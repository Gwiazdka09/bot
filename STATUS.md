# FootStats — STATUS

_Ostatnia aktualizacja: 2026-04-16_

---

## Zrobione

- [x] Refaktor src-layout v3.0 — pełny pakiet `src/footstats/`
- [x] `normalize_team_name` w `utils/normalize.py` — 25 testów, 25/25 pass
- [x] `evening_agent.py` — deleguje `_norm()` do `normalize_team_name`
- [x] `data/team_mappings.json` — auto-seeding defaults (PSG, Man Utd, Inter itp.)
- [x] `--dry-run` i `--date` w `daily_agent.py` — blokuje 4 efekty uboczne
- [x] `coupon_tracker.py` — `get_draft_today`, `promote_to_active`
- [x] **Kelly None fix** — `(z.get("pewnosc_pct") or 50) / 100.0` we wszystkich miejscach `_dodaj_kelly`
- [x] **DRAFT→ACTIVE fix** — fallback w `_zapisz_kupon_do_db` wywołuje `update_coupon_status(ACTIVE)` gdy `phase == "final"`
- [x] Pipeline AI (Etapy 1–4): Bzzoiro → forma → Groq → weryfikacja kursów → DB
- [x] Evening agent v2: API-Football fuzzy-match → update statusów kuponów
- [x] Testy: 59/59 pass (ogółem)

---

## W toku (Sprint)

- [ ] **Decision Score filter** — przenieść po Groq lub liczyć z `pw`+kurs Bzzoiro pre-Groq
  - Aktualnie: brak `ev_netto`/`pewnosc_pct` na wyjściu Bzzoiro → filter nie działa pre-Groq
- [ ] **Faza final workflow** — uruchamiać `daily_agent --faza final` przed meczami (docelowo przez Task Scheduler)
- [ ] **`team_mappings.json`** — rozbudować o typowe błędy API-Football (np. "Man Utd" vs "Manchester United")
- [ ] **BetBuilder Superbet** — czeka na Playwright login z `.env` (`SUPERBET_USER`, `SUPERBET_PASS`)

---

## Zablokowane

- **BetBuilder Superbet** — wymaga konfiguracji `.env` z danymi logowania Superbet
- **Etap 6 (backtest kalibracja)** — walk-forward na `df_wyk`, progi 95%=mocny / 80%=słaby → brak planu implementacji
- **Etap 7 (RAG)** — ładowanie historycznych lekcji Groq do kontekstu → nierozpoczęte

---

## Log Decyzji

### [DECISION-2026-04-16-kelly-none-fix]
`(z.get("pewnosc_pct") or 50)` zamiast `z.get("pewnosc_pct", 50)`.
Rationale: `.get(key, default)` nie chroni gdy klucz istnieje z wartością `None` — `None / 100.0` rzucał TypeError połykanym przez `except Exception`.

### [DECISION-2026-04-16-draft-active-fallback]
`_zapisz_kupon_do_db` z `phase="final"` wywołuje `update_coupon_status(cid, ACTIVE)` po `save_coupon()`.
Rationale: `save_coupon` zawsze tworzy `status=DRAFT`; bez tego kroku evening_agent nie rozliczał kuponów z fazy final.

### [DECISION-2026-04-16-team-mappings-seeding]
`_seed_mappings_file()` tworzy `data/team_mappings.json` z 13 domyślnymi aliasami jeśli plik nie istnieje.
Rationale: plik jest w `.gitignore`; nowa instalacja nie miała mappingów i normalize działał bez aliasów.

### [DECISION-2026-04-11-dry-run-flags]
`--date` i `--dry-run` w `daily_agent.py` blokują 4 efekty uboczne (DB, TXT, Telegram, Windows toast).
Rationale: bezpieczny podgląd pipeline'u bez mutacji stanu.

### [DECISION-2026-04-11-normalize]
`normalize_team_name` w `utils/normalize.py` z `@lru_cache` na JSON mappings.
`evening_agent._norm()` deleguje do tej funkcji — single source of truth.

### [DECISION-2026-04-11-decision-score-timing]
Decision Score filter nie zadziałał pre-Groq (brak `ev_netto`/`pewnosc_pct` na wyjściu Bzzoiro).
TODO: przenieść po Groq lub liczyć z `pw`+kurs.
