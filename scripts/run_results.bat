@echo off
cd /d F:\bot
call .venv\Scripts\activate.bat
python -m footstats.scrapers.results_updater >> logs\scheduler_results.log 2>&1
