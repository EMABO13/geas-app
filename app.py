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

# --- CONFIGURAZIONI INIZIALI ---
st.set_page_config(layout="wide", page_title="GEAS BASKET - Dashboard Avanzata", page_icon="🏀")

GEAS_RED = "#E3182D"
GEAS_BLACK = "#121212"
GEAS_GOLD = "#D2BFA4"

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
IMG_PATH = os.path.join(CURRENT_DIR, "image.png")
CALENDAR_FILE = os.path.join(CURRENT_DIR, "calendar_data.json")
EXT_LOAD_FILE = os.path.join(CURRENT_DIR, "external_load.csv")

ROSTER = sorted([
    "Appetiti Arianna", "Trezzi Francesca", "Bettoni Rebecca", "Rovello Giorgia",
    "Magni Emilia", "Connelli Grace", "Bianchi Emma", "Alfieri Fiamma",
    "Sacca Federica", "Fiani Carlotta", "Porcelli Paola", "Pozzi Rebecca",
    "Raimondi Vittoria", "Trerotola Asia", "Villani Alice", "Sala Emma",
    "Zanotti Anna", "Barchiellini Cecilia"
])

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
                # FIX: Rimuovi gli errori e le date vuote al caricamento
                df['Data'] = pd.to_datetime(df['Data'], errors='coerce').dt.normalize()
                df = df.dropna(subset=['Data'])
                return df
        except gspread.WorksheetNotFound:
            pass
        except Exception as e:
            pass

    if os.path.exists(EXT_LOAD_FILE):
        df = pd.read_csv(EXT_LOAD_FILE)
        df['Data'] = pd.to_datetime(df['Data'], errors='coerce').dt.normalize()
        df = df.dropna(subset=['Data'])
        return df
    return pd.DataFrame(columns=['Data', 'Esercitazione', 'Peso', 'Minuti', 'Carico_Esterno'])

def save_ext_load(df, url):
    client = get_gclient()
    sheet_id = get_sheet_id(url)
    df_out = df.copy()
    # FIX: Sicurezza extra in scrittura
    df_out = df_out.dropna(subset=['Data']) 
    
    if client and sheet_id:
        try:
            sh = client.open_by_key(sheet_id)
            try:
                ws = sh.worksheet("Carico_Esterno")
            except gspread.WorksheetNotFound:
                ws = sh.add_worksheet(title="Carico_Esterno", rows="1000", cols="5")
            
            df_out['Data'] = df_out['Data'].dt.strftime('%Y-%m-%d')
            rows = [df_out.columns.values.tolist()] + df_out.values.tolist()
            
            ws.clear()
            try:
                ws.update(values=rows, range_name="A1")
            except TypeError:
                ws.update("A1", rows)
        except Exception as e:
            st.error(f"Impossibile salvare il Carico Esterno su Google Sheets.")

    df_out.to_csv(EXT_LOAD_FILE, index=False)

