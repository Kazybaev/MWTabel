param(
    [switch]$SeedDemo,
    [switch]$SkipMigrate
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

Write-Host ""
Write-Host "Local mode enabled:" -ForegroundColor Cyan
Write-Host "  DEBUG=True"
Write-Host "  DB_ENGINE=sqlite"
Write-Host "  ALLOWED_HOSTS=127.0.0.1,localhost,testserver"
Write-Host ""

if (-not $SkipMigrate) {
    python tabel_project\manage.py migrate
}

if ($SeedDemo) {
    python tabel_project\manage.py seed_demo
}

python tabel_project\manage.py runserver 127.0.0.1:8000
