# FootStats — TODO

## Sprint bieżący (2026-04-11)

- [x] `normalize_team_name` w `src/footstats/utils/normalize.py` — 25 testów, 25/25 pass
- [x] `evening_agent.py` używa `normalize_team_name` przez `_norm()` (delegacja)
- [x] `data/team_mappings.json` — pusty słownik z komentarzami + aliasy PSG/Paris SG
- [x] `--dry-run` i `--date` dodane do `daily_agent.py` (4 blokowane efekty uboczne)
- [x] Dry-run 2026-04-11 — skrapery działają (47 kandydatów Bzzoiro)
- [x] `DECISIONS.md` zaktualizowany — lista meczów do monitorowania

## Następne zadania

- [ ] Decision Score filter: przenieść po Groq lub liczyć z `pw`+kurs Bzzoiro pre-Groq
- [ ] Faza final o 14:20 — uruchomić `daily_agent --faza final` (bez dry-run)
- [ ] Kelly Criterion: `kelly_stake` zwraca `None` dla all legs — zbadać dlaczego (brak `pewnosc_pct` pre-Groq?)
- [ ] `team_mappings.json` — rozbudować o typowe błędy API-Football (np. "Man Utd" → "Manchester United")
- [ ] Backtest kalibracja (Etap 6) — walk-forward na df_wyk, progi 95%/80%
- [ ] RAG (Etap 7) — ładowanie historycznych lekcji Groq do kontekstu

## Zablokowane

- BetBuilder Superbet — czeka na Playwright login (wymaga `.env` SUPERBET_*)
