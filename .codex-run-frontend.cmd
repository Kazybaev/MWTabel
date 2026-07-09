@echo off
cd /d C:\Users\user\MWTabel\frontend
set VITE_API_PROXY=http://127.0.0.1:8000
npm run dev -- --host 127.0.0.1 --port 5173 > ..\frontend-vite.log 2> ..\frontend-vite.err.log
