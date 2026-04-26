# FootStats — STATUS PROJEKTU

**Data:** 2026-04-26  
**Wersja:** v3.2 (Ultra-Skeptical AI, Autonomous Scheduler)  
**Branch:** main (+6 commits ahead)

---

## ✅ UKOŃCZONE (Apr 26)

- **Ultra-Skeptical AI Analyzer** (dc32882): System prompt rewrite — AI szuka powodów aby TIP PRZEGRAŁ, nie wygrał. Confidence scale, mandatory risk field (ryzyko).
- **Kreator 48h Window** (01f3b98): Match filtering limited to 48h rolling window from now.
- **Windows Task Scheduler** (run_daily.bat @08:00): Daily agent execution automated.
- **Coupon Settlement Loop**: KROK 0 (results update) + KROK 0b (feedback analysis) active.
- **30-Day Backtest**: Ultra-Skeptical vs baseline — 3/3 wins (100% accuracy, +12.32 PLN).
- **AI Feedback Loop**: Groq generates post-match insights, injected into next day's prompt.

---

## 🔴 WYSOKI PRIORYTET — Rozwinięcia poprawy

### 1. Live Coupon Generation Pipeline ✅ DONE
**Status:** Daily_agent auto-executes --faza draft → waits for next_final.txt → --faza final.  
**Commit:** 2a6a9fa (daily_agent_scheduler.py + run_daily.bat --faza draft)
**Completed:**
- ✅ Scheduled daily_agent --faza final (auto-triggered from next_final.txt)
- ✅ Draft phase runs at 08:00, final phase waits until 70min before first match
- ✅ Coupons now saved to DB on both draft and final phases
- ✅ next_final.txt auto-cleaned after final phase execution

### 2. Playwright Superbet Scraper (BetBuilder)
**Status:** Planned (project notes), not started.  
**Need:** Real odds for Over/BTTS/Combo bets from Superbet SuperSocial tab.  
**Rozwinięcie:**
- Create `src/footstats/scrapers/superbet.py` with Playwright login (.env creds)
- Parse SuperSocial table → extract odds for all market types
- Merge with Bzzoiro/API-Football odds in source_manager
- Test on 3-5 matches daily

### 3. Referee Performance Integration ✅ DONE
**Status:** Zawodtyper scraper integrated into daily agent (KROK 0d).  
**Commit:** db6beab (zawodtyper_referees.py sync + daily_agent integration)
**Completed:**
- ✅ Convert zawodtyper_referees.py from async to sync
- ✅ Add KROK 0d: fetch_referees_zawodtyper() on daily startup
- ✅ Referee data now updates before AI analysis (integrated in KROK 1b)
- ✅ Stats used in AI confidence calculation (referee_signal, avg_yellow, n_matches)

### 4. RAG System (Post-Match Lessons)
**Status:** Etap 7 (planned), partial Groq integration done (ai_feedback table).  
**Problem:** Wnioski z porażek nie są systematycznie cachowane/retrieved.  
**Rozwinięcie:**
- Index ai_feedback entries by match pattern (home/away dominance, team tactics, league)
- Implement vector search (embed mistake summaries)
- Inject top-3 relevant lessons into daily Groq prompt alongside current wnioski
- Track lesson "hit rate" (when applied, did prediction improve?)

---

## 🟡 ŚREDNI PRIORYTET — Bug fixes & Polish

### 5. Print → Logging Refactor ✅ DONE
**Commit:** e392ffa (logging added to 8 scrapers)
**Files Completed:** enriched, flashscore_match, form_scraper, kursy, sts, superbet, superoferta, zawodtyper_referees
**Remaining:** daily_agent, evening_agent (next phase if needed)
**Completed:**
- ✅ Added logging import + logger = getLogger(__name__) to 8 scrapers
- ✅ Replaced print() → logger.info/error/warning with proper f-strings
- ✅ Centralized observability — can now track scraper failures via logs

