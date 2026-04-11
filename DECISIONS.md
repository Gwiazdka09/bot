# DECISIONS.md — FootStats Daily Log

---

## 2026-04-11 — Dry-run Draft: mecze do porannego monitorowania

Uruchomiono: `python -m footstats.daily_agent --faza draft --date 2026-04-11 --dry-run --tylko-kupon`
Bzzoiro zwrócił **47 kandydatów** w oknie 72h.

### KUPON A (stawka 10 PLN | kurs 1.60 | szansa 48.2% | wygrana netto ~14 PLN)

| # | Mecz | Typ | Kurs | Pewność |
|---|------|-----|------|---------|
| 1 | Celtic vs St. Mirren | 1 (dom) | 1.18 | 67% |
| 2 | Coventry City vs Sheffield Wednesday | Over 2.5 | 1.36 | 72% |

### KUPON B (stawka 5 PLN | kurs 1.71 | szansa 56.0% | wygrana netto ~7.50 PLN)

| # | Mecz | Typ | Kurs | Pewność |
|---|------|-----|------|---------|
| 1 | Dundee United vs Livingston | 1 (dom) | 1.71 | 56% |

### TOP 3 — wartościowe obserwacje (nie w kuponie)

| # | Mecz | Typ | Kurs | EV% | Uwaga |
|---|------|-----|------|-----|-------|
| 1 | Coventry City vs Sheffield Wednesday | 2 (gość) | 18.00 | +168% | Wysoki EV, niska pewność — spekulacja |
| 2 | RB Leipzig vs Borussia M'gladbach | 2 (gość) | 6.00 | +75% | Umiarkowana pewność |
| 3 | Cercle Brugge vs RAAL La Louvière | 2 (gość) | 3.75 | +56% | Umiarkowana pewność |

### Decyzje i obserwacje

- Decision Score filter nie zadziałał (brak pól EV/pewność na wyjściu Bzzoiro) — kandydaci nie są pre-filtrowani
- Faza `final` zaplanowana na **14:20** (czas startu meczu z `next_final.txt`)
- `--dry-run` nie zapisał do DB ani TXT — kupon wymaga potwierdzenia przed fazą final

[DECISION-2026-04-11-dry-run-flags] Dodano `--date` i `--dry-run` do `daily_agent.py`. Rationale: możliwość podglądu pipeline'u bez efektów ubocznych (DB, TXT, Telegram, Windows toast). Dry-run blokuje dokładnie 4 mutacje stanu, pozostawiając odczyty (Bzzoiro, Groq) aktywne.

## 2026-04-10

### Evening Agent — Run 01:36 CEST (UTC 23:36)

**API-Football**: 433 zakończonych meczów (FT) dla 2026-04-10

---

### Aktywne Kupony (stan po evening agent)

#### Kupon #4 — DRAFT | stake=5.0 PLN | odds=26.82 | decision_score=0

| # | Gospodarz | Gość | Typ | Kurs | Wynik |
|---|---|---|---|---|---|
| 1 | FC Augsburg | TSG Hoffenheim | 1 | 3.45 | ⏳ PENDING |
| 2 | Wisła Płock | KS Lechia Gdańsk | 2 | 2.45 | ⏳ PENDING |
| 3 | Roma | Pisa | Over 2.5 | 1.90 | ⏳ PENDING |
| 4 | Al-Taawoun | Al-Kholood | Over 2.5 | 1.67 | ⏳ PENDING |

> ⚠️ **Uwaga**: Kupon w stanie DRAFT (nie ACTIVE) — nie był promowany przez faze final.
> Kupony DRAFT nie przechodzą weryfikacji evening agent (tylko ACTIVE). To jest bug workflow.

#### Kupon #3 — DRAFT | stake=5.0 PLN | odds=18.35 | decision_score=0

| # | Gospodarz | Gość | Typ | Kurs | Wynik |
|---|---|---|---|---|---|
| 1 | FC Augsburg | TSG Hoffenheim | 1 | 3.45 | ⏳ PENDING |
| 2 | Wisła Płock | KS Lechia Gdańsk | 2 | 2.45 | ⏳ PENDING |
| 3 | Al-Taawoun | Al-Kholood | Over 2.5 | 1.67 | ⏳ PENDING |
| 4 | FC Twente | FC Volendam | Over 2.5 | 1.30 | ⏳ PENDING |

> ⚠️ **Uwaga**: Identyczny problem — DRAFT, nie ACTIVE.

---

### Decyzje i Obserwacje

#### 🟡 Problem: Kupony w stanie DRAFT nie są weryfikowane

Evening agent (`run_evening_agent`) sprawdza kupony przez `get_active_coupons()`, która zwraca
status IN (`DRAFT`, `ACTIVE`). Kod weryfikuje **wszystkie** z nich, ale ustawia nowy status tylko
jeśli `nowy_status != STATUS_ACTIVE`. Kupony z `decision_score=0` oznaczają, że faza `draft` z `daily_agent --faza draft`
nie uruchomiła się poprawnie lub kupony były tworzone bez enrichmentu.

#### 🔴 Brak fazy Final

Kupony #3 i #4 są w stanie DRAFT (nie ACTIVE) — oznacza to, że `daily_agent --faza final`
nie uruchomił się dla tych kuponów. Powinny być w ACTIVE przed evening agent.

#### ✅ Evening Agent: infrastruktura działa

- API key aktywny (433 FT meczów znaleziono)
- Fuzzy match działa (próg 0.60)
- `update_coupon_status` działa poprawnie

---

### Następne Kroki (2026-04-11)

- [ ] Uruchomić `python -m footstats.daily_agent --faza draft` ok. 08:00
- [ ] Uruchomić `python -m footstats.daily_agent --faza final` przed meczami
- [ ] Evening agent uruchomi się automatycznie przez Task Scheduler o 23:00
- [ ] Sprawdzić wyniki kuponów #3 i #4 ręcznie (jeśli mecze już zakończone)

---

*Ostatnia aktualizacja: 2026-04-11 01:36 CEST | Evening Agent v2*
