$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location (Join-Path $projectRoot "frontend")

if (-not $env:VITE_API_PROXY) {
    $env:VITE_API_PROXY = "http://127.0.0.1:8000"
}

Write-Host ""
Write-Host "Frontend local mode enabled:" -ForegroundColor Cyan
Write-Host "  VITE_API_PROXY=$env:VITE_API_PROXY"
Write-Host ""

npm run dev -- --host 127.0.0.1
