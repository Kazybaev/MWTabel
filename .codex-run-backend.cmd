@echo off
cd /d C:\Users\user\MWTabel
set DEBUG=True
set ALLOWED_HOSTS=127.0.0.1,localhost,testserver
set CSRF_TRUSTED_ORIGINS=http://127.0.0.1:8000,http://localhost:8000
set DB_ENGINE=sqlite
set SECURE_SSL_REDIRECT=False
set USE_X_FORWARDED_HOST=False
"C:\Users\user\AppData\Local\Programs\Python\Python312\python.exe" tabel_project\manage.py runserver 127.0.0.1:8000 > backend-runserver.log 2> backend-runserver.err.log
