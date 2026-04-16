@echo off
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
python -m footstats.weekly_report >> logs\weekly_report.log 2>&1
