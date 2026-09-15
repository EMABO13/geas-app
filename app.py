import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime, timedelta
import os
import requests
import re
import json

try:
    import gspread
    from google.oauth2.service_account import Credentials
    GSPREAD_AVAILABLE = True
except ImportError:
    GSPREAD_AVAILABLE = False

# --- CONFIGURAZIONI INIZIALI E GRUPPI ---
st.set_page_config(layout="wide", page_title="GEAS BASKET - Dashboard Avanzata", page_icon="🏀")

GEAS_RED = "#E3182D"
GEAS_BLACK = "#121212"
GEAS_GOLD = "#D2BFA4"

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
IMG_PATH = os.path.join(CURRENT_DIR, "image.png")
CALENDAR_FILE = os.path.join(CURRENT_DIR, "calendar_data.json")
EXT_LOAD_FILE = os.path.join(CURRENT_DIR, "external_load.csv")

# Definizione dei roster in base al documento ufficiale
ROSTER_U19 = [
    "Appetiti Arianna", "Trezzi Francesca", "Bettoni Rebecca", "Rovello Giorgia",
    "Magni Emilia", "Connelli Grace", "Bianchi Emma", "Alfieri Fiamma",
    "Sacca Federica", "Fiani Carlotta", "Porcelli Paola"
]

ROSTER_U17 = [
    "Alfieri Fiamma", "Sacca Federica", "Pozzi Rebecca", "Raimondi Vittoria", 
    "Trerotola Asia", "Fiani Carlotta", "Porcelli Paola", "Villani Alice", 
    "Sala Emma", "Zanotti Anna", "Barchiellini Cecilia"
]

ALTRE_ATLETE = ["Cuomo Lara", "Turconi Margherita"]

ROSTER = sorted(list(set(ROSTER_U19 + ROSTER_U17 + ALTRE_ATLETE)))

