# FootStats v3.3-stable
Lang: PL. Context: Soccer predictions (Poisson + RAG + LLM).

## Commands
- Run: `python -m footstats.<module>`
- Test: `pytest tests/ -v`
- API: Port 8000. Dashboard: `/preview`
- UI: `streamlit run src/footstats/dashboard.py`
- Brain: `python scripts/visualize_brain.py`

## Rules
- Autonomy: Python, pytest, git, files, subagents.
- ASK: `pip install`, `.env` changes, destructive ops (reset/force push/rm).
- Style: PEP8, Type hints, PL comments/logs.

## Architecture (Pointers)
- Structure: See `PROJECT_STRUCTURE.md`
- Core: `src/footstats/` (AI, Core, Scrapers)
- DB: `data/footstats_backtest.db` (SQLite)
- Pipeline: `run_daily.bat` (8-step autonomous loop)

## Tech Stack
- Backend: FastAPI, Playwright (Scraping), Groq SDK (Llama 3.1 8B).
- Frontend: Streamlit, vis-network (Brain Graph).
- Logic: Poisson, Kelly Criterion, RAG Feedback Loop.
