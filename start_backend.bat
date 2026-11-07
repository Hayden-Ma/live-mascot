@echo off
cd /d %~dp0
set PYTHONUNBUFFERED=1
set PYTHONIOENCODING=utf-8
".venv\Scripts\python.exe" -m uvicorn backend.main:app --host 0.0.0.0 --port 12121 --env-file .env
