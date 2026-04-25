@echo off
setlocal enabledelayedexpansion

cd /d F:\bot
python -m footstats.daily_agent --stawka 10 --dni 3 >> F:\bot\data\logs\daily_agent.log 2>&1
