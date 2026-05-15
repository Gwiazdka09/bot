@echo off
setlocal enabledelayedexpansion

cd /d F:\bot

REM KROK 0: Backup bazy danych przed pipeline
echo [%date% %time%] === Backup DB START === >> F:\bot\data\logs\daily_agent.log
python scripts/backup_db.py >> F:\bot\data\logs\daily_agent.log 2>&1
if %errorlevel% neq 0 (
    echo [%date% %time%] BLAD: Backup nieudany - przerywam pipeline >> F:\bot\data\logs\daily_agent.log
    exit /b 1
)
echo [%date% %time%] Backup OK >> F:\bot\data\logs\daily_agent.log

REM KROK 1 (08:00): Draft phase + wait for final phase
REM Script automatically:
REM   1. Runs --faza draft
REM   2. Reads next_final.txt
REM   3. Waits until scheduled time
REM   4. Runs --faza final
REM   5. Cleans up next_final.txt

python -m footstats.daily_agent_scheduler --stawka 10 --dni 3 --mode draft-wait-final >> F:\bot\data\logs\daily_agent.log 2>&1
if %errorlevel% neq 0 (
    echo [%date% %time%] BLAD: daily_agent_scheduler zakonczyl sie z bledem >> F:\bot\data\logs\daily_agent.log
    exit /b 1
)

echo [%date% %time%] Daily agent cycle completed >> F:\bot\data\logs\daily_agent.log
