@echo off
setlocal enabledelayedexpansion

cd /d F:\bot

REM KROK 1 (08:00): Draft phase + wait for final phase
REM Script automatically:
REM   1. Runs --faza draft
REM   2. Reads next_final.txt
REM   3. Waits until scheduled time
REM   4. Runs --faza final
REM   5. Cleans up next_final.txt

python -m footstats.daily_agent_scheduler --stawka 10 --dni 3 --mode draft-wait-final >> F:\bot\data\logs\daily_agent.log 2>&1

echo [%date% %time%] Daily agent cycle completed >> F:\bot\data\logs\daily_agent.log
