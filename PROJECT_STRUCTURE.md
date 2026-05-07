# FootStats Project Structure

Generated: 2026-05-07

```plaintext
FootStats/
├── README.md               # Main project documentation (recruiter-ready)
├── STATUS.md               # Current project health and metrics
├── CLAUDE.md               # System instructions for Claude
├── pyproject.toml          # Project configuration and dependencies
├── Dockerfile              # Containerization for the API
├── docker-compose.yml      # Orchestration for DB and API
├── LICENSE                 # MIT License
│
├── src/                    # Python Source Code
│   └── footstats/
│       ├── __init__.py
│       ├── __main__.py
│       ├── cli.py          # Interactive Terminal Interface
│       ├── dashboard.py    # Streamlit Dashboard (Live Analytics)
│       ├── config.py       # Environment and App configuration
│       ├── daily_agent.py  # Core prediction loop
│       ├── ...
│       ├── ai/             # LLM Agents (Groq, RAG, Post-match)
│       ├── core/           # Mathematical models (Poisson, Kelly, BetBuilder)
│       ├── scrapers/       # Data collection engines (Playwright, API)
│       ├── api/            # FastAPI REST endpoints
│       └── utils/          # Logging, Caching, DB helpers
│
├── scripts/                # Automation and Utility Scripts
│   ├── run_daily.bat       # Scheduler entry point
│   ├── czysc_baze.py       # DB Maintenance
│   ├── visualize_brain.py  # RAG Graph Visualization
│   └── ...
│
├── tests/                  # Pytest Suite (>100 tests)
├── assets/                 # Visual artifacts, diagrams, and debug images
├── data/                   # SQLite Databases (backtest, results)
├── docs/                   # Extended documentation and archives
├── logs/                   # Application runtime logs
└── pdf/                    # Generated prediction reports
```
