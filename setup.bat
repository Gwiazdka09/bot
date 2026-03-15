@echo off
chcp 65001 >nul
echo.
echo ════════════════════════════════════════════════════
echo   FootStats AI Setup - instalacja bibliotek
echo ════════════════════════════════════════════════════
echo.

echo [1/4] Sprawdzam Python...
python --version
if errorlevel 1 (
    echo BLAD: Python nie jest zainstalowany lub nie jest w PATH.
    echo Pobierz z: https://www.python.org/downloads/
    echo WAZNE: Zaznacz "Add Python to PATH" podczas instalacji!
    pause
    exit /b 1
)

echo.
echo [2/4] Instaluję biblioteki Python...
pip install playwright groq python-dotenv requests rich pandas numpy scipy reportlab openpyxl
if errorlevel 1 (
    echo BLAD podczas instalacji bibliotek.
    pause
    exit /b 1
)

echo.
echo [3/4] Instaluję przeglądarkę Chromium dla Playwright...
playwright install chromium
if errorlevel 1 (
    echo BLAD podczas instalacji Chromium.
    pause
    exit /b 1
)

echo.
echo [4/4] Sprawdzam Ollama...
ollama --version
if errorlevel 1 (
    echo.
    echo INFO: Ollama nie jest zainstalowana.
    echo Pobierz z: https://ollama.com/download/windows
    echo Po instalacji uruchom ten skrypt ponownie lub wpisz:
    echo   ollama pull gemma2:2b
    echo.
) else (
    echo Ollama znaleziona. Pobieram model gemma2:2b...
    ollama pull gemma2:2b
)

echo.
echo ════════════════════════════════════════════════════
echo   GOTOWE! Pamiętaj o dodaniu klucza Groq do .env:
echo   GROQ_API_KEY=gsk_TWOJ_NOWY_KLUCZ
echo ════════════════════════════════════════════════════
echo.
echo Następne kroki:
echo   1. Wejdź na console.groq.com - wygeneruj nowy klucz
echo   2. Otwórz plik .env w Notatniku
echo   3. Dodaj linię: GROQ_API_KEY=gsk_twoj_klucz
echo   4. Uruchom: python ai_client.py  (test)
echo   5. Uruchom: python ai_analyzer.py  (analiza meczu)
echo.
pause
