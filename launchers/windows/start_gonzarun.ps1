$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$venv = Join-Path $root ".venv"
$python = Join-Path $venv "Scripts\python.exe"
$port = 8501

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Add-Type -AssemblyName PresentationFramework
    [System.Windows.MessageBox]::Show("Gonzarun necesita Python 3.12 o superior. Instálalo desde python.org y vuelve a abrir la app.", "Gonzarun") | Out-Null
    exit 1
}

if (-not (Test-Path $python)) {
    python -m venv $venv
    & $python -m pip install --upgrade pip *> "$env:TEMP\gonzarun-install.log"
    & $python -m pip install -r (Join-Path $root "requirements.txt") *> "$env:TEMP\gonzarun-install.log"
}

Start-Process -FilePath $python -WorkingDirectory $root -ArgumentList "-m streamlit run app.py --server.headless true --server.port $port" -WindowStyle Hidden
for ($i = 0; $i -lt 30; $i++) {
    try {
        Invoke-WebRequest "http://127.0.0.1:$port/_stcore/health" -UseBasicParsing -TimeoutSec 1 | Out-Null
        Start-Process "http://127.0.0.1:$port"
        exit 0
    } catch {
        Start-Sleep -Seconds 1
    }
}

Add-Type -AssemblyName PresentationFramework
[System.Windows.MessageBox]::Show("Gonzarun no ha podido iniciar. Revisa los logs temporales de instalación.", "Gonzarun") | Out-Null
