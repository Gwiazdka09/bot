@echo off
cd /d F:\bot
call .venv\Scripts\activate.bat
start "" /B python -m uvicorn footstats.api.main:app --port 8000 >> logs\scheduler_dashboard.log 2>&1
