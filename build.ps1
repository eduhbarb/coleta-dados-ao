$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "Criando ambiente virtual (.venv)..."
    python -m venv .venv
}

$Py = Join-Path $Root ".venv\Scripts\python.exe"
$Pip = Join-Path $Root ".venv\Scripts\pip.exe"
$PyInstaller = Join-Path $Root ".venv\Scripts\pyinstaller.exe"

Write-Host "Instalando dependências..."
& $Pip install --upgrade pip
& $Pip install -r requirements.txt

Write-Host "Executando testes unitários..."
& $Py -m unittest discover -s tests -v

Write-Host "Gerando coleta-dados-ao.exe..."
& $PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --windowed `
    --name "coleta-dados-ao" `
    --add-data "ui;ui" `
    --paths "src" `
    src/main.py

Write-Host "Concluído! Executável disponível em: dist\coleta-dados-ao.exe"
