# FootStats — Project State

## Phase: AI Pipeline — Etap 5 (normalizacja + daily agent dry-run)
## Last updated: 2026-04-11

### Architektura systemu

```
Bzzoiro ML → Decision Score → [SofaScore forma] → Groq AI → weryfikacja kursów → DB/TXT/Telegram
                                    ↑
                            daily_agent.py (faza draft @ 08:00, faza final @ -1h)
```

Evening agent uruchamia się o 23:00: API-Football → fuzzy-match wyników → update kuponów w DB.

### Key Decisions

- [DECISION-2026-04-11-dry-run-flags] `--dry-run` + `--date` w `daily_agent.py`: blokuje 4 efekty uboczne (update_pending, SQLite, TXT, Telegram/toast). Rationale: bezpieczny podgląd pipeline'u bez mutacji stanu.
- [DECISION-2026-04-11-normalize] `normalize_team_name` w `utils/normalize.py` z `@lru_cache` na JSON mappings. `evening_agent._norm()` deleguje do tej funkcji — single source of truth.
- [DECISION-2026-04-11-decision-score-timing] Decision Score filter nie zadziałał pre-Groq (brak `ev_netto`/`pewnosc_pct` na wyjściu Bzzoiro). TODO: przenieść po Groq lub liczyć z `pw`+kurs.

### Modified Files (ta sesja)

- `src/footstats/utils/normalize.py` — NOWY: normalize_team_name, _strip_diacritics, _load_mappings (lru_cache), reload_mappings
- `src/footstats/evening_agent.py` — `_norm()` deleguje do `normalize_team_name`; import dodany
- `src/footstats/daily_agent.py` — dodano `--date`, `--dry-run`; dry-run blokuje 4 mutacje
- `src/footstats/core/coupon_tracker.py` — get_draft_today, promote_to_active (poprzednia sesja)
- `tests/test_normalize.py` — NOWY: 25 testów (prefiksy, sufiksy, diakrytyki, mappingi, integracja)
- `data/team_mappings.json` — NOWY (gitignored): aliasy PSG, Paris SG
- `DECISIONS.md` — NOWY: log decyzji + morning report 2026-04-11

### Commit history (ta sesja)

```
aaae81b  feat: --dry-run i --date w daily_agent + dry-run morning report 2026-04-11
8856896  feat: normalize_team_name + integracja z evening_agent
```

### Stan scraper (2026-04-11 09:21)

- Bzzoiro: **47 kandydatów** z 72h okna — działa
- API-Football: 1/100 requestów, Ekstraklasa: kandydaci pobierani
- SofaScore/Playwright: niedostępny (pomijany przez `--tylko-kupon`)
- Faza final zaplanowana na **14:20**

### Dry-run wynik (KUPON A — nie zapisany do DB)

| Mecz | Typ | Kurs | Pewność |
|------|-----|------|---------|
| Celtic vs St. Mirren | 1 | 1.18 | 67% |
| Coventry City vs Sheffield Wednesday | Over 2.5 | 1.36 | 72% |

Kurs łączny: 1.60 | Szansa: 48.2% | Wygrana netto: ~14 PLN

### Known Issues

- Decision Score filter nie działa pre-Groq (brak pól EV w kandydatach Bzzoiro)
- `kelly_stake` zwraca `None` dla nóg kuponu — `pewnosc_pct` może nie docierać do Kelly
- `data/` jest w `.gitignore` — `team_mappings.json` tylko lokalnie

### Environment

- Python 3.12, SQLite @ `data/footstats_backtest.db`
- Windows 11, bash syntax w skryptach
- API keys: `BZZOIRO_API_KEY`, `GROQ_API_KEY`, `APISPORTS_KEY` w `.env`
- Komunikacja po polsku
