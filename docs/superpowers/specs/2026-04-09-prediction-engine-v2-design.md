# FootStats — Prediction Engine v2 + Zamknięty Krąg Uczenia

**Data:** 2026-04-09
**Priorytet:** Skuteczność predykcji (cel 95%) + automatyczny cykl uczenia
**Podejście:** A — Zamknięty krąg uczenia

---

## 1. Kontekst i cel

System FootStats v3.0 ma działający pipeline Poisson + CatBoost (Bzzoiro) + Groq AI,
ale brakuje:
- zamkniętego kręgu weryfikacja → uczenie → kalibracja
- rozbudowanego modelu analitycznego (tylko sztywny Poisson)
- automatycznej weryfikacji wyników kuponów
- modelu decyzyjnego go/no-go opartego na danych

**Cel:** Zbudować system który co dzień uczy się na własnych błędach i dąży do 95% accuracy
na typowanych zdarzeniach.

---

## 2. Architektura ogólna

```
08:00  daily_agent.py --faza draft
         → Bzzoiro + Ensemble → Decision Score (próg 40)
         → Groq: DRAFT kupon
         → SQLite status=DRAFT + Telegram

HH:MM  daily_agent.py --faza final  (1h przed pierwszym meczem)
         → API-Football lineups + referee_db
         → Re-score Decision Score (próg 60)
         → Groq: FINALNY kupon
         → SQLite status=ACTIVE + Telegram

23:00  evening_agent.py
         → API-Football wyniki
         → Weryfikacja nóg WIN/LOSS/VOID
         → Aktualizuj SQLite
         → Jeśli 20+ wyników → auto-trainer → groq_lessons.json
         → Telegram: raport dzienny

pon 09:00  weekly_report.py
         → Groq analizuje 7 dni
         → Raport accuracy/ROI + rekomendacje
```

---

## 3. Rozszerzony model analityczny

### 3.1 xG-Lambda (nowe wejście do Poissona)

Zamiast surowych goli historycznych jako λ, używamy xG z FBref:

```python
# core/xg_lambda.py
def xg_lambda(team, df_hist, ostatnie_n=10):
    """Lambda Poissona z xG (dokładniejszy estymator siły ataku/obrony)."""
    mecze = df_hist[df_hist.home == team].tail(ostatnie_n)
    return mecze['xg_home'].mean()  # kolumna już w historical_loader
```

Wagi czasowe: mecze z ostatnich 2 tygodni × 2.0, starsze × 1.0.

### 3.2 Ensemble (nowy rdzeń predykcji)

```python
# core/ensemble.py
def ensemble_pred(g, a, df, context, market) -> dict:
    p_poisson = poisson_probs(xg_lambda(g, a, df))     # z xG
    p_bzz     = bzzoiro_probs(g, a)                     # CatBoost Bzzoiro
    wagi      = get_dynamic_weights(market, league)     # z backtest DB
    return weighted_average(p_poisson, p_bzz, wagi)
```

Dynamiczne wagi aktualizowane co tydzień z danych backtest:
- Over 2.5: Poisson 68% acc vs CatBoost 74% → wagi [0.35, 0.65]
- Wynik 1X2: wagi zależne od historycznej accuracy per liga

### 3.3 Kontekst zewnętrzny

**Składy (Faza 2, 1h przed):**
- `scrapers/lineup_scraper.py` — API-Football `/fixtures/lineups`
- Kluczowi gracze: napastnicy + bramkarz → jeśli absent: confidence −15 pkt

**Sędzia:**
- `scrapers/referee_db.py` — buduje i aktualizuje SQLite tabelę `referees`
- Statystyki: kartki/mecz, gole/mecz, faule/mecz, bias domowy (%)
- Sędzia "kartkowy" (>5 żółtych/mecz): sygnał dla BTTS/Over meczów fizycznych

**Forma rozszerzona (już istnieje, rozbudować):**
- xG w ostatnich 5 meczach (nie tylko W/D/L)
- Shots on target ratio jako proxy "jakości szans"

---

## 4. Decision Score (0–100)

Każdy kandydat dostaje score przed decyzją o wejściu w kupon.

| Warunek | Punkty |
|---|---|
| EV_netto > 0 (oba modele) | +15 |
| Ensemble confidence > 70% | +20 |
| Brak ROTACJA / ZMECZENIE | +15 |
| PATENT lub TWIERDZA | +10 |
| Kluczowi zawodnicy w składzie* | +10 |
| Sędzia neutralny | +10 |
| Historical accuracy > 65% (ten rynek) | +10 |
| Brak ROZBIEŻNOŚĆ (Poisson vs ML <20%) | +10 |
| **PRÓG DRAFT (08:00)** | **>= 40** |
| **PRÓG FINAL (HH:MM)** | **>= 60** |

