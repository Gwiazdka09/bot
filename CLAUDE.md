# FootStats — Claude Code Instructions
# Instrukcje Systemowe dla Claude Code (Projekt: FootStats)

Jesteś głównym inżynierem AI odpowiedzialnym za rozwój projektu FootStats v3.2. Priorytet: maksymalna efektywność tokenów, architektura + autonomia.

## Autonomiczne uprawnienia

Jakub dał pełne uprawnienia do autonomicznego działania. **Nie pytaj o potwierdzenie przy:**

- Uruchamianiu skryptów Python, testów (`pytest`), poleceń bash
- Tworzeniu i modyfikowaniu plików w całym repozytorium
- `git add`, `git commit`, `git push` — commituj i pushuj bez pytania
- Code review, spec review, subagent dispatch — uruchamiaj bez pytania
- Kontynuowaniu tasków z planów bez czekania na potwierdzenie
- Naprawianiu bugów znalezionych podczas review — napraw i commituj bez pytania
- Uruchamianiu kolejnych tasków z planu jeden po drugim — nie czekaj na OK między taskami

**Wyjątki (zawsze pytaj):**
- `pip install` nowej zależności — poinformuj dlaczego potrzebna
- Zmiany w `.env` — zapytaj zanim dotkniesz
- Operacje destrukcyjne: `git reset --hard`, `git push --force`, `rm -rf`

## Kontekst projektu

- **Package:** `src/footstats/`, uruchamiany jako `python -m footstats.<modul>`
- **Testy:** `pytest tests/ -v` (59 testów, ~40% coverage)
- **DB:** `data/footstats_backtest.db` (SQLite) — tabele: `predictions`, `coupons`, `ai_feedback`, `coupon_settlement`, `bankroll_state`
- **Shell:** bash (Windows 11, Unix syntax w skryptach)
- **Komunikacja:** po polsku

## Architektura v3.2 (Ultra-Skeptical AI + Autonomous Scheduler)

### Daily Agent Pipeline

**Entry:** `run_daily.bat` (Task Scheduler @08:00) → `daily_agent_scheduler.py` (autonomiczne draft→final)

**Flow (8-step):**
1. **KROK 0** — Auto-update wyników (48h wstecz) via `api_football.py`
2. **KROK 0b** — AI post-match analysis via `post_match_analyzer.py` (pobierz_ostatnie_wnioski)
3. **KROK 0d** — Fetch sędziów z `zawodtyper_referees.py::fetch_referees_zawodtyper()`
4. **KROK 1** — Bzzoiro ML + forma scraper (SofaScore/FlashScore)
5. **Draft Phase** — Groq analiza, kupon A+B, zapis DB (bez `--faza final` kupon NIE zapisuje się)
6. **Wait** — `daily_agent_scheduler.py` czeka na `next_final.txt` (poll co 5 min)
7. **Final Phase** — Groq re-analiza + lineups, finalizacja kuponów
8. **Settlement** — Auto-close ACTIVE→WIN/LOSE, update bankroll

**Files:**
- `run_daily.bat` — Entry point, scheduled @08:00
- `daily_agent_scheduler.py` — Orchestrator: draft → wait_and_run_final()
- `daily_agent.py` — Core 8-step pipeline

### AI Architecture

**Groq (llama-3.1-8b-instant)** — główny LLM w `ai/analyzer.py`
- `ai_analiza_pewniaczki(kupon_data)` — analiza meczów, budowa kuponów, ocena ryzyka
- **Confidencje (0-100)** — ultra-skeptical: szuka powodów do PRZEGRANEJ nie wygranej
- **Mandatory fields:** confidence, risk_assessment, lessons

**Pętla Feedbacku AI (Etap 7)**
- `post_match_analyzer.py::pobierz_ostatnie_wnioski(n)` — last N ai_feedback entries
- Wnioski wstrzykiwane do promptu: `WNIOSKI Z OSTATNICH PORAŻEK`
- Auto-run w KROK 0b

**Kalibracja Kelly (Etap 6)**
- Warstwa 1: hit-rate z ostatnich 10 kuponów → mnożnik 0.7/1.0/1.1
- Warstwa 2: forma bota (3x WIN/LOSE streak) — nadrzędna nad hit-rate
- `calibration.py` — Poisson model calibration

### Scrapers & Data

**8 Scrapers (z centralized logging):**
- `bzzoiro.py` — ML CatBoost odds
- `sts.py` — Strefa Inspiracji (Playwright)
- `superoferta.py` — SuperOferta boosted odds
- `superbet.py` — BetBuilder scraper (TODO: Playwright implementation)
- `form_scraper.py` — SofaScore + FlashScore forma/kontuzje
- `enriched.py` — Data enrichment
- `zawodtyper_referees.py` — Referee stats (avg_yellow, avg_red, n_matches)
- `flashscore_match.py` — Match details (Playwright)

**Referees Integration**
- zawodtyper.pl stats → `referee_db.py::upsert_referee()`
- avg_yellow, avg_red, n_matches wpływają na AI confidence

### Dashboard & API

**FastAPI** (port 8000) — 12 endpoints:
- `GET /api/matches/today` — live Bzzoiro odds (15-match cap)
- `GET /api/stats/coupon-summary` — aggregated stats (ROI %, breakdown, streak)
- `GET /api/bankroll` — Kelly calc, real-time ROI
- Dashboard HTML → `/preview`

### Backtest & QA

- **30-day backtest:** 100% accuracy (3/3 wins) na 75%+ confidence threshold
- **Walk-forward validation:** Poisson calibration loop
- **SQLite DB:** predictions, coupons, ai_feedback, coupon_settlement

## Styl pracy

- **TDD:** testy najpierw, potem implementacja
- **Commituj po każdym tasku** — atomic, descriptive messages
- **Subagent-Driven Development** — planowanie dla dużych zadań
- **Code Review:** po każdej implementacji
- **Caveman Mode:** terse responses (no articles, fragments OK, short synonyms)