# --- FUNZIONI CALCOLI ---
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
        for d in all_dates:
            d_str = d.strftime('%Y-%m-%d')
            day_info = cal_data.get(d_str, {'type': 'Allenamento', 'duration': default_duration, 'rest': False})
            
            if day_info.get('rest', False):
                new_rows.append({'Data': d, 'Atleta': atleta, 'RPE': 0, 'Durata': 0, 'Tipo': 'Riposo'})
            else:
                rpe_row = atleta_data[atleta_data['Data'] == d]
                tipo_giorno = day_info.get('type', 'Allenamento')
                
                if tipo_giorno == 'Partita': durata = day_info.get('player_minutes', {}).get(atleta, 40)
                else: durata = day_info.get('duration', default_duration)
                
                if not rpe_row.empty:
                    new_rows.append({'Data': d, 'Atleta': atleta, 'RPE': rpe_row['RPE'].mean(), 'Durata': durata, 'Tipo': tipo_giorno})
                else:
                    new_rows.append({'Data': d, 'Atleta': atleta, 'RPE': 0, 'Durata': durata, 'Tipo': f"{tipo_giorno} (Assente)"})
                    
    df_full = pd.DataFrame(new_rows)
    df_full['sRPE'] = df_full['RPE'] * df_full['Durata']
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
    st.sidebar.info("💾 Salvataggio Locale Attivo")

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
        st.subheader("🔴🟡🟢 Status Infortuni (ACWR EWMA Odierno)")
        cols = st.columns(4)
        for i, atleta in enumerate(ROSTER):
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
        
        df_team = df_full.groupby('Data')['sRPE'].mean().reset_index()
        
        if tf == "Ultimi 7 Giorni": df_team_filt = df_team[df_team['Data'] >= oggi - timedelta(days=7)]
        elif tf == "Ultimi 30 Giorni": df_team_filt = df_team[df_team['Data'] >= oggi - timedelta(days=30)]
        else: df_team_filt = df_team
            
        fig = go.Figure()
        fig.add_trace(go.Bar(x=df_team_filt['Data'].dt.strftime('%d/%m'), y=df_team_filt['sRPE'], marker_color=GEAS_GOLD, text=df_team_filt['sRPE'].round(0), textposition='auto'))
        fig.update_layout(template="plotly_white", margin=dict(t=20, b=20, l=20, r=20))
        st.plotly_chart(fig, use_container_width=True)
        
        st.markdown("---")
        st.subheader("🔍 Esamina RPE Giornaliero per Atleta")
        atleta_home_sel = st.selectbox("Seleziona Giocatrice per vedere il suo dettaglio giornaliero", ROSTER)
        
        if atleta_home_sel:
            df_a_home = df_full[df_full['Atleta'] == atleta_home_sel].copy()
            
            if tf == "Ultimi 7 Giorni": df_a_home = df_a_home[df_a_home['Data'] >= oggi - timedelta(days=7)]
            elif tf == "Ultimi 30 Giorni": df_a_home = df_a_home[df_a_home['Data'] >= oggi - timedelta(days=30)]
                
            fig_a = go.Figure()
            colors_h = []
            for tipo in df_a_home['Tipo']:
                if 'Riposo' in tipo: colors_h.append('gray')
                elif 'Partita' in tipo: colors_h.append(GEAS_GOLD)
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
            st.markdown("*Legenda Colori: <span style='color:#3498db'>■ Allenamento</span> | <span style='color:#D2BFA4'>■ Partita</span> | <span style='color:gray'>■ Riposo</span> | <span style='color:red'>■ Assente/Mancante</span>*", unsafe_allow_html=True)
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
                df_ext = pd.concat([df_ext, nuova_riga], ignore_index=True)
                save_ext_load(df_ext, url_google)
                st.success("Esercitazione salvata!")
                st.rerun()
                
    with colB:
        st.subheader("Andamento Carico Esterno Totale")
        if not df_ext.empty:
            view = st.radio("Vista Grafico:", ["Giornaliero", "Settimanale"], horizontal=True)
            df_g = df_ext.groupby('Data')['Carico_Esterno'].sum().reset_index()
            
            if view == "Settimanale":
                df_g['Settimana'] = df_g['Data'].dt.isocalendar().week
                df_g = df_g.groupby('Settimana')['Carico_Esterno'].sum().reset_index()
                fig = go.Figure(go.Bar(x=df_g['Settimana'].astype(str), y=df_g['Carico_Esterno'], marker_color=GEAS_RED))
                fig.update_layout(template="plotly_white", xaxis_title="Numero Settimana dell'anno")
            else:
                fig = go.Figure(go.Bar(x=df_g['Data'].dt.strftime('%d/%m/%Y'), y=df_g['Carico_Esterno'], marker_color=GEAS_RED))
                fig.update_layout(template="plotly_white", xaxis_title="Data")
                
            st.plotly_chart(fig, use_container_width=True)
            
    st.markdown("---")
    st.header("📝 Diario Esercitazioni e Modifica")
    
    if not df_ext.empty:
        col_ed1, col_ed2 = st.columns(2)
        with col_ed1:
            st.subheader("Modifica / Elimina Record")
            df_storico = df_ext.sort_values('Data', ascending=False).copy()
            # FIX: Eliminiamo qualsiasi riga vuota dal dataset prima di mostrare
            df_storico = df_storico.dropna(subset=['Data']) 
            
            edited_df = st.data_editor(
                df_storico, num_rows="dynamic", use_container_width=True, hide_index=True,
                column_config={"Data": st.column_config.DatetimeColumn("Data", format="DD/MM/YYYY")}
            )
            
            if not edited_df.equals(df_storico):
                # FIX: Quando l'utente salva, ignoriamo se ha lasciato la riga mezza vuota
                edited_df = edited_df.dropna(subset=['Data'])
                edited_df['Carico_Esterno'] = edited_df['Peso'] * edited_df['Minuti']
                save_ext_load(edited_df, url_google)
                st.success("Modifiche salvate con successo!")
                st.rerun()

        with col_ed2:
            st.subheader("Tracciamento Allenamenti (Diario Coach)")
            # FIX: Filtra in sicurezza le date
            df_storico = df_storico.dropna(subset=['Data'])
            giorni = df_storico['Data'].unique()
            for g in giorni[:10]:
                if pd.isna(g): continue # FIX: Se la data è non-valida la ignora
                dati_giorno = df_storico[df_storico['Data'] == g]
                data_str = pd.to_datetime(g).strftime('%d/%m/%Y')
                carico_tot = dati_giorno['Carico_Esterno'].sum()
                with st.expander(f"🏀 Allenamento del {data_str} (Carico Tot: {carico_tot})"):
                    for _, row in dati_giorno.iterrows():
                        st.markdown(f"- **{row['Esercitazione']}** | Intensità: {row['Peso']}/10 | Durata: {row['Minuti']}'")

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
            if not info.get('rest', False): giorni_lavoro.append(d)
                
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
        
        dati_giorno = calendar_data.get(data_str, {'type': 'Allenamento', 'duration': durata_globale, 'rest': False})
        idx_tipo = 0
        if dati_giorno.get('type') == 'Partita': idx_tipo = 1
        elif dati_giorno.get('rest'): idx_tipo = 2
            
        tipo_giorno = st.radio("Cosa è previsto per oggi?", ["Allenamento", "Partita", "Riposo Totale"], index=idx_tipo)
                               
        if tipo_giorno == "Allenamento":
            durata_all = st.number_input("Minuti Allenamento", min_value=0, value=dati_giorno.get('duration', durata_globale))
            if st.button("Salva Allenamento"):
                calendar_data[data_str] = {'type': 'Allenamento', 'duration': durata_all, 'rest': False}
                save_calendar_data(calendar_data, url_google)
                st.success("Salvato!")
                st.rerun()
                
        elif tipo_giorno == "Riposo Totale":
            if st.button("Salva come Riposo"):
                calendar_data[data_str] = {'type': 'Riposo', 'duration': 0, 'rest': True}
                save_calendar_data(calendar_data, url_google)
                st.success("Giorno di riposo registrato!")
                st.rerun()
                
        elif tipo_giorno == "Partita":
            st.info("Imposta il minutaggio esatto di ogni atleta in partita (Default: 40')")
            player_mins = dati_giorno.get('player_minutes', {})
            with st.form("minutaggi_partita"):
                new_mins = {}
                for atleta in ROSTER:
                    new_mins[atleta] = st.number_input(f"{atleta}", min_value=0, max_value=60, value=player_mins.get(atleta, 40))
                if st.form_submit_button("Salva Minutaggi Partita"):
                    calendar_data[data_str] = {'type': 'Partita', 'duration': 40, 'rest': False, 'player_minutes': new_mins}
                    save_calendar_data(calendar_data, url_google)
                    st.success("Salvato!")
                    st.rerun()
                    
    with col2:
        st.subheader("Registro Configurazioni")
        if calendar_data:
            df_cal = pd.DataFrame.from_dict(calendar_data, orient='index').reset_index()
            df_cal.columns = ['Data', 'Tipo', 'Durata Base', 'Riposo', 'Minuti Giocatori']
            df_cal['Data'] = pd.to_datetime(df_cal['Data'])
            df_cal = df_cal.sort_values('Data', ascending=False)
            st.dataframe(df_cal[['Data', 'Tipo', 'Durata Base', 'Riposo']].style.format({"Data": lambda t: t.strftime("%d/%m/%Y")}), use_container_width=True)
            if st.button("Resetta tutto il calendario"):
                save_calendar_data({}, url_google)
                st.rerun()

