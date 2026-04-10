@echo off
cd /d F:\bot
call venv\Scripts\activate.bat 2>nul || call .venv\Scripts\activate.bat 2>nul
python -m footstats.weekly_report >> logs\weekly_report.log 2>&1
