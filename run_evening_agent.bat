@echo off
cd /d F:\bot
call venv\Scripts\activate.bat 2>nul || call .venv\Scripts\activate.bat 2>nul
python -m footstats.evening_agent >> logs\evening_agent.log 2>&1
