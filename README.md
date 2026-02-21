# Launcher SolidWorks

App desktop Python per:
- caricare un file di configurazione `.sldreg` nel registro Windows
- avviare `SLDWORKS.exe` subito dopo il caricamento
- salvare setup rapidi con: nome setup, file `.sldreg`, versione SW, percorso `SLDWORKS.exe`
- avvio rapido da pagina con pulsanti dedicati ai setup salvati
- riordino pulsanti setup con drag&drop in `Avvio Rapido`
- pulsanti setup compatti per mostrare piu setup a schermo
- scelta stile wizard SolidWorks di cosa ripristinare:
  - Opzioni sistema
  - Layout toolbar (`Tutte` oppure `Solo macro`)
  - Tasti rapidi
  - Gesti mouse
  - Personalizzazioni menu
  - Viste salvate
- opzione per pulire le chiavi selezionate prima dell'import (evita residui da configurazioni precedenti)

UI basata su `MyStyle01`.

## Versione

`0.8.6`

## Avvio

```bash
pip install -r requirements.txt
python main.py
```

## Generare distribuzione `.exe`

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

## Note operative

- Funziona solo su Windows.
- Il comando `reg import` puo richiedere privilegi adeguati in base alle chiavi presenti nel file `.sldreg`.
- I setup sono salvati in `LAUNCHER-SW/settings.json`.
- UI organizzata in 2 tab: `Avvio Rapido` e `Gestione Setup`.
- Il log e visibile solo nella tab `Gestione Setup` (non in `Avvio Rapido`).
- Le opzioni selezionate vengono importate filtrando il file `.sldreg` per categorie compatibili con il wizard SolidWorks.
- Se attivo, il flag "Pulisci chiavi selezionate prima dell'import" elimina prima le chiavi pertinenti e poi applica il nuovo `.sldreg`.
- Compatibilita migliorata lettura `.sldreg` `REGEDIT4` (ANSI/UTF-8) e `Version 5.00` (UTF-16 BOM).
- Riordino setup con drag&drop stabilizzato (tracciamento target via posizione cursore).
- Le chiavi `Recent*` e `Pinned File List` vengono preservate durante l'import per non bloccare l'aggiornamento dei documenti recenti.
- La pulizia evita delete "padre" che cancellerebbero categorie non selezionate.
- Il messaggio di conferma a fine import/avvio e temporaneo e si chiude automaticamente dopo 5 secondi.
- Prima dell'avvio, se `SLDWORKS.exe` e gia aperto, il launcher chiede conferma: con `No` si ferma, con `Si` chiude le sessioni aperte e poi procede con import + nuovo avvio.