# --- FUNZIONI GOOGLE SHEETS & LOCALI ---
def get_gclient():
    if GSPREAD_AVAILABLE and "gcp_service_account" in st.secrets:
        try:
            creds = Credentials.from_service_account_info(
                st.secrets["gcp_service_account"],
                scopes=["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
            )
            return gspread.authorize(creds)
        except Exception as e:
            st.sidebar.error(f"Errore Autenticazione Cloud: {e}")
    return None

def get_sheet_id(url):
    match = re.search(r'/d/([a-zA-Z0-9-_]+)', url)
    return match.group(1) if match else None

def load_calendar_data(url):
    client = get_gclient()
    sheet_id = get_sheet_id(url)
    if client and sheet_id:
        try:
            sh = client.open_by_key(sheet_id)
            ws = sh.worksheet("Calendario")
            records = ws.get_all_records()
            cal_data = {}
            for r in records:
                try:
                    cal_data[str(r['Data'])] = json.loads(r['JSON'])
                except: pass
            return cal_data
        except gspread.WorksheetNotFound:
            pass 
        except Exception as e:
            pass 

    if os.path.exists(CALENDAR_FILE):
        with open(CALENDAR_FILE, 'r') as f: return json.load(f)
    return {}

def save_calendar_data(data, url):
    client = get_gclient()
    sheet_id = get_sheet_id(url)
    if client and sheet_id:
        try:
            sh = client.open_by_key(sheet_id)
            try:
                ws = sh.worksheet("Calendario")
            except gspread.WorksheetNotFound:
                ws = sh.add_worksheet(title="Calendario", rows="1000", cols="2")
            
            rows = [['Data', 'JSON']]
            for k, v in data.items():
                rows.append([k, json.dumps(v)])
            
            ws.clear()
            try:
                ws.update(values=rows, range_name="A1")
            except TypeError:
                ws.update("A1", rows)
        except Exception as e:
            st.error(f"Impossibile salvare il Calendario su Google Sheets. Errore: {e}")
            
    with open(CALENDAR_FILE, 'w') as f: json.dump(data, f, indent=4)

# RIPRISTINO VECCHIO SISTEMA LETTURA DATE PER MANTENERE COMPATIBILITA'
def load_ext_load(url):
    client = get_gclient()
    sheet_id = get_sheet_id(url)
    
    if client and sheet_id:
        try:
            sh = client.open_by_key(sheet_id)
            ws = sh.worksheet("Carico_Esterno")
            records = ws.get_all_records()
            if records:
                df = pd.DataFrame(records)
                if 'Data' in df.columns:
                    # Ritorno all'esatto metodo originale
                    df['Data'] = pd.to_datetime(df['Data'], errors='coerce', dayfirst=True).dt.normalize()
                    df = df.dropna(subset=['Data'])
                    return df
        except gspread.WorksheetNotFound:
            pass
        except Exception:
            pass

    if os.path.exists(EXT_LOAD_FILE):
        try:
            df = pd.read_csv(EXT_LOAD_FILE)
            if 'Data' in df.columns:
                df['Data'] = pd.to_datetime(df['Data'], errors='coerce', dayfirst=True).dt.normalize()
                df = df.dropna(subset=['Data'])
                return df
        except Exception:
            pass
            
    return pd.DataFrame(columns=['Data', 'Esercitazione', 'Peso', 'Minuti', 'Carico_Esterno'])

# RIPRISTINO VECCHIO SISTEMA SALVATAGGIO CON FIX PER CELLE VUOTE
def save_ext_load(df, url):
    client = get_gclient()
    sheet_id = get_sheet_id(url)
    df_out = df.copy()
    
    df_out = df_out.dropna(subset=['Data']) 
    
    if client and sheet_id:
        try:
            sh = client.open_by_key(sheet_id)
            try:
                ws = sh.worksheet("Carico_Esterno")
            except gspread.WorksheetNotFound:
                ws = sh.add_worksheet(title="Carico_Esterno", rows="1000", cols="5")
            
            # Formattazione originale YYYY-MM-DD
            df_out['Data'] = df_out['Data'].dt.strftime('%Y-%m-%d')
            # Previene crash su valori non numerici (celle vuote)
            df_out = df_out.fillna('')
            
            rows = [df_out.columns.values.tolist()] + df_out.values.tolist()
            ws.clear()
            try:
                ws.update(values=rows, range_name="A1")
            except TypeError:
                ws.update("A1", rows)
        except Exception as e:
            st.error(f"Impossibile salvare su Google Sheets. Errore: {e}")

    df_out.to_csv(EXT_LOAD_FILE, index=False)

def calc_ewma(series, span):
    return series.ewm(span=span, adjust=False).mean()

@st.cache_data(ttl=60)
def fetch_raw_data(url):
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            import io
            return pd.read_csv(io.StringIO(response.text)), None
        return pd.DataFrame(), f"HTTP Error {response.status_code}"
    except Exception as e:
        return pd.DataFrame(), str(e)

def process_data(df_raw, col_data, col_atleta, col_rpe):
    if df_raw.empty or not all([col_data, col_atleta, col_rpe]): return pd.DataFrame()
    df = df_raw[[col_data, col_atleta, col_rpe]].copy()
    df.columns = ['Data', 'Atleta', 'RPE']
    df = df.dropna(how='all')
    
    def pulisci_data(x):
        try:
            s = str(x).strip()
            if s.lower() in ['nan', 'none', 'nat', '']: return pd.NaT
            return pd.to_datetime(s.split()[0], dayfirst=True)
        except: return pd.NaT
            
    df['Data'] = df['Data'].apply(pulisci_data).dt.normalize()
    
    def pulisci_rpe(x):
        try:
            s = str(x).strip()
            match = re.search(r'(\d+)', s)
            if match: return float(match.group(1))
            return np.nan
        except: return np.nan
            
    df['RPE'] = df['RPE'].apply(pulisci_rpe)
    df = df.dropna(subset=['Data', 'RPE'])
    
    df['Atleta'] = df['Atleta'].astype(str).str.title().str.strip()
    
    def match_roster(nome_form):
        for nome_ufficiale in ROSTER:
            if nome_ufficiale.split()[0].lower() in nome_form.lower():
                return nome_ufficiale
        return nome_form 

    df['Atleta_Norm'] = df['Atleta'].apply(match_roster)
    df = df[df['Atleta_Norm'].isin(ROSTER)]
    df['Atleta'] = df['Atleta_Norm']
    
    return df

def process_daily_data(df_base, cal_data, default_duration=90):
    if df_base.empty: return pd.DataFrame()
    
    min_date = df_base['Data'].min()
    oggi = pd.to_datetime('today').normalize()
    max_date = max(df_base['Data'].max(), oggi)
    all_dates = pd.date_range(start=min_date, end=max_date, freq='D')
    
    new_rows = []
    
    for atleta in ROSTER:
        atleta_data = df_base[df_base['Atleta'] == atleta].copy()
        
        is_u19 = atleta in ROSTER_U19
        is_u17 = atleta in ROSTER_U17
        
        for d in all_dates:
            d_str = d.strftime('%Y-%m-%d')
            day_info = cal_data.get(d_str, {})
            
            gruppi_info = []
            if is_u19 and "U19" in day_info: gruppi_info.append(day_info["U19"])
            if is_u17 and "U17" in day_info: gruppi_info.append(day_info["U17"])
            if "Global" in day_info: gruppi_info.append(day_info["Global"]) 
            
            if not gruppi_info:
                if 'type' in day_info: 
                    g_info = day_info
                else:
                    g_info = {'type': 'Allenamento', 'duration': default_duration, 'rest': False}
            else:
                has_match = any(g.get('type') == 'Partita' for g in gruppi_info)
                has_train = any(g.get('type') == 'Allenamento' for g in gruppi_info)
                
                if has_match:
                    g_info = next(g for g in gruppi_info if g.get('type') == 'Partita')
                elif has_train:
                    g_info = next(g for g in gruppi_info if g.get('type') == 'Allenamento')
                else:
                    g_info = gruppi_info[0]

            if g_info.get('rest', False):
                new_rows.append({'Data': d, 'Atleta': atleta, 'RPE': 0, 'Durata': 0, 'Tipo': 'Riposo', 'Gruppo_Tag': 'Riposo'})
            else:
                rpe_row = atleta_data[atleta_data['Data'] == d]
                tipo_giorno = g_info.get('type', 'Allenamento')
                
                if tipo_giorno == 'Partita': durata = g_info.get('player_minutes', {}).get(atleta, 40)
                else: durata = g_info.get('duration', default_duration)
                
                if not rpe_row.empty:
                    new_rows.append({'Data': d, 'Atleta': atleta, 'RPE': rpe_row['RPE'].mean(), 'Durata': durata, 'Tipo': tipo_giorno, 'Gruppo_Tag': tipo_giorno})
                else:
                    new_rows.append({'Data': d, 'Atleta': atleta, 'RPE': 0, 'Durata': durata, 'Tipo': f"{tipo_giorno} (Assente)", 'Gruppo_Tag': tipo_giorno})
                    
    df_full = pd.DataFrame(new_rows)
    df_full['sRPE'] = df_full['RPE'] * df_full['Durata']
    
    def assign_primary_group(name):
        if name in ROSTER_U19 and name in ROSTER_U17: return "Doppio Roster (U19/U17)"
        elif name in ROSTER_U19: return "U19"
        elif name in ROSTER_U17: return "U17"
        return "Altro"
        
    df_full['Gruppo'] = df_full['Atleta'].apply(assign_primary_group)
    return df_full

def calcola_metriche(df_atleta):
    df = df_atleta.sort_values('Data').set_index('Data').copy()
    if len(df) > 1:
        idx = pd.date_range(df.index.min(), df.index.max(), name='Data')
        df = df.reindex(idx)
        df['RPE'] = df['RPE'].fillna(0)
        df['Durata'] = df['Durata'].fillna(0)
        df['sRPE'] = df['RPE'] * df['Durata']
        df['Tipo'] = df['Tipo'].fillna('Non specificato')
        df['Atleta'] = df['Atleta'].ffill().bfill()
        
    df['Acuto_7d'] = calc_ewma(df['sRPE'], span=7)
    df['Cronico_28d'] = calc_ewma(df['sRPE'], span=28)
    df['ACWR_EWMA'] = np.where(df['Cronico_28d'] > 0, df['Acuto_7d'] / df['Cronico_28d'], 0)
    return df


# --- UI APP ---
if os.path.exists(IMG_PATH): st.sidebar.image(IMG_PATH, use_container_width=True)
st.sidebar.markdown(f"📅 **Oggi:** {datetime.today().strftime('%d/%m/%Y')}")

if GSPREAD_AVAILABLE and "gcp_service_account" in st.secrets:
    st.sidebar.success("☁️ Sincronizzazione Cloud Attiva")
else:
    st.sidebar.info("💾 Salvataggio Locale Attivo (Cloud NON configurato o non accessibile)")

page = st.sidebar.radio("📌 MENU NAVIGAZIONE", [
    "🏠 Home Squadra", 
    "👤 Rapporto Interno/Esterno (Atleta)", 
    "📈 Gestione Carico Esterno",
    "📊 Compliance % (Assenze)",
    "📅 Calendario & Partite", 
    "📚 Formazione & Spiegazioni"
])

st.sidebar.markdown("---")
durata_globale = st.sidebar.number_input("⏳ Durata Sessione Default", min_value=10, max_value=180, value=90, step=5)

DEFAULT_URL = "https://docs.google.com/spreadsheets/d/1deIrnozT_kNkdFFCwgxBRIeiGo_50ikoGw1jRC1iywA/export?format=csv"
with st.sidebar.expander("⚙️ Sorgente Dati Google (Form)"):
    url_google = st.text_input("URL CSV", value=DEFAULT_URL)
    df_raw, err = fetch_raw_data(url_google)
    if not df_raw.empty:
        cols = df_raw.columns.tolist()
        col_data = st.selectbox("Colonna Data", cols, index=0)
        col_atleta = st.selectbox("Colonna Atleta", cols, index=1 if len(cols)>1 else 0)
        col_rpe = st.selectbox("Colonna RPE", cols, index=2 if len(cols)>2 else 0)
    else:
        st.error(f"Errore: {err}")
        col_data = col_atleta = col_rpe = None

# --- CARICAMENTO DATI ---
calendar_data = load_calendar_data(url_google)
df_ext = load_ext_load(url_google)

df_base = process_data(df_raw, col_data, col_atleta, col_rpe)
df_full = process_daily_data(df_base, calendar_data, default_duration=durata_globale)


# --- PAGINE ---
if page == "🏠 Home Squadra":
    st.title("Panoramica Globale U19/U17")
    
    if not df_full.empty:
        filter_group = st.radio("Filtra Vista per Gruppo:", ["Tutta la Squadra", "Solo U19", "Solo U17"], horizontal=True)
        
        if filter_group == "Solo U19":
            roster_attivo = ROSTER_U19
            df_view = df_full[df_full['Atleta'].isin(ROSTER_U19)]
        elif filter_group == "Solo U17":
            roster_attivo = ROSTER_U17
            df_view = df_full[df_full['Atleta'].isin(ROSTER_U17)]
        else:
            roster_attivo = ROSTER
            df_view = df_full

        st.subheader("🔴🟡🟢 Status Infortuni (ACWR EWMA Odierno)")
        cols = st.columns(4)
        for i, atleta in enumerate(roster_attivo):
            df_a = calcola_metriche(df_full[df_full['Atleta'] == atleta])
            if not df_a.empty:
                acwr = df_a.iloc[-1]['ACWR_EWMA']
                
                if acwr > 1.5: c, s, e = GEAS_RED, "Rischio Alto", "🔴"
                elif acwr < 0.8: c, s, e = "#F39C12", "Sottoallen.", "🟡"
                else: c, s, e = "#27AE60", "Ottimale", "🟢"
                
                with cols[i % 4]:
                    st.markdown(f"""<div style="background-color:#F8F9F9; padding:10px; border-radius:8px; margin-bottom:10px; border-left: 5px solid {c}; box-shadow: 1px 1px 3px rgba(0,0,0,0.1);"><h5 style="margin:0; color:#333;">{atleta}</h5><p style="margin:2px 0; font-size:18px; font-weight:bold; color:{c};">{acwr:.2f}</p><p style="margin:0; font-size:12px; color:#777;">{e} {s}</p></div>""", unsafe_allow_html=True)

        st.markdown("---")
        st.subheader("📈 Andamento Carico Interno Squadra (sRPE)")
        
        tf = st.radio("Seleziona Vista Temporale:", ["Ultimi 7 Giorni", "Ultimi 30 Giorni", "Tutto lo storico"], horizontal=True)
        oggi = pd.to_datetime('today').normalize()
        
        def get_bar_color(date, group_filter):
            date_str = date.strftime('%Y-%m-%d')
            day_info = calendar_data.get(date_str, {})
            
            if group_filter == "Solo U19":
                if day_info.get("U19", {}).get("type") == "Partita": return GEAS_RED
            elif group_filter == "Solo U17":
                if day_info.get("U17", {}).get("type") == "Partita": return GEAS_RED
            else:
                if day_info.get("U19", {}).get("type") == "Partita" or \
                   day_info.get("U17", {}).get("type") == "Partita" or \
                   day_info.get("Global", {}).get("type") == "Partita" or \
                   day_info.get("type") == "Partita": 
                    return GEAS_RED
            return GEAS_GOLD
        
        df_team = df_view.groupby('Data')['sRPE'].mean().reset_index()
        if tf == "Ultimi 7 Giorni": df_team_filt = df_team[df_team['Data'] >= oggi - timedelta(days=7)].copy()
        elif tf == "Ultimi 30 Giorni": df_team_filt = df_team[df_team['Data'] >= oggi - timedelta(days=30)].copy()
        else: df_team_filt = df_team.copy()
            
        if not df_team_filt.empty:
            df_team_filt['Color'] = df_team_filt['Data'].apply(lambda d: get_bar_color(d, filter_group))
            
            fig = go.Figure()
            fig.add_trace(go.Bar(
                x=df_team_filt['Data'].dt.strftime('%d/%m'), 
                y=df_team_filt['sRPE'], 
                marker_color=df_team_filt['Color'], 
                text=df_team_filt['sRPE'].round(0), 
                textposition='auto',
                hovertemplate="Data: %{x}<br>Media sRPE: %{y}<extra></extra>"
            ))
            fig.update_layout(template="plotly_white", margin=dict(t=20, b=20, l=20, r=20))
            st.plotly_chart(fig, use_container_width=True)
            st.markdown(f"*Legenda Colori (Media Squadra): <span style='color:{GEAS_GOLD}'>■ Allenamento</span> | <span style='color:{GEAS_RED}'>■ Partita (Media influenzata dai minutaggi)</span>*", unsafe_allow_html=True)
        else:
            st.info("Nessun dato nel periodo selezionato.")
        
        st.markdown("---")
        st.subheader("🔍 Esamina RPE Giornaliero per Atleta")
        atleta_home_sel = st.selectbox("Seleziona Giocatrice per vedere il suo dettaglio giornaliero", roster_attivo)
        
        if atleta_home_sel:
            df_a_home = df_full[df_full['Atleta'] == atleta_home_sel].copy()
            
            if tf == "Ultimi 7 Giorni": df_a_home = df_a_home[df_a_home['Data'] >= oggi - timedelta(days=7)]
            elif tf == "Ultimi 30 Giorni": df_a_home = df_a_home[df_a_home['Data'] >= oggi - timedelta(days=30)]
                
            fig_a = go.Figure()
            colors_h = []
            for tipo in df_a_home['Tipo']:
                if 'Riposo' in tipo: colors_h.append('gray')
                elif 'Partita' in tipo: colors_h.append(GEAS_RED)
                elif 'Assente' in tipo: colors_h.append('red') 
                else: colors_h.append('#3498db')
                
            fig_a.add_trace(go.Bar(
                x=df_a_home['Data'].dt.strftime('%d/%m'), y=df_a_home['RPE'],
                marker_color=colors_h, text=df_a_home['RPE'].replace(0, '').apply(lambda x: str(round(x,1)) if x != '' else ''), textposition='auto',
                name="RPE (0-10)", customdata=df_a_home['Tipo'],
                hovertemplate="Data: %{x}<br>RPE: %{y}<br>Tipo: %{customdata}<extra></extra>"
            ))
            
            media_rpe_home = df_a_home[df_a_home['RPE']>0]['RPE'].mean()
            if not pd.isna(media_rpe_home):
                fig_a.add_hline(y=media_rpe_home, line_dash="dash", line_color="#333", annotation_text="Media del Periodo")
                
            fig_a.update_layout(template="plotly_white", yaxis_range=[0, 11], margin=dict(t=20, b=20, l=20, r=20))
            st.plotly_chart(fig_a, use_container_width=True)
            st.markdown(f"*Legenda Colori: <span style='color:#3498db'>■ Allenamento</span> | <span style='color:{GEAS_RED}'>■ Partita</span> | <span style='color:gray'>■ Riposo</span> | <span style='color:red'>■ Assente/Mancante</span>*", unsafe_allow_html=True)
    else:
        st.warning("Nessun dato RPE caricato.")

elif page == "📈 Gestione Carico Esterno":
    st.title("Gestione Carico Esterno (Coach)")
    
    colA, colB = st.columns([1, 2])
    with colA:
        st.subheader("Inserisci Esercitazione")
        with st.form("ext_form"):
            e_data = st.date_input("Data", datetime.today())
            e_nome = st.text_input("Nome Esercitazione (es. 4v4 a tutto campo)")
            e_peso = st.slider("Peso/Intensità (1-10)", 1, 10, 5)
            e_min = st.number_input("Durata (Minuti)", 1, 120, 15)
            
            if st.form_submit_button("Salva nel Registro"):
                nuovo_carico = e_peso * e_min
                nuova_riga = pd.DataFrame([{'Data': pd.to_datetime(e_data), 'Esercitazione': e_nome, 'Peso': e_peso, 'Minuti': e_min, 'Carico_Esterno': nuovo_carico}])
                if df_ext.empty:
                    df_ext = pd.DataFrame(columns=['Data', 'Esercitazione', 'Peso', 'Minuti', 'Carico_Esterno'])
                df_ext = pd.concat([df_ext, nuova_riga], ignore_index=True)
                
                save_ext_load(df_ext, url_google)
                st.success("Esercitazione salvata!")
                st.rerun()
                
    with colB:
        st.subheader("Andamento Carico Esterno Totale")
        if not df_ext.empty:
            view = st.radio("Vista Grafico:", ["Giornaliero", "Settimanale"], horizontal=True)
            df_g_base = df_ext.dropna(subset=['Data']).copy()
            
            if view == "Giornaliero":
                # Grafico in ordine rigoroso considerando date da inizio a fine
                min_date = df_g_base['Data'].min()
                max_date = df_g_base['Data'].max()
                
                if pd.isna(min_date):
                    min_date = pd.to_datetime('today').normalize() - timedelta(days=7)
                    max_date = pd.to_datetime('today').normalize()
                
                all_days = pd.date_range(start=min_date, end=max_date, freq='D')
                
                df_g = df_g_base.groupby('Data')['Carico_Esterno'].sum().reindex(all_days, fill_value=0).reset_index()
                df_g.columns = ['Data', 'Carico_Esterno']
                df_g = df_g.sort_values('Data', ascending=True)
                
                fig = go.Figure(go.Bar(x=df_g['Data'].dt.strftime('%d/%m/%Y'), y=df_g['Carico_Esterno'], marker_color=GEAS_RED))
                fig.update_layout(template="plotly_white", xaxis_title="Data")
            else:
                df_g_base['Settimana'] = df_g_base['Data'].dt.isocalendar().week
                df_g = df_g_base.groupby('Settimana')['Carico_Esterno'].sum().reset_index()
                df_g = df_g.sort_values('Settimana', ascending=True)
                fig = go.Figure(go.Bar(x=df_g['Settimana'].astype(str), y=df_g['Carico_Esterno'], marker_color=GEAS_RED))
                fig.update_layout(template="plotly_white", xaxis_title="Numero Settimana dell'anno")
                
            st.plotly_chart(fig, use_container_width=True)
            
    st.markdown("---")
    st.header("📝 Diario Esercitazioni e Modifica")
    
    col_ed1, col_ed2 = st.columns(2)
    with col_ed1:
        st.subheader("Modifica / Elimina Record")
        if not df_ext.empty:
            df_storico = df_ext.sort_values('Data', ascending=False).copy()
            df_storico = df_storico.dropna(subset=['Data']) 
            
            # Utilizza DatetimeColumn originale per formattare senza toccare l'oggetto python base
            edited_df = st.data_editor(
                df_storico, num_rows="dynamic", use_container_width=True, hide_index=True,
                column_config={"Data": st.column_config.DatetimeColumn("Data", format="DD/MM/YYYY")}
            )
            
            if not edited_df.equals(df_storico):
                edited_df['Data'] = pd.to_datetime(edited_df['Data'], errors='coerce').dt.normalize()
                edited_df = edited_df.dropna(subset=['Data'])
                edited_df['Peso'] = pd.to_numeric(edited_df['Peso'], errors='coerce').fillna(0)
                edited_df['Minuti'] = pd.to_numeric(edited_df['Minuti'], errors='coerce').fillna(0)
                edited_df['Carico_Esterno'] = edited_df['Peso'] * edited_df['Minuti']
                
                save_ext_load(edited_df, url_google)
                st.success("Modifiche salvate con successo!")
                st.rerun()
        else:
            st.info("Nessuna esercitazione presente da modificare.")

    with col_ed2:
        st.subheader("Tracciamento Allenamenti (Diario Coach)")
        
        df_storico_disp = df_ext.dropna(subset=['Data']).copy() if not df_ext.empty else pd.DataFrame(columns=['Data'])
        
        # Calendario dinamico: va dalla data MASSIMA esistente a ritroso (massimo 30 giorni) 
        # Cosi include sempre anche le date vecchie lette erroneamente nel futuro!
        if not df_storico_disp.empty:
            max_d = df_storico_disp['Data'].max()
            min_d = df_storico_disp['Data'].min()
            start_d = max(min_d, max_d - timedelta(days=30))
            giorni_calendario = pd.date_range(start=start_d, end=max_d, freq='D')[::-1]
        else:
            oggi = pd.to_datetime('today').normalize()
            giorni_calendario = pd.date_range(end=oggi, periods=14, freq='D')[::-1]
            
        for g in giorni_calendario:
            dati_giorno = df_storico_disp[df_storico_disp['Data'] == g] if not df_storico_disp.empty else pd.DataFrame()
            data_str = g.strftime('%d/%m/%Y')
            
            if not dati_giorno.empty:
                carico_tot = dati_giorno['Carico_Esterno'].sum()
                with st.expander(f"🏀 {data_str} - Carico Totale: {carico_tot}", expanded=False):
                    for _, row in dati_giorno.iterrows():
                        st.markdown(f"- **{row.get('Esercitazione', 'N/D')}** | Intensità: {row.get('Peso', 0)}/10 | Durata: {row.get('Minuti', 0)}'")
            else:
                with st.expander(f"⏸️ {data_str} - Nessun carico registrato", expanded=False):
                    st.write("Nessuna esercitazione inserita per questa giornata.")

elif page == "👤 Rapporto Interno/Esterno (Atleta)":
    st.title("Stato di Forma: Interno vs Esterno")
    
    if not df_full.empty:
        atleta_sel = st.selectbox("Seleziona Giocatrice", ROSTER)
        df_a = calcola_metriche(df_full[df_full['Atleta'] == atleta_sel])
        df_ext_g = df_ext.groupby('Data').agg({'Carico_Esterno': 'sum', 'Peso': 'mean'}).reset_index() if not df_ext.empty else pd.DataFrame(columns=['Data','Carico_Esterno','Peso'])
        df_merge = pd.merge(df_a.reset_index(), df_ext_g, on='Data', how='left').fillna(0)
        df_merge_all = df_merge[df_merge['Tipo'] == 'Allenamento'].copy()
        
        if not df_merge_all.empty and df_merge_all['Peso'].sum() > 0:
            ultimi_allenamenti = df_merge_all.tail(7) 
            media_rpe = ultimi_allenamenti[ultimi_allenamenti['RPE']>0]['RPE'].mean()
            media_peso = ultimi_allenamenti[ultimi_allenamenti['Peso']>0]['Peso'].mean()
            diff = media_rpe - media_peso
            
            st.subheader("💡 Analisi Adattamento (Efficienza)")
            col1, col2, col3 = st.columns(3)
            col1.metric("Media RPE Atleta (Recente)", f"{media_rpe:.1f}/10")
            col2.metric("Media Difficoltà Coach (Recente)", f"{media_peso:.1f}/10")
            
            with col3:
                if pd.isna(diff): st.info("Dati insufficienti")
                elif diff > 1.5: st.error("🔴 **FATICAMENTO**\nSente il carico molto più pesante di quanto previsto.")
                elif diff < -1.5: st.success("🟢 **OTTIMO ADATTAMENTO**\nSente il carico più leggero del previsto.")
                else: st.success("🟡 **IN LINEA**\nLa fatica percepita è coerente con l'allenamento proposto.")
            
            st.markdown("---")
            st.subheader("Grafico Sovrapposto (Valori sRPE vs Valori Arbitrari Coach)")
            fig = make_subplots(specs=[[{"secondary_y": True}]])
            fig.add_trace(go.Bar(x=df_merge_all['Data'].dt.strftime('%d/%m'), y=df_merge_all['Carico_Esterno'], name='Carico Esterno (Coach)', marker_color="#E0E0E0"), secondary_y=False)
            fig.add_trace(go.Scatter(x=df_merge_all['Data'].dt.strftime('%d/%m'), y=df_merge_all['sRPE'], mode='lines+markers', name='Carico Interno (Atleta)', line=dict(color=GEAS_RED, width=3)), secondary_y=True)
            fig.update_layout(template="plotly_white", hovermode="x unified")
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Per vedere l'analisi di adattamento devi registrare dei carichi esterni (allenamenti).")

elif page == "📊 Compliance % (Assenze)":
    st.title("Monitoraggio Compilazioni Form RPE")
    if not df_base.empty:
        giorni_lavoro = []
        oggi = pd.to_datetime('today').normalize()
        for d in pd.date_range(start=df_base['Data'].min(), end=oggi):
            d_str = d.strftime('%Y-%m-%d')
            info = calendar_data.get(d_str, {})
            rest_global = info.get('Global', info).get('rest', False)
            if not rest_global: giorni_lavoro.append(d)
                
        tot_giorni = len(giorni_lavoro)
        comp_data = []
        for atleta in ROSTER:
            atleta_rpe = df_base[df_base['Atleta'] == atleta]
            giorni_compilati = atleta_rpe['Data'].dt.normalize().unique()
            match = len([g for g in giorni_lavoro if g in giorni_compilati])
            perc = (match / tot_giorni * 100) if tot_giorni > 0 else 0
            comp_data.append({'Atleta': atleta, 'Compliance': perc, 'Compilati': match})
            
        df_comp = pd.DataFrame(comp_data).sort_values('Compliance', ascending=True)
        st.subheader(f"Statistiche su {tot_giorni} sessioni (Esclusi Riposi)")
        
        fig = go.Figure()
        colors = ['#E3182D' if x < 70 else ('#F39C12' if x < 90 else '#27AE60') for x in df_comp['Compliance']]
        fig.add_trace(go.Bar(
            y=df_comp['Atleta'], x=df_comp['Compliance'], orientation='h', marker_color=colors,
            text=df_comp['Compliance'].round(1).astype(str) + "%", textposition='auto'
        ))
        fig.update_layout(template="plotly_white", height=600, xaxis_title="% Compilazione", xaxis=dict(range=[0,100]))
        st.plotly_chart(fig, use_container_width=True)

elif page == "📅 Calendario & Partite":
    st.title("Programmazione: Riposi, Allenamenti, Partite")
    
    col1, col2 = st.columns([1,2])
    with col1:
        st.subheader("Modifica Giornata")
        data_sel = st.date_input("Seleziona Data", datetime.today())
        data_str = data_sel.strftime('%Y-%m-%d')
        
        if data_str not in calendar_data:
            calendar_data[data_str] = {
                "U19": {'type': 'Allenamento', 'duration': durata_globale, 'rest': False},
                "U17": {'type': 'Allenamento', 'duration': durata_globale, 'rest': False}
            }
        
        target_group = st.selectbox("Imposta programma per:", ["U19", "U17"])
        
        if "type" in calendar_data[data_str]:
            old_data = calendar_data[data_str].copy()
            calendar_data[data_str] = {"U19": old_data, "U17": old_data}

        dati_target = calendar_data[data_str].get(target_group, {'type': 'Allenamento', 'duration': durata_globale, 'rest': False})
        
        idx_tipo = 0
        if dati_target.get('type') == 'Partita': idx_tipo = 1
        elif dati_target.get('rest'): idx_tipo = 2
            
        tipo_giorno = st.radio("Cosa è previsto?", ["Allenamento", "Partita", "Riposo Totale"], index=idx_tipo)
                               
        if tipo_giorno == "Allenamento":
            durata_all = st.number_input(f"Minuti Allenamento ({target_group})", min_value=0, value=dati_target.get('duration', durata_globale))
            if st.button("Salva Allenamento"):
                calendar_data[data_str][target_group] = {'type': 'Allenamento', 'duration': durata_all, 'rest': False}
                save_calendar_data(calendar_data, url_google)
                st.success(f"Salvato Allenamento per {target_group}!")
                st.rerun()
                
        elif tipo_giorno == "Riposo Totale":
            if st.button("Salva come Riposo"):
                calendar_data[data_str][target_group] = {'type': 'Riposo', 'duration': 0, 'rest': True}
                save_calendar_data(calendar_data, url_google)
                st.success(f"Giorno di riposo registrato per {target_group}!")
                st.rerun()
                
        elif tipo_giorno == "Partita":
            st.info(f"Imposta il minutaggio esatto atlete {target_group} (Default: 40')")
            player_mins = dati_target.get('player_minutes', {})
            
            roster_da_mostrare = ROSTER_U19 if target_group == "U19" else ROSTER_U17
            
            with st.form("minutaggi_partita"):
                new_mins = {}
                for atleta in roster_da_mostrare:
                    new_mins[atleta] = st.number_input(f"{atleta}", min_value=0, max_value=60, value=player_mins.get(atleta, 40))
                if st.form_submit_button(f"Salva Partita {target_group}"):
                    calendar_data[data_str][target_group] = {'type': 'Partita', 'duration': 40, 'rest': False, 'player_minutes': new_mins}
                    save_calendar_data(calendar_data, url_google)
                    st.success("Salvato!")
                    st.rerun()
                    
    with col2:
        st.subheader("Registro Configurazioni")
        if calendar_data:
            disp_data = []
            for d, v in calendar_data.items():
                if "type" in v:
                    disp_data.append({'Data': d, 'Gruppo': 'Global', 'Tipo': v.get('type')})
                else:
                    if "U19" in v: disp_data.append({'Data': d, 'Gruppo': 'U19', 'Tipo': v['U19'].get('type')})
                    if "U17" in v: disp_data.append({'Data': d, 'Gruppo': 'U17', 'Tipo': v['U17'].get('type')})
            
            if disp_data:
                df_cal = pd.DataFrame(disp_data)
                df_cal['Data'] = pd.to_datetime(df_cal['Data'])
                df_cal = df_cal.sort_values('Data', ascending=False)
                st.dataframe(df_cal.style.format({"Data": lambda t: t.strftime("%d/%m/%Y")}), use_container_width=True)
                
            if st.button("Resetta tutto il calendario"):
                save_calendar_data({}, url_google)
                st.rerun()

elif page == "📚 Formazione & Spiegazioni":
    st.title("🧠 Guida ai Parametri per lo Staff Tecnico")
    st.markdown("""
    Questa sezione è pensata per aiutare gli allenatori e lo staff a leggere e interpretare le metriche presenti nella dashboard. 
    L'obiettivo è fornire una spiegazione chiara dei parametri utilizzati per monitorare lo stato di forma e il carico di lavoro delle atlete.
    """)
    
    with st.expander("1. 📊 RPE e Carico Interno (sRPE)"):
        st.markdown("""
        **RPE (Rating of Perceived Exertion - Scala 1-10)**
        È il valore che l'atleta assegna alla difficoltà dell'allenamento. Riflette non solo lo sforzo fisico, ma lo stress globale percepito in quel momento.
        *   **1-3:** Molto leggero (es. sedute di tiro o recupero)
        *   **4-6:** Moderato (es. lavoro tattico a metà campo)
        *   **7-8:** Duro (es. lavoro ad alta intensità, transizioni)
        *   **9-10:** Massimale (es. lavoro metabolico estremo o gara intensa)
        
        **sRPE (Session RPE = RPE x Minuti)**
        Rappresenta il **Carico Interno**. Se un allenamento di 90 minuti viene valutato 6, il carico interno registrato sarà 540. Questo valore quantifica l'impatto fisiologico reale della seduta sull'atleta.
        """)
        
    with st.expander("2. 📋 Carico Esterno e Unità Arbitrarie (AU)"):
        st.markdown("""
        Il **Carico Esterno** quantifica il lavoro oggettivo richiesto dallo staff durante la seduta. In assenza di sensori GPS, la dashboard permette di calcolarlo manualmente.
        
        Si assegna un'intensità arbitraria (Peso da 1 a 10) all'esercitazione:
        *   **1-3:** Esercizi statici, tiri liberi, walk-through.
        *   **4-6:** Tecnica individuale, 3v3 a metà campo, situazioni tattiche.
        *   **7-8:** 5v5 a tutto campo, transizioni continue ad alta intensità.
        *   **9-10:** Lavoro metabolico a secco o situazioni di gioco massimali prolungate.
        
        Moltiplicando questo Peso per i minuti di durata dell'esercitazione, si ottengono le Unità Arbitrarie (AU) del carico esterno.
        """)
        
    with st.expander("3. ⚖️ Matrice Efficienza (Rapporto Interno/Esterno)"):
        st.markdown("""
        L'Efficienza mette a confronto l'intensità pianificata dallo staff (Carico Esterno) con la fatica realmente percepita dall'atleta (Carico Interno).
        
        *   🟢 **Efficienza Positiva (Esterno ALTO / Interno BASSO):** A fronte di un carico esterno elevato (es. peso 8), l'atleta percepisce uno sforzo inferiore (es. RPE 5). Indica un'ottima fitness e un buon adattamento al lavoro.
        *   🟡 **Neutra (Esterno = Interno):** La fatica percepita è coerente con l'intensità dell'allenamento proposto.
        *   🔴 **Efficienza Negativa (Esterno BASSO / Interno ALTO):** A fronte di un carico leggero, l'atleta percepisce un RPE alto. È un indicatore visivo di possibile fatica residua, stress o scarso recupero muscolare in quel momento.
        """)

    with st.expander("4. 📈 Indice di Rischio (ACWR) ed EWMA"):
        st.markdown("""
        L'**Acute:Chronic Workload Ratio (ACWR)** è una metrica utilizzata per monitorare il rapporto tra il carico di lavoro recente e quello storico. 
        Mette in relazione la fatica accumulata a breve termine (**Carico Acuto** - ultimi 7 giorni) con la base di lavoro costruita nel lungo periodo (**Carico Cronico** - ultimi 28 giorni). La dashboard utilizza la formula **EWMA** (Exponentially Weighted Moving Average), che assegna un peso maggiore agli allenamenti più recenti.
        
        **La lettura dei valori ACWR:**
        *   🔵 **< 0.8 (Sottoallenamento):** L'atleta sta affrontando un carico significativamente inferiore rispetto a quello storico.
        *   🟢 **0.8 - 1.3 (Sweet Spot):** Condizione di equilibrio. Il carico attuale è ben proporzionato rispetto alla base storica.
        *   🟡 **1.3 - 1.5 (Zona di Attenzione):** Il carico acuto sta crescendo rapidamente rispetto alla media dell'ultimo mese.
        *   🔴 **> 1.5 (Danger Zone):** Il picco di lavoro recente supera di oltre il 50% la base cronica dell'atleta. La letteratura sportiva indica che un innalzamento così brusco rispetto alle abitudini espone statisticamente a un maggior rischio di sovraccarico.
        """)
