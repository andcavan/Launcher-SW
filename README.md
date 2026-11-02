# Launcher SolidWorks

App desktop Python per:
- caricare un file di configurazione `.sldreg` nel registro Windows
- avviare `SLDWORKS.exe` subito dopo il caricamento
- salvare setup rapidi con: nome setup, file `.sldreg`, versione SW, percorso `SLDWORKS.exe`
- avvio rapido da pagina con pulsanti dedicati ai setup salvati
- pulsanti setup con nome e versione SolidWorks su due righe
- riordino setup con le frecce `▲` / `▼` accanto a `Setup salvato` in `Gestione Setup`
- colore personalizzabile per ogni pulsante di avvio (`Gestione Setup` -> `Colore pulsante avvio`, con 8 colori rapidi)
- scelta stile wizard SolidWorks di cosa ripristinare:
  - Opzioni sistema
  - Layout toolbar (`Tutte` oppure `Solo macro`)
  - Tasti rapidi
  - Gesti mouse
  - Personalizzazioni menu
  - Viste salvate
- opzione per pulire le chiavi selezionate prima dell'import (evita residui da configurazioni precedenti)

UI basata su `PyQt6`.

## Versione

`0.9.17`

## Avvio

```bash
pip install -r requirements.txt
python main.py
```

## Generare distribuzione `.exe`

### Build automatica (GitHub Actions)

Ad ogni push che modifica `main.py`, `VERSION`, `requirements.txt`, `build.ps1` o `CFG/`
il workflow `.github/workflows/build-windows.yml` genera la build su Windows.
Si puo avviare anche a mano da GitHub: `Actions` -> `Build Windows` -> `Run workflow`.

Lo zip `LauncherSW-<versione>-win64` si scarica dalla pagina della run, sezione `Artifacts`
(conservato 90 giorni). Contiene la cartella `LauncherSW` pronta da copiare.

### Build locale

1. Apri PowerShell nella cartella del progetto:
```powershell
cd "C:\Users\prog3\Desktop\APP MECCANICA\LAUNCHER-SW"
```
2. Se PowerShell blocca gli script, abilita solo per la sessione corrente:
```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
```
3. Genera la build consigliata (cartella distribuibile):
```powershell
.\build.ps1
```

Output consigliato:
- `dist\LauncherSW\LauncherSW.exe` (modalita `onedir`)

Per distribuire l'app su un altro PC:
- copia **tutta** la cartella `dist\LauncherSW` (non solo il file `.exe`)

Opzione alternativa (singolo file):
```powershell
.\build.ps1 -OneFile
```

Output:
- `dist\LauncherSW.exe`

## Risoluzione errori comuni build

- Errore `running scripts is disabled`:
```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
```
- Errore `No module named PyInstaller`:
```powershell
python -m pip install -r requirements.txt pyinstaller
```
- `build.ps1` bloccato da file scaricato:
```powershell
Unblock-File .\build.ps1
```
- Windows SmartScreen/antivirus blocca l'avvio dell'exe:
  - usa `dist\LauncherSW\LauncherSW.exe` (build `onedir`)
  - se compare l'avviso SmartScreen: `Altre info` -> `Esegui comunque`
  - in ambiente aziendale puo servire firma digitale dell'eseguibile
- Errore permessi durante `reg import` nel programma:
  - avvia l'app come amministratore se il `.sldreg` scrive in chiavi protette
- Percorsi troppo lunghi o con caratteri speciali:
  - mantieni il progetto in un path breve, ad esempio `C:\SW\LAUNCHER-SW`

## Aggiornamento App

Durante l'aggiornamento dell'applicazione:
1. **NON sovrascrivere** la cartella `CFG/` che contiene le tue configurazioni
2. Sostituisci tutti gli altri file nella cartella principale
3. Le tue impostazioni e setup salvati in `CFG/settings.json` verranno preservati

## Note operative

- Funziona solo su Windows.
- Il comando `reg import` puo richiedere privilegi adeguati in base alle chiavi presenti nel file `.sldreg`.
- I setup sono salvati in `CFG/settings.json` (la cartella CFG non va mai eliminata durante aggiornamenti).
- UI organizzata in 2 tab: `Avvio Rapido` e `Gestione Setup`.
- Ogni tab ha la sua dimensione finestra (default 400x540 e 620x700): cambiando tab la finestra si adatta; le dimensioni scelte vengono ricordate in `CFG/settings.json`.
- Il log e visibile solo nella tab `Gestione Setup` (non in `Avvio Rapido`).
- Le opzioni selezionate vengono importate filtrando il file `.sldreg` per categorie compatibili con il wizard SolidWorks.
- Se attivo, il flag "Pulisci chiavi selezionate prima dell'import" elimina prima le chiavi pertinenti e poi applica il nuovo `.sldreg`.
- Compatibilita migliorata lettura `.sldreg` `REGEDIT4` (ANSI/UTF-8) e `Version 5.00` (UTF-16 BOM).
- Le chiavi `Recent*` e `Pinned File List` vengono preservate durante l'import per non bloccare l'aggiornamento dei documenti recenti.
- La pulizia evita delete "padre" che cancellerebbero categorie non selezionate.
- Il messaggio di conferma a fine import/avvio e temporaneo e si chiude automaticamente dopo 5 secondi.
- Prima dell'avvio, se `SLDWORKS.exe` e gia aperto, il launcher chiede conferma: con `No` si ferma, con `Si` chiude le sessioni aperte e poi procede con import + nuovo avvio.
