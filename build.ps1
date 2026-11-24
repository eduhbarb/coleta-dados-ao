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
& $Py -m pip install --upgrade pip --quiet
& $Pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw "Falha ao instalar dependências." }

Write-Host "Executando testes unitários..."
& $Py -m unittest discover -s tests -v
if ($LASTEXITCODE -ne 0) { throw "Testes unitários falharam." }

Write-Host "Gerando coleta-dados-ao.exe..."
$PyInstallerArgs = @(
    "--noconfirm",
    "--clean",
    "--onefile",
    "--windowed",
    "--name", "coleta-dados-ao",
    "--icon", "assets/app.ico",
    "--add-data", "ui;ui",
    "--add-data", "assets/app.ico;assets",
    "--paths", "src"
)
$PyInstallerArgs += "src/main.py"
& $PyInstaller @PyInstallerArgs
if ($LASTEXITCODE -ne 0) { throw "Falha ao gerar o executável." }

Write-Host "Concluído! Executável disponível em: dist\coleta-dados-ao.exe"
