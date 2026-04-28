# FootStats — Claude Code Instructions

Projekt FootStats v3.2. Komunikacja po polsku.

## Uprawnienia

Pełna autonomia: python, pytest, git commit/push, pliki, code review, subagenty.
**Pytaj przy:** `pip install`, zmiany `.env`, operacje destrukcyjne (reset --hard, push --force, rm -rf).

## Projekt

- **Package:** `src/footstats/`, run: `python -m footstats.<modul>`
- **Testy:** `pytest tests/ -v`
- **DB:** `data/footstats_backtest.db` (SQLite)
- **API:** FastAPI port 8000, dashboard `/preview`
- **Shell:** bash (Win11, Unix syntax)

## Pipeline

`run_daily.bat` @08:00 → `daily_agent_scheduler.py` → `daily_agent.py` (8-step):
wyniki → AI wnioski → sędziowie → Bzzoiro ML → draft kupon → wait → final kupon → settlement

## AI

- **Groq llama-3.1-8b** w `ai/analyzer.py` — ultra-skeptical (szuka porażek)
- Feedback loop: `post_match_analyzer.py` → wnioski wstrzykiwane do promptu
- Kelly calibration: hit-rate + forma streak → mnożnik stawki
