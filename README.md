# FootStats v3.1 — Interaktywny Kreator

Narzędzie do analizy piłkarskiej i predykcji wyników. Łączy model Poissona, ML (Bzzoiro CatBoost), 3 źródła danych API oraz AI (Groq llama-3.3-70b) w jedno CLI z live dashboardem i interaktywnym kreatorem kuponów.

## Funkcje

- **Live Dashboard** – FastAPI + HTML/JS na porcie 8000 (`/preview`) — bankroll, ROI, historia kuponów, ustawienia Kelly
- **Kreator Kuponu** – 5-krokowy interaktywny wizard: mecze Bzzoiro → analiza AI → wybór typów → Kelly calc → zapis
- **Kalibracja Kelly v2** – hit-rate z ostatnich 10 kuponów + forma bota (3x seria WIN/LOSE)
- **Pętla Feedbacku AI** – po każdej porażce Groq generuje wniosek → wstrzykiwany do kolejnego promptu
- **Zamykanie kuponów** – automatyczne ACTIVE→WIN/LOSE na podstawie API-Football + aktualizacja bankrolla
- **Predykcja meczów** – model Poissona + ML cross-walidacja z Bzzoiro
- **Pewniaczki 48h** – skanowanie wszystkich lig Bzzoiro, Scout Bot EV, analiza AI
- **AI Analiza** – Groq 70B analizuje typy, buduje kupony AKO, ocenia Twój kupon
- **Form Scraper** – SofaScore (primary) + FlashScore (fallback), forma + kontuzje
- **Eksport PDF** – raporty z czcionką DejaVu (polskie znaki)
- **Backtest DB** – SQLite, śledzenie skuteczności typów

## Wymagania

- Python 3.10+
- Klucze API: `FOOTBALL_DATA_KEY`, `APISPORTS_KEY`, `BZZOIRO_KEY`, `GROQ_API_KEY`

## Instalacja

```bash
git clone https://github.com/yourusername/FootStats.git
cd FootStats

# Środowisko wirtualne (zalecane)
python -m venv venv
venv\Scripts\activate      # Windows
# source venv/bin/activate  # Linux/Mac

# Instalacja pakietu (tryb edytowalny)
pip install -e .[dev]

# Playwright (dla scraperów STS/SofaScore/FlashScore)
playwright install chromium
```

## Konfiguracja

Skopiuj szablon i uzupełnij klucze API:

```bash
copy env_wzor.txt .env   # Windows
# cp env_wzor.txt .env   # Linux/Mac
```

Plik `env_wzor.txt` zawiera wszystkie wymagane zmienne z opisem. Plik `.env` jest w `.gitignore` i nie trafia do repozytorium.

```plaintext
FOOTBALL_DATA_KEY=twoj_klucz_football_data_org
APISPORTS_KEY=twoj_klucz_api_sports_io
BZZOIRO_KEY=twoj_klucz_bzzoiro
GROQ_API_KEY=twoj_klucz_groq
```

## Live Dashboard

Uruchom serwer API:
```bash
python -m uvicorn footstats.api.main:app --port 8000
```
Otwórz: `http://localhost:8000` → przekieruje do `/preview`

Zakładki: **Dashboard** (bankroll + ROI) | **Historia** | **Ustawienia** | **Stwórz Kupon**

## Automatyczne uruchamianie (Windows Task Scheduler)

Instrukcja w `docs/scheduler_setup.md`. Skrypty w `scripts/`:

| Plik | Czas | Opis |
|------|------|------|
| `scripts/run_dashboard.bat` | Przy starcie systemu | Serwer API na porcie 8000 |
| `scripts/run_agent.bat` | 08:00 + 16:00 | Codzienna analiza + kupon |
| `scripts/run_results.bat` | 23:30 | Aktualizacja wyników i zamknięcie kuponów |

Uruchamiane przez `scripts/silent_run.vbs` — bez okna konsoli (`wscript.exe`).

## Uruchomienie

```bash
python -m footstats
```

## Struktura projektu

```
FootStats/
├── src/footstats/
│   ├── cli.py                  # Główna pętla CLI
│   ├── config.py               # Konfiguracja, klucze ENV
│   ├── data_fetcher.py         # Pobieranie danych z API
│   ├── ai/
│   │   ├── client.py           # Groq → Ollama fallback
│   │   └── analyzer.py         # Analiza meczów + kupony AI
│   ├── core/
│   │   ├── poisson.py          # Model Poissona
│   │   ├── quick_picks.py      # Szybkie Pewniaczki 48h + Scout Bot
│   │   ├── weekly_picks.py     # Pewniaczki Tygodnia (multi-liga)
│   │   ├── backtest.py         # SQLite DB – śledzenie typów
│   │   └── ...                 # forma, H2H, wartość zakładu itp.
│   ├── scrapers/
│   │   ├── bzzoiro.py          # Bzzoiro ML CatBoost
│   │   ├── sts.py              # STS Strefa Inspiracji (Playwright)
│   │   ├── superoferta.py      # STS SuperOferta boosted odds
│   │   ├── form_scraper.py     # SofaScore + FlashScore forma
│   │   └── ...
│   └── export/
│       ├── pdf.py              # Eksport PDF (ReportLab)
│       └── pdf_font.py         # Czcionka DejaVu
├── data/                       # SQLite DB (gitignored)
├── cache/                      # Cache scraperów (gitignored)
├── tests/                      # Testy pytest (59 testów)
└── .env                        # Klucze API (gitignored)
```

## Opcje menu

| Opcja | Opis |
|-------|------|
| **P** | Szybkie Pewniaczki 48h (Bzzoiro ML + AI Groq) |
| **1** | Analiza kolejki meczów |
| **2** | Predykcja wybranego meczu |
| **3** | Tabela ligi |
| **4** | Wyniki historyczne |
| **5** | Statystyki Dom/Wyjazd |
| **6** | Analiza H2H |
| **7** | Value bets |
| **8** | Pełne Pewniaczki Tygodnia (Poisson + ML) |
| **9** | Analiza drużyny |
| **I** | AI analiza meczu (Groq 70B) |
| **K** | Konfiguracja kluczy API |

## Testy

```bash
pytest tests/ -v
```

## Licencja

MIT License
