@echo off
:: cichy_bot.bat - Headless FootStats Update
:: Uruchamia aktualizację wyników i rozliczanie kuponów bez okna konsoli.

cd /d "F:\bot"

:: Ustawienie PYTHONPATH, aby Python widział moduły w folderze src
set PYTHONPATH=F:\bot\src

:: 1. Aktualizacja wyników (API-Football)
".venv\Scripts\pythonw.exe" -m footstats.scrapers.results_updater --dni 2

:: Czekaj 15 sekund na zwolnienie limitów/zapis bazy
timeout /t 15 /nobreak > nul

:: 2. Rozliczanie kuponów i aktualizacja bankrolla
".venv\Scripts\pythonw.exe" -m scripts.settle_coupons

exit
