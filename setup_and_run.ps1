# Install dependencies then run the Django server.
# Run this in PowerShell: .\setup_and_run.ps1

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$py = "$PSScriptRoot\venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    Write-Host "Virtual environment not found. Create it first: python -m venv venv"
    exit 1
}

Write-Host "Installing dependencies (this may take a few minutes)..." -ForegroundColor Cyan
& $py -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "`nStarting Django server..." -ForegroundColor Green
& $py manage.py runserver
