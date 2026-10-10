# Crea "MDGB Centrale.exe" (Windows) in app\desktop\dist\, piu' lo zip per il centralino. ~3 minuti.
# Da PowerShell, nella cartella del repo:
#   powershell -ExecutionPolicy Bypass -File app\desktop\build_windows.ps1
# Serve: Python 3.12 (python.org o "winget install Python.Python.3.12") e Mosquitto per Windows installato in
# C:\Program Files\mosquitto (installer ufficiale: https://mosquitto.org/download/): l'exe lo include,
# quindi il centralino non deve installare nulla. Senza un PC Windows: la build automatica su GitHub
# (.github/workflows/centrale-windows.yml) fa la stessa cosa.
$ErrorActionPreference = "Stop"
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$Build = Join-Path $Here "build"
$Dist = Join-Path $Here "dist"
$Venv = Join-Path $Build "venv"
New-Item -ItemType Directory -Force $Build | Out-Null

Write-Host "0/4 Mosquitto"
$MosqDir = if ($env:MOSQUITTO_DIR) { $env:MOSQUITTO_DIR } else { "C:\Program Files\mosquitto" }
if (-not (Test-Path (Join-Path $MosqDir "mosquitto.exe"))) {
  throw "Mosquitto non trovato in ${MosqDir}: installalo da https://mosquitto.org/download/ (installer per Windows x64)"
}

Write-Host "1/4 ambiente di build (app\desktop\build\venv)"
$Py = Join-Path $Venv "Scripts\python.exe"
if (-not (Test-Path $Py)) {
  if ($env:BUILD_PYTHON) { & $env:BUILD_PYTHON -m venv $Venv }
  elseif (Get-Command py -ErrorAction SilentlyContinue) { & py -3.12 -m venv $Venv }
  else { & python -m venv $Venv }
}
& $Py -m pip install -q --upgrade pip
& $Py -m pip install -q -r (Join-Path $Here "requirements.txt")
if ($LASTEXITCODE -ne 0) { throw "pip install fallito" }

Write-Host "2/4 icona"
& $Py (Join-Path $Here "make_icon.py") --ico (Join-Path $Build "icon.ico")

Write-Host "3/4 app"
& (Join-Path $Venv "Scripts\pyinstaller.exe") --noconfirm --clean --log-level ERROR `
  --distpath $Dist --workpath (Join-Path $Build "pyinstaller") (Join-Path $Here "centrale.spec")
if ($LASTEXITCODE -ne 0) { throw "PyInstaller fallito" }

Write-Host "4/4 autotest e pacchetto"
$Exe = Join-Path $Dist "MDGB Centrale.exe"
$p = Start-Process -FilePath $Exe -ArgumentList "--selftest" -Wait -PassThru
if ($p.ExitCode -ne 0) { throw "Autotest fallito (codice $($p.ExitCode)): log in $env:TEMP\mdgb-selftest-*\centrale.log" }
Compress-Archive -Force -Path $Exe -DestinationPath (Join-Path $Dist "MDGB-Centrale-windows.zip")
Write-Host ""
Write-Host "Pronta: $Exe"
Write-Host "Per il centralino: $Dist\MDGB-Centrale-windows.zip (solo l'app, Mosquitto incluso)"
