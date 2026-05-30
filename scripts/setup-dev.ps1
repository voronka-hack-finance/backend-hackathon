# Creates a local venv with Python 3.12 (matches Docker).
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$py = Get-Command py -ErrorAction SilentlyContinue
if (-not $py) {
    Write-Error "Python launcher 'py' not found. Install Python 3.12 from https://www.python.org/downloads/"
}

& py -3.12 -c "import sys; assert sys.version_info >= (3, 12), sys.version"
if ($LASTEXITCODE -ne 0) {
    Write-Error "Python 3.12 is not installed. Run: py install 3.12"
}

if (-not (Test-Path ".venv")) {
    & py -3.12 -m venv .venv
}

& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\pip.exe install -e ".[dev]"

Write-Host ""
Write-Host "Done. Activate and run tests:"
Write-Host "  .\.venv\Scripts\Activate.ps1"
Write-Host "  pytest"
