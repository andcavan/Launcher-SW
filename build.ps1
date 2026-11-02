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

# Copia la cartella CFG accanto all'exe
if ($OneFile) {
    if (Test-Path "dist\CFG") { Remove-Item -Recurse -Force "dist\CFG" }
    Copy-Item -Recurse -Force "CFG" "dist\CFG"
    Write-Host "Build completata: dist\\LauncherSW.exe"
    Write-Host "Cartella CFG copiata in: dist\\CFG"
} else {
    if (Test-Path "dist\LauncherSW\CFG") { Remove-Item -Recurse -Force "dist\LauncherSW\CFG" }
    Copy-Item -Recurse -Force "CFG" "dist\LauncherSW\CFG"
    Write-Host "Build completata: dist\\LauncherSW\\LauncherSW.exe"
    Write-Host "Cartella CFG copiata in: dist\\LauncherSW\\CFG"
}