*Dostępne tylko w Fazie 2 (składy). W Fazie 1 ten punkt = 0.

```python
# core/decision_score.py
def score_kandydat(w, context, phase="draft") -> tuple[int, list[str]]:
    """Zwraca (score, powody). Phase: 'draft' | 'final'."""
    ...
```

---

## 5. SQLite — nowe tabele

### Tabela `coupons`

```sql
CREATE TABLE coupons (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    phase           TEXT NOT NULL,          -- 'draft' | 'final'
    status          TEXT NOT NULL,          -- 'DRAFT'|'ACTIVE'|'WON'|'LOST'|'PARTIAL'|'VOID'
    kupon_type      TEXT NOT NULL,          -- 'A' | 'B' | 'single'
    legs_json       TEXT NOT NULL,          -- JSON lista nóg
    total_odds      REAL,
    stake_pln       REAL,
    payout_pln      REAL,                   -- NULL dopóki nie rozliczony
    roi_pct         REAL,
    groq_reasoning  TEXT,
    decision_score  INTEGER,
    match_date_first TEXT                   -- data pierwszego meczu w kuponie
);
```

### Tabela `referees`

```sql
CREATE TABLE referees (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL UNIQUE,
    country         TEXT,
    avg_yellow      REAL,   -- żółte/mecz
    avg_red         REAL,
    avg_goals       REAL,   -- gole/mecz w jego meczach
    home_win_pct    REAL,   -- % wygranych gospodarzy
    n_matches       INTEGER,
    updated_at      TEXT
);
```

### Istniejąca tabela `predictions` — bez zmian

Nowe pole `coupon_id` (FK → coupons) przy zapisie typów AI.

---

## 6. Nowe moduły (mapa plików)

```
src/footstats/
  core/
    xg_lambda.py          NOWY — lambda z xG
    ensemble.py           NOWY — weighted average Poisson+ML
    decision_score.py     NOWY — score 0-100 go/no-go
    coupon_tracker.py     NOWY — CRUD coupons w SQLite
  scrapers/
    lineup_scraper.py     NOWY — API-Football lineups
    referee_db.py         NOWY — statystyki sędziów
  evening_agent.py        NOWY — cron 23:00 weryfikacja
  weekly_report.py        NOWY — raport tygodniowy Groq

  daily_agent.py          ROZSZERZONY — --faza draft/final
  ai/analyzer.py          ROZSZERZONY — przyjmuje context dict
  ai/trainer.py           BEZ ZMIAN — już działa
```

---

## 7. Harmonogram Windows Task Scheduler

| Zadanie | Czas | Komenda |
|---|---|---|
| FootStats Draft | 08:00 codziennie | `python -m footstats.daily_agent --faza draft` |
| FootStats Final | dynamiczny¹ | `python -m footstats.daily_agent --faza final` |
| FootStats Evening | 23:00 codziennie | `python -m footstats.evening_agent` |
| FootStats Weekly | pon. 09:00 | `python -m footstats.weekly_report` |

¹ Faza draft zapisuje czas pierwszego meczu − 70min do pliku `data/next_final.txt`.
Alternatywnie: fallback stały czas 13:30 gdy mecze popołudniowe.

---

## 8. Przepływ uczenia (zamknięty krąg)

```
[Kupon ACTIVE]
    → 23:00 evening_agent weryfikuje wyniki
    → predictions.tip_correct = 0/1
    → coupons.status = WON/LOST/PARTIAL
    → jeśli n_nowych >= 20:
        trainer.py analizuje przegrane nogi
        → pattern: "Over 2.5 w meczach z ROTACJA → 62% miss"
        → groq_lessons.json zaktualizowany
        → _SYSTEM_TYPER wstrzykuje lekcje do prompta
    → co tydzień:
        weekly_report.py liczy accuracy per rynek/liga
        → dynamiczne wagi ensemble zaktualizowane
        → Telegram raport + rekomendacje zmian zasad
```

---

## 9. Testy

- `tests/test_decision_score.py` — jednostkowe: każdy warunek osobno
- `tests/test_ensemble.py` — porównanie weighted_average z edge cases
- `tests/test_coupon_tracker.py` — CRUD + statusy SQLite
- `tests/test_evening_agent.py` — mock API-Football + weryfikacja nóg

---

## 10. Priorytety implementacji (kolejność)

1. `coupon_tracker.py` + migracja SQLite (fundament dla reszty)
2. `evening_agent.py` — weryfikacja wyników (zamknięcie pętli)
3. `decision_score.py` — score 0-100
4. `xg_lambda.py` + `ensemble.py` — lepszy model
5. `lineup_scraper.py` + `referee_db.py` — kontekst zewnętrzny
6. Rozbudowa `daily_agent.py` (--faza draft/final)
7. `weekly_report.py` — raport

Każdy etap jest niezależny i deployowalny osobno.