### 6. Memory Leak in walkforward.py ✅ VERIFIED SAFE
**Status:** No leak found — _connect() already uses sqlite3.Connection context manager
**Code:** `with _connect() as conn:` properly implements __enter__/__exit__
**Result:** No action needed

### 7. Coupon Dashboard Stats 🔄 IN PROGRESS
**Need:** Win/loss breakdown by coupon type, ROI % calculation, streak tracking  
**Endpoint:** Add GET /api/stats/coupon-summary (aggregating last 30 days)
**Schema:**
```json
{
  "total_coupons": 16,
  "total_stake": 160,
  "total_return": 172.32,
  "roi_percent": 7.7,
  "win_count": 12,
  "loss_count": 4,
  "by_type": {
    "top3": {"wins": 8, "stake": 80, "return": 92},
    "combo": {"wins": 3, "stake": 50, "return": 65},
    "single": {"wins": 1, "stake": 30, "return": 15.32}
  },
  "streak": {"current": 3, "max": 5},
  "confidence_avg": 78.5
}
```
**Implementation:** Query coupons + predictions tables, aggregate by type/date, compute ROI

---

## 🟢 NISKI PRIORYTET — Refactoring & Tech Debt

### 8. Scraper Base Class
**Opportunity:** Deduplicate pagination, retry logic, user-agent rotation  
**Files:** bzzoiro.py, api_football.py, superoferta.py, football_data.py

### 9. Test Coverage → 80%
**Current:** ~40% (unit tests thin, integration tests missing)  
**Add:** Tests for coupon settlement, AI confidence validation, form scraper fallbacks

### 10. API Odds Endpoint Refresh
**Endpoint:** GET /api/matches/today  
**Issue:** Returns odds from API-Football (often null); merge with live Bzzoiro on request  
**Improve:** Cache odds for 5min, tag with "last_update" timestamp

---

## 📊 METRICS — Current State

| Metric | Value |
|--------|-------|
| AI Win Rate (75%+ confidence) | 100% (3/3, 30-day backtest) |
| Coupons Generated (Apr 26) | 16 active/closed |
| Backtest Window | 30 days (rolling) |
| DB Size | ~1.5 MB (footstats_backtest.db) |
| Scheduler Status | ✅ Windows Task (08:00 daily) |
| Bzzoiro API | ✅ Connected (53a6e... key) |
| Groq LLM | ✅ Connected (llama-3.1-8b) |

---

## 🔗 KEY FILES

- `src/footstats/daily_agent.py` — Core 8-KROK pipeline (1200+ lines)
- `src/footstats/ai/analyzer.py` — Ultra-skeptical prompt + JSON schema (1200+ lines)
- `data/footstats_backtest.db` — SQLite (predictions, coupons, ai_feedback, bankroll_state)
- `.env` — BZZOIRO_KEY, GROQ_API_KEY, APISPORTS_KEY
- `run_daily.bat` — Windows scheduler entry point

> Jedyne źródło prawdy. Scalony z poprzednich TODO/DECISIONS. Ostatnia aktualizacja: 2026-04-17 (01:35).

---

## Struktura projektu (docelowa)

```
F:\bot\
├── src/footstats/          ← główny pakiet Python
│   ├── ai/                 ← klient Groq, RAG, trainer, analyzer
│   ├── core/               ← Kelly, Poisson, backtest, decyzje, kupony
│   ├── scrapers/           ← Bzzoiro, STS, FlashScore, lineup, sędziowie
│   ├── utils/              ← normalize, cache, logging, Telegram
│   ├── export/             ← PDF, tabele
│   ├── data/               ← historical_loader
│   ├── api/                ← FastAPI main.py
│   ├── gui/                ← React/Vite frontend
│   ├── daily_agent.py      ← główny agent (draft/final)
│   ├── evening_agent.py    ← agent wieczorny
│   ├── weekly_report.py    ← raport tygodniowy
│   ├── cli.py              ← CLI interface
│   └── config.py
├── tests/                  ← pytest (test_*.py)
│   └── scratch/            ← skrypty debugowe (check_db.py etc.)
├── assets/                 ← czcionki (DejaVuSans.ttf)
├── data/                   ← baza SQLite, parquet, JSON
├── logs/                   ← logi agentów
├── docs/                   ← dokumentacja
├── legacy/                 ← stare wersje (tylko archiwum)
├── dashboard.py            ← UI (punkt wejścia, zostaje w root)
├── run_*.bat               ← launche Task Scheduler (ukryte przez VBScript)
└── .env                    ← sekrety (nie w git)
```

