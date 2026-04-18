# FootStats Project Structure

Generated: 2026-04-17

```
F:\bot\
├── README.md
├── STATUS.md
├── CLAUDE.md
├── pyproject.toml
├── setup.bat
│
├── src/
│   └── footstats/
│       ├── __init__.py
│       ├── __main__.py
│       ├── config.py
│       ├── cli.py
│       ├── data_fetcher.py
│       ├── dashboard.py
│       ├── daily_agent.py
│       ├── evening_agent.py
│       ├── weekly_report.py
│       │
│       ├── ai/
│       │   ├── __init__.py
│       │   ├── analyzer.py
│       │   ├── client.py
│       │   ├── post_match_analyzer.py
│       │   ├── rag.py
│       │   └── trainer.py
│       │
│       ├── api/
│       │   └── main.py
│       │
│       ├── core/
│       │   ├── __init__.py
│       │   ├── backtest.py
│       │   ├── bankroll.py
│       │   ├── bet_builder.py
│       │   ├── calibration.py
│       │   ├── classifier.py
│       │   ├── confidence.py
│       │   ├── coupon_tracker.py
│       │   ├── decision_score.py
│       │   ├── ensemble.py
│       │   ├── fatigue.py
│       │   ├── form.py
│       │   ├── fortress.py
│       │   ├── h2h.py
│       │   ├── importance.py
│       │   ├── kelly.py
│       │   ├── pattern_analyzer.py
│       │   ├── poisson.py
│       │   ├── quick_picks.py
│       │   ├── queue_analysis.py
│       │   ├── value_bet.py
│       │   ├── walkforward.py
│       │   ├── weekly_picks.py
│       │   └── xg_lambda.py
│       │
│       ├── data/
│       │   ├── __init__.py
│       │   └── historical_loader.py
│       │
│       ├── export/
│       │   ├── __init__.py
│       │   ├── pdf.py
│       │   ├── pdf_font.py
│       │   └── tables.py
│       │
│       ├── scrapers/
│       │   ├── __init__.py
│       │   ├── api_football.py
│       │   ├── base.py
│       │   ├── bzzoiro.py
│       │   ├── enriched.py
│       │   ├── flashscore_match.py
│       │   ├── football_data.py
│       │   ├── form_scraper.py
│       │   ├── kursy.py
│       │   ├── lineup_scraper.py
│       │   ├── referee_db.py
│       │   ├── results_updater.py
│       │   ├── source_manager.py
│       │   ├── sts.py
│       │   ├── superbet.py
│       │   ├── superoferta.py
│       │   └── zawodtyper_referees.py
│       │
│       └── utils/
│           ├── __init__.py
│           ├── cache.py
│           ├── console.py
│           ├── helpers.py
│           ├── logging.py
│           ├── normalize.py
│           └── telegram_notify.py
│
├── tests/
│   ├── __init__.py
│   ├── conftest.py
│   ├── test_backtest.py
│   ├── test_cache.py
│   ├── test_calibration.py
│   ├── test_coupon_tracker.py
│   ├── test_daily_agent_faza.py
│   ├── test_decision_score.py
│   ├── test_ensemble.py
│   ├── test_evening_agent.py
│   ├── test_footstats.py
│   ├── test_helpers.py
│   ├── test_kelly.py
│   ├── test_lineup_scraper.py
│   ├── test_normalize.py
│   ├── test_pattern_analyzer.py
│   ├── test_pdf_export.py
│   ├── test_pdf_minimal.py
│   ├── test_poisson.py
│   ├── test_referee_db.py
│   ├── test_scrapers.py
│   ├── test_walkforward.py
│   ├── test_weekly_report.py
│   ├── test_xg_lambda.py
│   └── test_ai_integration.py
│
├── docs/
│   └── superpowers/
│       ├── plans/
│       │   ├── 2026-04-09-core-loop-plan.md
│       │   └── 2026-04-10-model-enhancement-plan.md
│       └── specs/
│           └── 2026-04-09-prediction-engine-v2-design.md
│
├── legacy/
│   ├── footstats_v2.7_monolith.py
│   └── golazo_bot.py
│
└── pdf/
    ├── FootStats_20260226_1434.pdf
    ├── FootStats_20260228_1113.pdf
    ├── FootStats_20260228_1159.pdf
    ├── FootStats_20260301_1816.pdf
    ├── FootStats_20260301_1915.pdf
    ├── FootStats_20260301_1926.pdf
    ├── Pewniaczki_20260302_1007.pdf
    ├── Pewniaczki_20260303_0014.pdf
    └── Pewniaczki_20260303_0044.pdf
```

## Key Directories

### `src/footstats/` - Main Python Package
- **core/** - Betting logic (Kelly criterion, Poisson, xG/λ, form, etc.)
- **scrapers/** - Data collection (Bzzoiro, STS, API-Football, form scrapers, etc.)
- **ai/** - AI/ML features (Groq integration, RAG, analyzers, trainer)
- **export/** - PDF generation with Polish character support (DejaVuSans font)
- **utils/** - Utilities (logging, caching, Telegram notifications, normalization)
- **data/** - Historical data loading and management
- **api/** - REST API endpoints

### `tests/` - Test Suite (24 modules)
All tests use pytest framework with 80%+ coverage target
- Unit tests for core logic (Kelly, Poisson, decision scoring, etc.)
- Integration tests for agents (daily_agent, evening_agent)
- PDF export tests with Polish characters

### Entry Points
- `daily_agent.py` - Daily coupon generation pipeline
- `evening_agent.py` - Evening match analysis
- `dashboard.py` - Streamlit dashboard
- `cli.py` - Command-line interface
- `__main__.py` - Package entry point

## Configuration Files
- `pyproject.toml` - Python project metadata and dependencies
- `CLAUDE.md` - Claude Code system instructions
- `STATUS.md` - Project status and TODOs
- `README.md` - Project documentation
- `.vscode/settings.json` - VS Code configuration

## Data Files
- `data/footstats_backtest.db` - SQLite database (coupons, predictions, bankroll state)
- `pdf/` - Generated PDF reports
- `legacy/` - Deprecated code versions

## Excluded from this Tree
- `.git/` - Version control (use git commands to explore)
- `.venv/` - Virtual environment
- `__pycache__/` - Python cache files
- `.pytest_cache/` - Pytest cache
- `node_modules/` - JavaScript dependencies (if any)
- `.vscode/` - IDE configuration (minimal)
