@echo off
cd /d F:\bot
call .venv\Scripts\activate.bat
python -m footstats.daily_agent --faza final >> logs\scheduler_agent.log 2>&1
