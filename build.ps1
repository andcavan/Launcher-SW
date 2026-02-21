param(
    [switch]$SkipDeps,
    [switch]$OneFile
)

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    throw "Python non trovato nel PATH. Installa Python 3.11+ o usa un venv attivo."
}

if (-not $SkipDeps) {
    python -m pip install --upgrade pip
    python -m pip install -r requirements.txt pyinstaller
}

$pyinstallerArgs = @(
    "--noconfirm"
    "--clean"
    "--windowed"
    "--name", "LauncherSW"
    "--add-data", "style;style"
    "--add-data", "VERSION;."
)

if (Test-Path "settings.json") {
    $pyinstallerArgs += @("--add-data", "settings.json;.")
}

if ($OneFile) {
    $pyinstallerArgs += "--onefile"
} else {
    $pyinstallerArgs += "--onedir"
}

$pyinstallerArgs += "main.py"

python -m PyInstaller @pyinstallerArgs

if ($OneFile) {
    Write-Host "Build completata: dist\\LauncherSW.exe"
    Write-Host "Nota: in modalita onefile, settings/versione interne sono pacchettizzate."
} else {
    Write-Host "Build completata: dist\\LauncherSW\\LauncherSW.exe"
}
