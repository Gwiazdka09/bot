# FootStats v3.0

Narzędzie do analizy piłkarskiej i predykcji wyników. Łączy model Poissona, ML (Bzzoiro CatBoost), 3 źródła danych API oraz AI (Groq llama-3.3-70b) w jedno CLI.

## Funkcje

- **Predykcja meczów** – model Poissona + ML cross-walidacja z Bzzoiro
- **Pewniaczki 48h** – skanowanie wszystkich lig Bzzoiro, Scout Bot EV, analiza AI
- **AI Analiza** – Groq 70B analizuje typy, buduje kupony AKO, ocenia Twój kupon
- **Form Scraper** – SofaScore (primary) + FlashScore (fallback), forma + kontuzje
- **SuperOferta** – scrapuje boosted odds ze STS, porównuje z Bzzoiro
- **Analiza kolejki** – wszystkie nadchodzące mecze ligi + ranking pewności
- **Dom/Wyjazd** – statystyki H/A drużyn
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

Stwórz plik `.env` w katalogu głównym:

```plaintext
FOOTBALL_DATA_KEY=twoj_klucz_football_data_org
APISPORTS_KEY=twoj_klucz_api_sports_io
BZZOIRO_KEY=twoj_klucz_bzzoiro
GROQ_API_KEY=twoj_klucz_groq
```

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