---

## Zrealizowane etapy

| Etap | Opis | Commit |
|------|------|--------|
| Bugi fix | Kelly crash, DRAFT→ACTIVE, invisible .bat, pdf_font path | `3783099` |
| Etap 6 | Kalibracja Kelly — hit-rate + bot-forma z ostatnich 10 kuponów (`calibration.py`) | `980d267` |
| Etap 7 | RAG / Pętla Feedbacku AI — `post_match_analyzer.py` + tabela `ai_feedback` | `57a24ca` |
| Dashboard v1 | Streamlit dashboard (`src/footstats/dashboard.py`) — kupony + wyniki z SQLite | `57a24ca` |
| PDF test | Regression test PDF (`tests/test_pdf_export.py`) — polskie znaki, 5 testów | `57a24ca` |
| Przeniesienie plików | assets/, tests/scratch/, usunięcie fbotsrcfootstatsgui/ i scratch/ | `5f15c31` |
| DejaVuSans font | assets/DejaVuSans.ttf dodany, `_zarejestruj_font()` wywołanie naprawione | `998e51f` |
| Dashboard v3.1 | FastAPI + SQLite live dashboard (`api/preview.html`) — bankroll, historia, ustawienia | `4261fc5` |
| Kreator Kuponu | 5-krokowy wizard interaktywny — mecze Bzzoiro → Kelly → zapis do DB | `8e40571` |
| Harmonogram | `docs/scheduler_setup.md` + `scripts/` — Windows Task Scheduler bez okna konsoli | `566c822` |
| Zamykanie kuponów | `update_active_coupons()` w `results_updater.py` — ACTIVE→WIN/LOSE po meczach | `(bieżący)` |
| Automatyzacja | Pełny "Cichy Bot" (`cichy_bot.bat`) + `TRACKED_LEAGUES` w `config.py` | `(bieżący)` |

---

## Naprawione bugi (commit 3783099 — 2026-04-16)

| # | Problem | Status | Gdzie |
|---|---------|--------|-------|
| 1 | Kelly TypeError (bankroll=None crash) | ✅ NAPRAWIONY | `daily_agent._dodaj_kelly` |
| 2 | DRAFT→ACTIVE (kupon utknie w DRAFT) | ✅ NAPRAWIONY | `daily_agent._zapisz_kupon_do_db` |
| 3 | team_mappings.json seeding | ✅ DZIAŁA | `utils/normalize._load_mappings` |
| 4 | Okna cmd.exe wyskakują co 30 min | ✅ NAPRAWIONY | wszystkie `run_*.bat` |
| 5 | pdf_font.py ścieżka do fontu | ✅ NAPRAWIONY | `export/pdf_font.py` |

### Szczegóły napraw

**Kelly (1):** `_dodaj_kelly` ma teraz guard `if not isinstance(bankroll, (int, float)) or bankroll <= 0: bankroll = AGENT_BANKROLL` oraz `try/except (TypeError, ZeroDivisionError)` wokół każdego wywołania → fallback 1.0 PLN zamiast crashu.

**DRAFT→ACTIVE (2):** `promote_to_active` wyizolowane w własnym `try/except`. Brakujący `else` dodany (komunikat "Brak DRAFT" wychodził nawet gdy DRAFT był znaleziony). Outer `except` teraz loguje pełny traceback zamiast cichego warning.

**Invisible .bat (4):** Każdy `.bat` tworzy tymczasowy `.vbs` w `%TEMP%`, który odpala siebie z flagą `-silent` i window-style=0. `wscript` jest bezokienkowy — żadne czarne okno nie wyskakuje z Task Schedulera.

