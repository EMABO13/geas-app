@echo off
echo =======================================================
echo          AVVIO DASHBOARD GEAS BASKET
echo =======================================================
echo Installazione/Aggiornamento delle dipendenze in corso...
python -m pip install -r requirements.txt
echo.
echo Avvio in corso. Si aprira' il browser tra pochi secondi...
python -m streamlit run app.py
pause
