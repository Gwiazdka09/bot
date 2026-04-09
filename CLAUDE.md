# FootStats — Claude Code Instructions

## Autonomiczne uprawnienia

Jakub dał pełne uprawnienia do autonomicznego działania. **Nie pytaj o potwierdzenie przy:**

- Uruchamianiu skryptów Python, testów (`pytest`), poleceń bash
- Tworzeniu i modyfikowaniu plików w całym repozytorium
- `git add`, `git commit`, `git push` — commituj i pushuj bez pytania
- Code review, spec review, subagent dispatch
- Kontynuowaniu tasków z planów bez czekania na potwierdzenie

**Wyjątki (zawsze pytaj):**
- `pip install` nowej zależności — poinformuj dlaczego potrzebna
- Zmiany w `.env` — zapytaj zanim dotkniesz
- Operacje destrukcyjne: `git reset --hard`, `git push --force`, `rm -rf`

## Kontekst projektu

- Python package: `src/footstats/`, uruchamiany jako `python -m footstats.<modul>`
- Testy: `pytest tests/ -v`
- DB: `data/footstats_backtrack.db` (SQLite)
- Shell: bash (Windows 11, ale Unix syntax w skryptach)
- Komunikacja: po polsku

## Styl pracy

- TDD: testy najpierw, potem implementacja
- Commituj po każdym ukończonym tasku
- Subagent-Driven Development dla planów implementacji
