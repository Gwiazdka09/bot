[![CI](https://github.com/Gwiazdka09/bot/actions/workflows/ci.yml/badge.svg)](https://github.com/Gwiazdka09/bot/actions/workflows/ci.yml)

# FootStats v2.7 MultiSource & Intelligence

Zaawansowany bot do analizy meczow pilkarskich. Lacczy dane z 3 darmowych API,
model Poissona, cross-walidacje ML, kursy bukmacherow (scraping) i analize AI.

## Moduly

| Plik | Opis |
|---|---|
| `footstats.py` | Glowny skrypt – menu, Poisson, tabele, PDF, Pewniaczki |
| `ai_client.py` | Klient AI: Groq 70B (online) z fallbackiem na Ollama (lokalnie) |
| `ai_analyzer.py` | Analiza meczu przez AI – laczy predykcje FootStats z kursami |
| `scraper_kursy.py` | Scraper kursow bukmacherskich z Betexplorer (Playwright) |
| `scraper_sts.py` | Scraper kuponow najlepszych typerow z STS Strefa Inspiracji |
| `footstats_logging.py` | Modul logowania – plik obrotowy + stderr, monkey-patching |

## Zrodla danych API

Wszystkie darmowe, bez karty kredytowej:

1. **football-data.org** (`FOOTBALL_API_KEY`) – 10 req/min, 12 lig TOP
2. **api-sports.io** (`APISPORTS_KEY`) – 100 req/dzien, 1200+ lig (Ekstraklasa, MLS, Saudi Pro, Liga MX...)
3. **sports.bzzoiro.com** (`BZZOIRO_KEY`) – bez limitu, ML CatBoost predictions + kursy + cross-walidacja Poisson

## AI

- **Groq** (llama-3.3-70b-versatile) – podstawowy backend AI, darmowy, online
- **Ollama** (gemma2:2b) – fallback lokalny, offline
- Analiza meczu: laczy predykcje statystyczne z kursami bukmacherow
- Wykrywanie value betow (model vs bukmacher)

## Scrapery (Playwright)

- **Betexplorer** (`scraper_kursy.py`) – kursy 1X2 na nadchodzace mecze
- **STS Strefa Inspiracji** (`scraper_sts.py`) – kupony top typerow, analiza AI

Wymagaja: `playwright install chromium`

## Opcje menu

Po zaladowaniu ligi dostepne sa nastepujace opcje:

| Opcja | Opis |
|---|---|
| **1** | Tabela ligowa (Importance 2.0 – tryb finalny) |
| **2** | Ostatnie wyniki |
| **3** | Predykcja meczu (+ H2H / Patent / Fortress / Dom-Wyjazd) |
| **4** | Porownanie formy (H2H 24 mies. + historia) |
| **5** | Analiza kolejki (LIGA / PUCHAR / REWANZ / FINAL v2.6) |
| **6** | Eksport PDF (raport z komentarzem) |
| **7** | Zmien lige |
| **9** | Analiza Dom/Wyjazd (dom vs wyjazd statystyki, wykrywanie Podroznikow) |
| **P** | Pewniaczki Tygodnia (ML + Poisson, Scout Bot EV, PDF) |
| **A** | Analiza Kuponu (wklej mecze – Scout Bot oceni EV i ryzyko) |
| **I** | AI Analiza meczu (Groq 70B / Ollama + kursy bukmacherow) |
| **J** | AI Analiza kolejki (wszystkie nadchodzace mecze) |

## Instalacja

```bash
# 1. Zainstaluj zaleznosci
pip install -r requirements.txt

# 2. Zainstaluj przegladarke dla scraperow
playwright install chromium

# 3. Skonfiguruj klucze API
#    Skopiuj env_wzor.txt do .env i uzupelnij klucze:
cp env_wzor.txt .env
#    Wymagane klucze: FOOTBALL_API_KEY, APISPORTS_KEY, BZZOIRO_KEY, GROQ_API_KEY
```

## Uruchomienie

```bash
python footstats.py
```

## Testy

```bash
# Testy jednostkowe
python -m pytest test_footstats.py -v

# Testy integracyjne AI (wymaga .env z kluczami)
python -m pytest test_ai_integration.py -v

# Wszystkie testy
python -m pytest test_footstats.py test_ai_integration.py -v
```

## Licencja

MIT
