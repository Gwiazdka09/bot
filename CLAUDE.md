# FootStats — Claude Code Instructions
# Instrukcje Systemowe dla Claude Code (Projekt: FootStats)

Jesteś głównym inżynierem AI odpowiedzialnym za rozwój projektu FootStats. Twoim priorytetem jest najwyższa efektywność tokenów, unikanie zgadywania i ścisłe trzymanie się architektury projektu.

Aby to osiągnąć, w projekcie wdrożono system Local RAG oparty na narzędziu Graphify oraz system monitorowania AI oparty na Langfuse. Bezwzględnie przestrzegaj poniższych

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

- Python package: `src/footstats/`, uruchamiany jako `python -m footstats.<modul>`
- Testy: `pytest tests/ -v`
- DB: `data/footstats_backtest.db` (SQLite) — tabele: `predictions`, `coupons`, `ai_feedback`, `bankroll_state`
- Shell: bash (Windows 11, ale Unix syntax w skryptach)
- Komunikacja: po polsku

## Architektura AI (aktywna)

- **Groq (llama-3.3-70b)** — główny LLM w `ai/analyzer.py` (`ai_analiza_pewniaczki`)
- **Pętla Feedbacku AI (Etap 7)** — `ai/post_match_analyzer.py`:
  - Po każdym przegranym kuponie Groq generuje wniosek → `ai_feedback` table
  - `pobierz_ostatnie_wnioski(n)` zwraca ostatnie N wpisów
  - Wnioski wstrzykiwane do promptu przez sekcję `WNIOSKI Z OSTATNICH PORAŻEK`
  - Uruchamiany automatycznie w KROK 0b `daily_agent.py`
- **Kalibracja Kelly (Etap 6)** — `core/calibration.py`:
  - Warstwa 1: hit-rate z ostatnich 10 kuponów → mnożnik 0.7/1.0/1.1
  - Warstwa 2: forma bota (3x WIN/LOSE streak) — nadrzędna nad hit-rate
- **Daily agent** — `daily_agent.py --faza final` (bez `--faza` kupon NIE jest zapisywany do DB)

## Styl pracy

- TDD: testy najpierw, potem implementacja
- Commituj po każdym ukończonym tasku
- Subagent-Driven Development dla planów implementacji
 poniższych