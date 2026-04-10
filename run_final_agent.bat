@echo off
:: FootStats Final Agent – uruchamia się co 30 min przez Task Scheduler.
:: Czyta data\next_final.txt (format HH:MM) i odpala agenta jeśli jesteśmy
:: w oknie [-35, +5] minut od zaplanowanej godziny finału.

cd /d F:\bot
call venv\Scripts\activate.bat 2>nul || call .venv\Scripts\activate.bat 2>nul

:: Odczytaj docelową godzinę
set "NEXT_FINAL_FILE=data\next_final.txt"
if not exist "%NEXT_FINAL_FILE%" (
    echo [FootStats Final] Brak pliku %NEXT_FINAL_FILE% – pomijam.
    exit /b 0
)

:: Użyj PowerShell do sprawdzenia okna czasowego
powershell -NoProfile -Command ^
  "$target = (Get-Content '%NEXT_FINAL_FILE%').Trim(); " ^
  "if ($target -notmatch '^\d{2}:\d{2}$') { exit 1 }; " ^
  "$now = Get-Date; " ^
  "$t = [DateTime]::ParseExact($target, 'HH:mm', $null); " ^
  "$t = $t.Date.AddHours($t.Hour).AddMinutes($t.Minute); " ^
  "$diff = ($t - $now).TotalMinutes; " ^
  "if ($diff -ge -35 -and $diff -le 5) { exit 0 } else { exit 2 }"

if errorlevel 2 (
    :: Poza oknem czasowym – cicho wyjdź
    exit /b 0
)
if errorlevel 1 (
    echo [FootStats Final] Nieprawidłowy format next_final.txt
    exit /b 1
)

echo [FootStats Final] Okno czasowe aktywne – uruchamiam agenta finalnego...
python -m footstats.daily_agent --faza final >> logs\final_agent.log 2>&1
echo [FootStats Final] Zakończono.
