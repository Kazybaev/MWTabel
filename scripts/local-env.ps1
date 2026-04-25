$env:DEBUG = "True"
$env:ALLOWED_HOSTS = "127.0.0.1,localhost,testserver"
$env:CSRF_TRUSTED_ORIGINS = "http://127.0.0.1:8000,http://localhost:8000"
$env:DB_ENGINE = "sqlite"
$env:SECURE_SSL_REDIRECT = "False"
$env:USE_X_FORWARDED_HOST = "False"

Write-Host "Local environment variables loaded for Tabel." -ForegroundColor Green