---

## TODO — aktywne

### Priorytet WYSOKI
_(brak aktywnych blokerów)_

### Priorytet ŚREDNI
- [x] **BetBuilder Superbet** — Playwright login, scraper SuperSocial (✅ ISTNIEJE, commit `8e40571`)

### Priorytet NISKI
- [ ] Langfuse LLM Observability (śledzenie tokenów Groq)
- [x] ~~**Etap 7 (RAG)**~~ — **GOTOWE** (`ai_feedback` → wstrzykiwane w prompt Groq)

## DONE — ukończone

### Testowanie i eksport danych (v3.2 — 2026-04-18)
- ✅ **Test integracji Telegram** — `tests/test_telegram.py` z 8 testami (2 unit, 6 integration) — commit `927a660`
- ✅ **Etap 5 (JSON export)** — `src/footstats/export/json_export.py` z 4 funkcjami (kupony, bankroll, AI feedback, raport dzienny) — commit `927a660`
- ✅ **Audyt legacy/** — usunięto `legacy/footstats_v2.7_monolith.py` i `legacy/golazo_bot.py` z gita — commit `927a660`
- ✅ **Pytest markers** — zaktualizowano `pyproject.toml` (unit, integration, slow markers) — commit `927a660`

### Veryfikacja i integracja (v3.1-3.2)
- ✅ **Weryfikacja harmonogramu** — `docs/scheduler_setup.md` + `scripts/` z `silent_run.vbs` (commit 566c822)
- ✅ **Instalacja Streamlit** — `src/footstats/dashboard.py` aktywna, uruchom: `python -m streamlit run src/footstats/dashboard.py` (commit 57a24ca)
- ✅ **Czyszczenie powiadomień UI** — usunięte `alert()` dialogi, wyłączone `setInterval()` polling, dodane inline error messages w HTML (v3.2)

---

## Stos technologiczny

| Warstwa | Narzędzie | Uwagi |
|---------|-----------|-------|
| LLM | Groq (llama-3.1-8b-instant) | główny model analizy |
| Scraper | Playwright | login Bzzoiro, BetBuilder |
| PDF | ReportLab + DejaVuSans | eksport kuponów |
| DB | SQLite WAL | `data/footstats_backtrack.db` |
| UI / Web Dashboard | **FastAPI + HTML/JS** (`api/preview.html`) | live dashboard — bankroll, historia, ustawienia, kreator |
| UI / Web Dashboard (legacy) | **Streamlit** | `src/footstats/dashboard.py` (stary UI, nadal działa) |
| LLM Observability | **Langfuse** | śledzenie zapytań Groq i kosztów tokenów (Etap 7) |
| Scheduler | Windows Task Scheduler + .bat (VBScript) | ciche uruchamianie agentów |

---

## Architektura — kluczowe decyzje

| Decyzja | Powód |
|---------|-------|
| `src-layout` v3.0 | Izolacja pakietu, działa z `python -m footstats.*` |
| SQLite WAL | Brak blokad na Windows przy wieloprocesowym dostępie |
| Fractional Kelly ÷3 | Konserwatywne zarządzanie bankrollem |
| Bzzoiro jako anchor kursu | ~8-9% wyżej niż STS, timezone UTC+4, podatek 12% flat |
| Flat betting 5-10 PLN, kotwica <1.35 | Over lambda>2.8, iteracyjnie kalibrowane |
| Task Scheduler co 30 min (final) | Elastyczne okno [-35, +5] min od `next_final.txt` |
| VBScript trick w .bat | Ukryte okna bez zmiany konfiguracji Task Scheduler |

---

## Znane ograniczenia

- **Timezone edge case**: `get_draft_today()` porównuje UTC daty. Przy DRAFT po 22:00 CEST i FINAL po północy UTC — mogą się minąć o dzień. Ryzyko praktyczne minimalne (draft 08:00, final 16:00).
- **Bzzoiro ML cache bug** — niezidentyfikowany problem w `scrapers/bzzoiro.py`, nie powoduje crashu, niska priorytet.
