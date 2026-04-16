@echo off
:: FootStats Final Agent – uruchamia się co 30 min przez Task Scheduler.
:: Czyta data\next_final.txt (format HH:MM) i odpala agenta jeśli jesteśmy
:: w oknie [-35, +5] minut od zaplanowanej godziny finału.

:: VBScript self-hide: relaunch without visible console window
if "%~1"=="-silent" goto :main
set "_VBS=%TEMP%\fs_hide_%~n0.vbs"
> "%_VBS%" echo Set o=CreateObject("WScript.Shell")
>> "%_VBS%" echo o.Run "cmd /c ""%~f0"" -silent", 0, False
wscript //nologo "%_VBS%"
del "%_VBS%" 2>nul
exit /b 0

:main
cd /d F:\bot
call venv\Scripts\activate.bat 2>nul || call .venv\Scripts\activate.bat 2>nul

set "NEXT_FINAL_FILE=data\next_final.txt"
if not exist "%NEXT_FINAL_FILE%" exit /b 0

:: Sprawdź okno czasowe przez PowerShell
powershell -NoProfile -Command ^
  "$target = (Get-Content '%NEXT_FINAL_FILE%').Trim(); " ^
  "if ($target -notmatch '^\d{2}:\d{2}$') { exit 1 }; " ^
  "$now = Get-Date; " ^
  "$t = [DateTime]::ParseExact($target, 'HH:mm', $null); " ^
  "$t = $t.Date.AddHours($t.Hour).AddMinutes($t.Minute); " ^
  "$diff = ($t - $now).TotalMinutes; " ^
  "if ($diff -ge -35 -and $diff -le 5) { exit 0 } else { exit 2 }"

if errorlevel 2 exit /b 0
if errorlevel 1 exit /b 1

python -m footstats.daily_agent --faza final >> logs\final_agent.log 2>&1
