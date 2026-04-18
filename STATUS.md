# FootStats — STATUS PROJEKTU

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
- [ ] **BetBuilder Superbet** — Playwright login, scraper SuperSocial, `scrapers/superbet.py`
- [ ] **Test integracji Telegram** — `tests/test_telegram.py` wysyła testową wiadomość (weryfikacja tokenu i uprawnień bota)

### Priorytet NISKI
- [ ] **Etap 5 (JSON export)** ← przeniesiony z ŚREDNIEGO (nie blokuje nic)
- [ ] Audyt i usunięcie `legacy/`
- [ ] Langfuse LLM Observability (śledzenie tokenów Groq)
- [x] ~~**Etap 7 (RAG)**~~ — **GOTOWE** (`ai_feedback` → wstrzykiwane w prompt Groq)

## DONE — ukończone

### Veryfikacja i integracja (v3.1-3.2)
- ✅ **Weryfikacja harmonogramu** — `docs/scheduler_setup.md` + `scripts/` z `silent_run.vbs` (commit 566c822)
- ✅ **Instalacja Streamlit** — `src/footstats/dashboard.py` aktywna, uruchom: `python -m streamlit run src/footstats/dashboard.py` (commit 57a24ca)
- ✅ **Czyszczenie powiadomień UI** — usunięte `alert()` dialogi, wyłączone `setInterval()` polling, dodane inline error messages w HTML (v3.2)

---

## Stos technologiczny

| Warstwa | Narzędzie | Uwagi |
|---------|-----------|-------|
| LLM | Groq (llama-3.3-70b) | główny model analizy |
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