elif page == "📚 Formazione & Spiegazioni":
    st.title("🧠 Guida Pratica per lo Staff Tecnico")
    st.markdown("""
    Questa sezione è pensata per aiutare gli allenatori e lo staff a trasformare i numeri in **decisioni pratiche sul campo**. 
    L'obiettivo non è guardare calcoli accademici complessi, ma rispondere a due domande fondamentali per vincere le partite: *Le ragazze sono in forma? Rischiano di farsi male?*
    """)
    
    with st.expander("1. 📊 RPE e Carico Interno (sRPE): La voce dell'atleta"):
        st.markdown("""
        **RPE (Rating of Perceived Exertion - Scala 1-10)**
        È il voto che l'atleta dà alla difficoltà dell'allenamento. Perché è fondamentale? Perché **non misura solo lo sforzo fisico, ma lo stress globale**. Una ragazza che ha dormito poco o ha forte stress scolastico percepirà un allenamento normale come "pesantissimo".
        *   **1-3:** Molto leggero (Recupero, walk-through, sessioni di solo tiro)
        *   **4-6:** Moderato (Lavoro tattico a metà campo, 5v0)
        *   **7-8:** Duro (Lavoro ad alta intensità, 5v5, transizioni, difese pressanti)
        *   **9-10:** Massimale (Partita punto a punto o lavoro metabolico estremo)
        
        **sRPE (Session RPE = RPE x Minuti)**
        È il vero **Carico Interno**. Se fai un allenamento di 90 minuti valutato 6, il carico è 540. Questo numero dice allo staff esattamente *quanta benzina* è stata consumata in quella seduta.
        
       
        
    with st.expander("2. 📋 Carico Esterno: La pianificazione del Coach"):
        st.markdown("""
        Il **Carico Esterno** è quello che lo staff *decide* di fare a tavolino. In assenza di GPS o wearable, lo calcoliamo assegnando un'intensità arbitraria all'esercitazione.
        
        **Come assegnare il "Peso" (1-10) alle esercitazioni di Basket:**
        *   **1-3:** Riscaldamento statico, stretching, tiri liberi, 5v0 a metà campo (camminato/jogging).
        *   **4-6:** Esercizi di tecnica individuale, 3v3 a metà campo, situazioni tattiche 4v4 con difesa guidata.
        *   **7-8:** 5v5 a tutto campo, transizioni continue, sovrannumeri ad alta intensità (es. 11-man drill).
        *   **9-10:** Lavoro metabolico a secco (suicidi, navette) o situazioni di gioco massimali prolungate senza pause,1v1 a tutto campo etc..
        
        Moltiplicando questo Peso per i minuti dell'esercitazione, otteniamo le Unità Arbitrarie (AU) del carico esterno giornaliero.
        """)
        
    with st.expander("3. ⚖️ Matrice Efficienza: L'atleta sta assorbendo il lavoro?"):
        st.markdown("""
        L'incrocio tra **quello che hai pianificato tu (Esterno)** e **quello che ha sentito l'atleta (Interno)** ti dice tutto sul suo stato di forma attuale.
        
        *   🟢 **Ottimo Adattamento (Esterno ALTO / Interno BASSO):** Hai fatto un allenamento durissimo (es. peso 8), ma la giocatrice lo ha percepito facile (es. RPE 5). *Significato:* L'atleta vola, ha una fitness eccellente e assorbe bene i carichi.
        *   🟡 **In Linea (Esterno = Interno):** L'allenamento era progettato da 7 e l'hanno sentito da 7. *Significato:* Normale amministrazione.
        *   🔴 **Faticamento (Esterno BASSO / Interno ALTO):** Hai fatto scarico pre-partita (peso 3), ma l'atleta ti dà RPE 7. *Significato:* Campanello d'allarme! L'atleta è svuotata, ha accumulato fatica residua o sta covando un'influenza. Ha bisogno di riposo, farla spingere ora significa infortunio o crollo della prestazione in gara.
        """)

    with st.expander("4. 📈 ACWR (Gabbett) & EWMA: Prevenire gli infortuni"):
        st.markdown("""
        L'**Acute:Chronic Workload Ratio (ACWR)** è il gold standard mondiale per la prevenzione infortuni. Risponde a un grande principio dello sport moderno: *"Non è l'allenamento duro a rompere i giocatori, ma l'allenamento duro per cui non sono preparati"*.
        
        Mette in rapporto la fatica di breve periodo (**Acuto** - ultimi 7 gg) con la "corazza" fisica costruita nel lungo periodo (**Cronico** - ultimi 28 gg). Noi usiamo la formula **EWMA**, che è più precisa perché dà più importanza agli allenamenti di ieri rispetto a quelli di 3 settimane fa.
        
        **Come leggere il semaforo in Home Page:**
        *   🔵 **< 0.8 (Sottoallenamento):** L'atleta si sta allenando troppo poco. Rischia di farsi male al primo picco di intensità (es. una partita con alto minutaggio) perché non ha "corazza" (Cronico basso).
        *   🟢 **0.8 - 1.3 (Sweet Spot):** La zona d'oro. Il carico sale gradualmente. Massima fitness, minimo rischio infortuni.
        *   🟡 **1.3 - 1.5 (Zona di Attenzione):** Il picco di carico sta salendo un po' troppo in fretta. Da monitorare (potrebbe essere fisiologico in pre-season o dopo un infortunio).
        *   🔴 **> 1.5 (Danger Zone):** Il carico acuto ha superato di oltre il 50% la base cronica. **Il rischio di infortuni muscolari e articolari raddoppia.** Bisogna far riposare l'atleta o ridurre drasticamente i suoi minuti nel prossimo allenamento.
        """)
        
  
