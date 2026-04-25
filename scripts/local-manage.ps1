param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$ManageArgs
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot

$env:DEBUG = "True"
$env:ALLOWED_HOSTS = "127.0.0.1,localhost,testserver"
$env:CSRF_TRUSTED_ORIGINS = "http://127.0.0.1:8000,http://localhost:8000"
$env:DB_ENGINE = "sqlite"
$env:SECURE_SSL_REDIRECT = "False"
$env:USE_X_FORWARDED_HOST = "False"

if (-not $ManageArgs -or $ManageArgs.Count -eq 0) {
    Write-Host "Usage: powershell -File .\scripts\local-manage.ps1 <manage.py args>" -ForegroundColor Yellow
    exit 1
}

python tabel_project\manage.py @ManageArgs
