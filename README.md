# FootStats v3.2 — Ultra-Skeptical AI + Autonomous Scheduler

Automatyczne narzędzie do analizy piłkarskiej i predykcji wyników. Łączy model Poissona, ML (Bzzoiro CatBoost), sędziów (zawodtyper.pl), dane API oraz ultra-skeptical AI (Groq llama-3.1-8b) w autonomiczny system z auto-kuponomm, schedulingiem i dashboardem live.

## Funkcje v3.2

**Autonomiczne Działanie:**
- **Daily Agent** – Auto-run draft fase (08:00) + final faza (70min przed pierwszym meczem)
- **Auto Settlement** – KROK 0: aktualizacja wyników, KROK 0b: feedback AI
- **Scheduler** – Windows Task Scheduler (run_daily.bat) + daily_agent_scheduler.py (draft→final flow)

**AI & Analiza:**
- **Ultra-Skeptical Analyzer** – Groq szuka powodów do PRZEGRANEJ, nie wygranej. Confidence 0-100, mandatory "ryzyko" field
- **Pętla Feedbacku AI** – co porażka → Groq wygeneruje lesson → injected do promptu next day
- **Sędziowie** – zawodtyper.pl stats (avg_yellow, avg_red, n_matches) wpływają na confidence AI
- **Kalibracja Kelly v2** – hit-rate (70/100/110%) + forma bota (3x seria WIN/LOSE)

**Dashboard & API:**
- **Live Dashboard** – FastAPI 12 endpoints, porto 8000 (`/preview`)
- **Statystyki kuponów** – GET `/api/stats/coupon-summary` (ROI %, type breakdown, streak tracking)
- **Bankroll tracking** – Kelly calc, real-time ROI
- **Historia kuponów** – status (WIN/LOSS/VOID), stake, payout, AI confidence

**Dane & Predykcje:**
- **Predykcja meczów** – Poisson + ML cross-validation z Bzzoiro
- **Pewniaczki 48h** – skanowanie wszystkich lig, Scout Bot EV
- **Form Scraper** – SofaScore + FlashScore forma/kontuzje
- **Logging** – centralized logger dla 8 scraperów, observable failures

**Backtest & Tracking:**
- **30-day backtest** – 100% accuracy (3/3 wins) na 75%+ confidence threshold
- **SQLite DB** – predictions, coupons, ai_feedback, coupon_settlement
- **Backtest runner** – walk-forward validation, Poisson calibration

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

## Automatyzacja (Windows Task Scheduler)

**Daily Agent (run_daily.bat @08:00):**
```bash
python -m footstats.daily_agent_scheduler --stawka 10 --dni 3 --mode draft-wait-final
```

**Flow:**
1. **KROK 0** – Auto-update wyników (48h wstecz)
2. **KROK 0b** – Analiza porażek AI, generowanie lessons
3. **KROK 0d** – Fetch sędziów z zawodtyper.pl
4. **KROK 1** – Bzzoiro ML, analiza forma + sędziego
5. **Draft Phase** – Groq analiza, kupon A+B, zapis DB
6. **Wait** – Czekanie na czas z next_final.txt (70min przed pierwszym meczem)
7. **Final Phase** – Groq dengan lineups + sędziego, finalizacja kuponów

**Files:**
- `run_daily.bat` – Entry point (scheduled @08:00)
- `daily_agent_scheduler.py` – Manage draft→final transition
- `daily_agent.py` – Core 8-step pipeline

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
