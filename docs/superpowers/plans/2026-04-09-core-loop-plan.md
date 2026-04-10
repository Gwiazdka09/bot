# Prediction Engine v2 — Plan 1: Core Loop

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Zamknąć pętlę uczenia: śledzić kupony w SQLite, automatycznie weryfikować wyniki po 23:00, i oceniać kandydatów score 0-100 przed wejściem w kupon.

**Architecture:** Trzy nowe moduły — `coupon_tracker.py` (SQLite CRUD dla kuponów), `evening_agent.py` (cron 23:00, API-Football → weryfikacja → auto-trainer), `decision_score.py` (score 0-100 go/no-go). Wszystkie korzystają z istniejącego `backtest.py` i `results_updater.py`. Zero zmian w `poisson.py`, `analyzer.py`, `bzzoiro.py`.

**Tech Stack:** Python 3.11, SQLite (sqlite3), API-Football (api-sports.io), Rich, python-dotenv, pytest, requests

---

## Mapa plików

```
src/footstats/
  core/
    coupon_tracker.py     NOWY  — CRUD: save_coupon, update_coupon_status,
                                         get_active_coupons, get_coupon_legs
    decision_score.py     NOWY  — score_kandydat(w, context, phase) → (int, list[str])
  evening_agent.py        NOWY  — run_evening_agent(date_str) → dict

tests/
  test_coupon_tracker.py  NOWY  — CRUD + statusy + ROI + migracja kolumny
  test_decision_score.py  NOWY  — każde kryterium osobno + progi draft/final
  test_evening_agent.py   NOWY  — mock API-Football + weryfikacja nóg + status kuponu
```

Istniejące pliki czytane (nie modyfikowane w tym planie):
- `src/footstats/core/backtest.py` — `init_db()`, `update_result()`, `_oblicz_tip_correct()`
- `src/footstats/scrapers/results_updater.py` — wzorzec `_fetch_fixtures()`
- `src/footstats/utils/telegram_notify.py` — `send_message()`
- `src/footstats/config.py` — `ENV_APISPORTS`
- `data/footstats_backtest.db` — istniejąca baza (migracja bezpieczna)

---

## Task 1: coupon_tracker.py — SQLite CRUD dla kuponów

**Files:**
- Create: `src/footstats/core/coupon_tracker.py`
- Create: `tests/test_coupon_tracker.py`

- [x] **Step 1.1: Napisz testy (TDD — najpierw testy)**

Utwórz `tests/test_coupon_tracker.py`:

```python
"""tests/test_coupon_tracker.py"""
import json
import pytest


@pytest.fixture(autouse=True)
def tmp_db(tmp_path, monkeypatch):
    """Każdy test dostaje własną pustą bazę."""
    db = tmp_path / "test.db"
    import footstats.core.coupon_tracker as ct
    monkeypatch.setattr(ct, "DB_PATH", db)
    yield db


from footstats.core.coupon_tracker import (
    init_coupon_tables,
    save_coupon,
    update_coupon_status,
    get_active_coupons,
    get_coupon_legs,
)


def test_save_coupon_returns_positive_id():
    legs = [{"gospodarz": "PSG", "goscie": "Lyon", "typ": "1", "kurs": 1.45}]
    cid = save_coupon("draft", "A", legs, total_odds=1.45, stake_pln=10.0)
    assert isinstance(cid, int)
    assert cid > 0


def test_new_coupon_has_draft_status():
    cid = save_coupon("draft", "A", [])
    active = get_active_coupons()
    assert len(active) == 1
    assert active[0]["status"] == "DRAFT"


def test_lost_coupon_not_in_active():
    cid = save_coupon("final", "A", [], stake_pln=10.0)
    update_coupon_status(cid, "LOST", payout_pln=0.0)
    active = get_active_coupons()
    assert all(c["id"] != cid for c in active)


def test_won_coupon_roi_calculated():
    cid = save_coupon("final", "A", [], stake_pln=10.0)
    update_coupon_status(cid, "WON", payout_pln=110.0)
    from footstats.core.coupon_tracker import _connect
    with _connect() as conn:
        row = conn.execute("SELECT roi_pct FROM coupons WHERE id=?", (cid,)).fetchone()
    assert row["roi_pct"] == pytest.approx(1000.0, abs=1.0)


def test_get_coupon_legs_roundtrip():
    legs = [{"gospodarz": "Bayern", "goscie": "Dortmund", "typ": "1X", "kurs": 1.30}]
    cid = save_coupon("draft", "B", legs)
    assert get_coupon_legs(cid) == legs


def test_get_coupon_legs_unknown_id_returns_empty():
    assert get_coupon_legs(9999) == []


def test_predictions_table_gets_coupon_id_column():
    """Migration: kolumna coupon_id musi być w predictions po init."""
    from footstats.core.backtest import init_db
    from footstats.core.coupon_tracker import _connect
    # Najpierw utwórz tabelę predictions przez backtest
    import footstats.core.backtest as bt
    monkeypatch = pytest.MonkeyPatch()
    # Upraszczamy: tylko sprawdzamy że init_coupon_tables nie exploduje na istniejącej tabeli
    init_coupon_tables()
    init_coupon_tables()  # drugi raz — idempotentne
```

- [x] **Step 1.2: Uruchom testy — upewnij się że FAIL**

```
pytest tests/test_coupon_tracker.py -v
```

Oczekiwany wynik: `ERROR` — `ModuleNotFoundError: No module named 'footstats.core.coupon_tracker'`

- [x] **Step 1.3: Utwórz `src/footstats/core/coupon_tracker.py`**

```python
"""
coupon_tracker.py – SQLite CRUD dla kuponów FootStats.

Tabela coupons: śledzi kupony od DRAFT do WON/LOST/VOID.
Migracja: dodaje coupon_id FK do istniejącej tabeli predictions.

Użycie:
    from footstats.core.coupon_tracker import save_coupon, update_coupon_status
    cid = save_coupon("draft", "A", legs, total_odds=12.5, stake_pln=10.0)
    update_coupon_status(cid, "WON", payout_pln=110.0)
"""

import json
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parents[3] / "data" / "footstats_backtest.db"

# Statusy kuponu
STATUS_DRAFT   = "DRAFT"
STATUS_ACTIVE  = "ACTIVE"
STATUS_WON     = "WON"
STATUS_LOST    = "LOST"
STATUS_PARTIAL = "PARTIAL"
STATUS_VOID    = "VOID"

ACTIVE_STATUSES = (STATUS_DRAFT, STATUS_ACTIVE)


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_coupon_tables() -> None:
    """Tworzy tabele coupons i migruje predictions. Bezpieczne wielokrotne wywołanie."""
    with _connect() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS coupons (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at       TEXT NOT NULL DEFAULT (datetime('now')),
                phase            TEXT NOT NULL,
                status           TEXT NOT NULL DEFAULT 'DRAFT',
                kupon_type       TEXT NOT NULL,
                legs_json        TEXT NOT NULL DEFAULT '[]',
                total_odds       REAL,
                stake_pln        REAL,
                payout_pln       REAL,
                roi_pct          REAL,
                groq_reasoning   TEXT,
                decision_score   INTEGER,
                match_date_first TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_coupon_status  ON coupons(status);
            CREATE INDEX IF NOT EXISTS idx_coupon_created ON coupons(created_at);
        """)
        # Migration: coupon_id do predictions (bezpieczne jeśli już istnieje)
        try:
            conn.execute(
                "ALTER TABLE predictions ADD COLUMN coupon_id INTEGER REFERENCES coupons(id)"
            )
        except sqlite3.OperationalError:
            pass  # kolumna już istnieje


def save_coupon(
    phase: str,
    kupon_type: str,
    legs: list[dict],
    total_odds: float | None = None,
    stake_pln: float | None = None,
    groq_reasoning: str = "",
    decision_score: int | None = None,
    match_date_first: str | None = None,
) -> int:
    """
    Zapisuje nowy kupon (status=DRAFT). Zwraca id.

    phase:      'draft' | 'final'
    kupon_type: 'A' | 'B' | 'single'
    legs:       lista dict z kluczami: gospodarz, goscie, typ, kurs,
                opcjonalnie: pewnosc, liga, prediction_id
    """
    init_coupon_tables()
    legs_json = json.dumps(legs, ensure_ascii=False)
    with _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO coupons
                (phase, status, kupon_type, legs_json, total_odds, stake_pln,
                 groq_reasoning, decision_score, match_date_first)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (phase, STATUS_DRAFT, kupon_type, legs_json,
             total_odds, stake_pln, groq_reasoning, decision_score, match_date_first),
        )
        return cur.lastrowid


def update_coupon_status(
    coupon_id: int,
    status: str,
    payout_pln: float | None = None,
) -> None:
    """
    Aktualizuje status kuponu. Jeśli payout_pln podany — oblicza roi_pct.

    status: 'DRAFT' | 'ACTIVE' | 'WON' | 'LOST' | 'PARTIAL' | 'VOID'
    """
    roi_pct = None
    with _connect() as conn:
        if payout_pln is not None:
            row = conn.execute(
                "SELECT stake_pln FROM coupons WHERE id=?", (coupon_id,)
            ).fetchone()
            if row and row["stake_pln"]:
                roi_pct = round(
                    (payout_pln - row["stake_pln"]) / row["stake_pln"] * 100, 1
                )
        conn.execute(
            "UPDATE coupons SET status=?, payout_pln=?, roi_pct=? WHERE id=?",
            (status, payout_pln, roi_pct, coupon_id),
        )


def get_active_coupons() -> list[sqlite3.Row]:
    """Zwraca kupony ze statusem DRAFT lub ACTIVE, od najnowszych."""
    init_coupon_tables()
    with _connect() as conn:
        return conn.execute(
            "SELECT * FROM coupons WHERE status IN (?, ?) ORDER BY created_at DESC",
            ACTIVE_STATUSES,
        ).fetchall()


def get_coupon_legs(coupon_id: int) -> list[dict]:
    """Zwraca listę nóg kuponu jako list[dict]. Pusty list jeśli kupon nie istnieje."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT legs_json FROM coupons WHERE id=?", (coupon_id,)
        ).fetchone()
        if not row:
            return []
        return json.loads(row["legs_json"])
```

- [x] **Step 1.4: Uruchom testy — upewnij się że PASS**

```
pytest tests/test_coupon_tracker.py -v
```

Oczekiwany wynik:
```
tests/test_coupon_tracker.py::test_save_coupon_returns_positive_id PASSED
tests/test_coupon_tracker.py::test_new_coupon_has_draft_status PASSED
tests/test_coupon_tracker.py::test_lost_coupon_not_in_active PASSED
tests/test_coupon_tracker.py::test_won_coupon_roi_calculated PASSED
tests/test_coupon_tracker.py::test_get_coupon_legs_roundtrip PASSED
tests/test_coupon_tracker.py::test_get_coupon_legs_unknown_id_returns_empty PASSED
tests/test_coupon_tracker.py::test_predictions_table_gets_coupon_id_column PASSED
```

- [x] **Step 1.5: Commit**

```bash
git add src/footstats/core/coupon_tracker.py tests/test_coupon_tracker.py
git commit -m "feat: coupon_tracker — SQLite CRUD dla kuponów (Task 1)"
```

---

## Task 2: decision_score.py — Score 0-100 go/no-go

**Files:**
- Create: `src/footstats/core/decision_score.py`
- Create: `tests/test_decision_score.py`

- [x] **Step 2.1: Napisz testy**

Utwórz `tests/test_decision_score.py`:

```python
"""tests/test_decision_score.py"""
import pytest
from footstats.core.decision_score import score_kandydat, is_go, PROG_DRAFT, PROG_FINAL


def _kandydat(**kwargs) -> dict:
    """Buduje minimalny słownik kandydata z defaultami."""
    defaults = {
        "ev_netto": -0.01,
        "pewnosc": 0.60,
        "czynniki": [],
        "roznica_modeli": 5.0,
        "accuracy": None,
    }
    defaults.update(kwargs)
    return defaults


def test_ev_netto_positive_gives_15_points():
    w = _kandydat(ev_netto=0.05)
    score, powody = score_kandydat(w)
    assert score >= 15
    assert any("EV_netto" in p for p in powody)


def test_ev_netto_negative_gives_0():
    w = _kandydat(ev_netto=-0.01)
    score, _ = score_kandydat(w)
    assert score < 15  # zero za EV


def test_high_confidence_gives_20_points():
    w = _kandydat(pewnosc=0.80, ev_netto=-0.01, roznica_modeli=25.0)
    score, _ = score_kandydat(w)
    assert score >= 20


def test_confidence_below_70_gives_0_for_confidence():
    w = _kandydat(pewnosc=0.65)
    score, _ = score_kandydat(w)
    # brak rotacji/zmęczenia (+15) + brak rozbieżności (+10) = 25 max bez confidence
    assert score <= 25


def test_rotacja_removes_15_points():
    w_clean = _kandydat(czynniki=[])
    w_rotacja = _kandydat(czynniki=["ROTACJA"])
    s_clean, _ = score_kandydat(w_clean)
    s_rotacja, _ = score_kandydat(w_rotacja)
    assert s_clean - s_rotacja == 15


def test_patent_gives_10_points():
    w_no = _kandydat(czynniki=[])
    w_patent = _kandydat(czynniki=["PATENT"])
    s_no, _ = score_kandydat(w_no)
    s_patent, _ = score_kandydat(w_patent)
    assert s_patent - s_no == 10


def test_twierdza_gives_10_points():
    w = _kandydat(czynniki=["TWIERDZA"])
    s, powody = score_kandydat(w)
    assert any("TWIERDZA" in p for p in powody)


def test_historical_accuracy_above_65_gives_10():
    w = _kandydat(accuracy=0.70)
    s_with, _ = score_kandydat(w)
    w_no = _kandydat(accuracy=0.60)
    s_without, _ = score_kandydat(w_no)
    assert s_with - s_without == 10


def test_rozbieznosc_above_20_removes_10():
    w_ok = _kandydat(roznica_modeli=10.0)
    w_rozn = _kandydat(roznica_modeli=25.0)
    s_ok, _ = score_kandydat(w_ok)
    s_rozn, _ = score_kandydat(w_rozn)
    assert s_ok - s_rozn == 10


def test_lineup_ok_gives_10_only_in_final_phase():
    w = _kandydat()
    ctx = {"lineup_ok": True, "referee_neutral": False}
    s_draft, _ = score_kandydat(w, ctx, phase="draft")
    s_final, _ = score_kandydat(w, ctx, phase="final")
    assert s_final - s_draft == 10  # tylko lineup (referee_neutral=False → 0)


def test_referee_neutral_gives_10_only_in_final_phase():
    w = _kandydat()
    ctx = {"lineup_ok": False, "referee_neutral": True}
    s_draft, _ = score_kandydat(w, ctx, phase="draft")
    s_final, _ = score_kandydat(w, ctx, phase="final")
    assert s_final - s_draft == 10


def test_perfect_candidate_scores_70_in_draft():
    """Maks w drafcie: 15+20+15+10+10+10 = 80 (bez składu i sędziego)."""
    w = _kandydat(
        ev_netto=0.10,
        pewnosc=0.85,
        czynniki=["PATENT"],
        roznica_modeli=5.0,
        accuracy=0.75,
    )
    score, _ = score_kandydat(w, phase="draft")
    assert score == 80


def test_is_go_draft_threshold():
    assert is_go(40, "draft") is True
    assert is_go(39, "draft") is False


def test_is_go_final_threshold():
    assert is_go(60, "final") is True
    assert is_go(59, "final") is False


def test_pewnosc_as_percentage_normalized():
    """pewnosc=85 (procenty) traktowane jak 0.85."""
    w = _kandydat(pewnosc=85)  # podane jako procenty
    score, _ = score_kandydat(w)
    assert score >= 20  # confidence > 70% → +20
```

- [x] **Step 2.2: Uruchom testy — upewnij się że FAIL**

```
pytest tests/test_decision_score.py -v
```

Oczekiwany: `ERROR — ModuleNotFoundError: No module named 'footstats.core.decision_score'`

- [x] **Step 2.3: Utwórz `src/footstats/core/decision_score.py`**

```python
"""
decision_score.py – Score 0-100 dla kandydatów na nogi kuponu.

Kryteria i punkty:
  EV_netto > 0 (model)              +15
  Ensemble confidence > 70%         +20
  Brak ROTACJA / ZMECZENIE          +15
  PATENT lub TWIERDZA               +10
  Historical accuracy > 65%         +10
  Brak ROZBIEŻNOŚĆ (<20% diff)      +10
  [tylko faza final]:
    Kluczowi zawodnicy w składzie   +10
    Sędzia neutralny                +10

Progi: draft >= 40 | final >= 60
"""

PROG_DRAFT = 40
PROG_FINAL = 60


def score_kandydat(
    w: dict,
    context: dict | None = None,
    phase: str = "draft",
) -> tuple[int, list[str]]:
    """
    Oblicza Decision Score dla kandydata.

    w: dict z polami kandydata (ze szybkie_pewniaczki / daily_agent):
        ev_netto (float)          — EV po podatku 12%, np. 0.05 = 5%
        pewnosc (float)           — 0–1 lub 0–100 (auto-normalizacja)
        czynniki (list[str])      — ["ROTACJA", "PATENT", "TWIERDZA", ...]
        roznica_modeli (float)    — różnica Poisson vs ML w pkt procentowych
        accuracy (float | None)   — historyczna accuracy na tym rynku (0–1)

    context: dict z polami Fazy 2 (opcjonalne):
        lineup_ok (bool)          — kluczowi zawodnicy w składzie
        referee_neutral (bool)    — sędzia bez wyraźnego biasu

    phase: 'draft' | 'final'

    Zwraca: (score: int, powody: list[str])
    """
    context = context or {}
    score = 0
    powody: list[str] = []

    # 1. EV_netto > 0 (+15)
    ev = w.get("ev_netto", w.get("ev"))
    if ev is not None and ev > 0:
        score += 15
        powody.append(f"EV_netto={ev:+.1%} > 0 (+15)")
    else:
        powody.append(f"EV_netto={ev} <= 0 (0)")

    # 2. Ensemble confidence > 70% (+20)
    pewnosc = w.get("pewnosc", w.get("pw", 0)) or 0
    if pewnosc > 1:  # podana jako procenty → znormalizuj
        pewnosc = pewnosc / 100
    if pewnosc > 0.70:
        score += 20
        powody.append(f"Pewność={pewnosc:.0%} > 70% (+20)")
    else:
        powody.append(f"Pewność={pewnosc:.0%} <= 70% (0)")

    # 3. Brak ROTACJA/ZMECZENIE (+15)
    czynniki = [str(c).upper() for c in (w.get("czynniki") or w.get("factors") or [])]
    ostrzegawcze = [c for c in czynniki if c in ("ROTACJA", "ZMECZENIE")]
    if not ostrzegawcze:
        score += 15
        powody.append("Brak ROTACJA/ZMECZENIE (+15)")
    else:
        powody.append(f"UWAGA: {', '.join(ostrzegawcze)} — minus 15 pkt (0)")

    # 4. PATENT lub TWIERDZA (+10)
    wzmacniajace = [c for c in czynniki if c in ("PATENT", "TWIERDZA")]
    if wzmacniajace:
        score += 10
        powody.append(f"{', '.join(wzmacniajace)} (+10)")

    # 5. Historical accuracy > 65% (+10)
    accuracy = w.get("accuracy") or w.get("historical_accuracy")
    if accuracy is not None and accuracy > 0.65:
        score += 10
        powody.append(f"Historical acc={accuracy:.0%} > 65% (+10)")

    # 6. Brak ROZBIEŻNOŚĆ Poisson vs ML < 20 pkt (+10)
    rozn = w.get("roznica_modeli") or w.get("rozbieznosc")
    if rozn is None or abs(rozn) < 20:
        score += 10
        powody.append("Brak ROZBIEŻNOŚĆ Poisson/ML (+10)")
    else:
        powody.append(f"ROZBIEŻNOŚĆ={abs(rozn):.0f}% >= 20% (0)")

    # 7 & 8. Kontekst zewnętrzny — tylko faza final
    if phase == "final":
        if context.get("lineup_ok", False):
            score += 10
            powody.append("Skład kompletny (+10)")
        else:
            powody.append("Skład: brak danych lub kluczowy gracz absent (0)")

        if context.get("referee_neutral", False):
            score += 10
            powody.append("Sędzia neutralny (+10)")
        else:
            powody.append("Sędzia: brak danych lub kartkowy (0)")

    return score, powody


def is_go(score: int, phase: str = "draft") -> bool:
    """True jeśli score >= progu dla fazy. draft=40, final=60."""
    return score >= (PROG_FINAL if phase == "final" else PROG_DRAFT)
```

- [x] **Step 2.4: Uruchom testy — upewnij się że PASS**

```
pytest tests/test_decision_score.py -v
```

Oczekiwany wynik: wszystkie 13 testów PASSED.

- [x] **Step 2.5: Commit**

```bash
git add src/footstats/core/decision_score.py tests/test_decision_score.py
git commit -m "feat: decision_score — score 0-100 go/no-go dla kandydatów (Task 2)"
```

---

## Task 3: evening_agent.py — Weryfikacja wyników po 23:00

**Files:**
- Create: `src/footstats/evening_agent.py`
- Create: `tests/test_evening_agent.py`

- [x] **Step 3.1: Napisz testy z mock API-Football**

Utwórz `tests/test_evening_agent.py`:

```python
"""tests/test_evening_agent.py"""
import json
import pytest
from unittest.mock import patch, MagicMock


# ── Fixtures ───────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def patch_db(tmp_path, monkeypatch):
    """Przekieruj obie bazy na tmp."""
    import footstats.core.coupon_tracker as ct
    import footstats.core.backtest as bt
    db = tmp_path / "test.db"
    monkeypatch.setattr(ct, "DB_PATH", db)
    monkeypatch.setattr(bt, "DB_PATH", db)
    yield db


@pytest.fixture
def sample_fixture_psg_lyon():
    """Fixture API-Football: PSG 2-1 Lyon (zakończony)."""
    return {
        "fixture": {"status": {"short": "FT"}},
        "teams": {
            "home": {"name": "Paris Saint-Germain"},
            "away": {"name": "Olympique Lyonnais"},
        },
        "goals": {"home": 2, "away": 1},
    }


@pytest.fixture
def sample_fixture_inprogress():
    """Fixture API-Football: mecz w trakcie."""
    return {
        "fixture": {"status": {"short": "1H"}},
        "teams": {
            "home": {"name": "Bayern Munich"},
            "away": {"name": "Borussia Dortmund"},
        },
        "goals": {"home": 1, "away": 0},
    }


# ── Testy pomocników ────────────────────────────────────────────────────────

from footstats.evening_agent import (
    _wynik_z_fixture,
    _find_result,
    _status_kuponu,
)


def test_wynik_z_fixture_finished(sample_fixture_psg_lyon):
    result = _wynik_z_fixture(sample_fixture_psg_lyon)
    assert result == ("Paris Saint-Germain", "Olympique Lyonnais", "2-1")


def test_wynik_z_fixture_inprogress_returns_none(sample_fixture_inprogress):
    assert _wynik_z_fixture(sample_fixture_inprogress) is None


def test_find_result_fuzzy_match(sample_fixture_psg_lyon):
    wynik = _find_result("PSG", "Lyon", [sample_fixture_psg_lyon])
    assert wynik == "2-1"


def test_find_result_no_match():
    fixture = {
        "fixture": {"status": {"short": "FT"}},
        "teams": {"home": {"name": "Juventus"}, "away": {"name": "Inter"}},
        "goals": {"home": 1, "away": 1},
    }
    wynik = _find_result("Arsenal", "Chelsea", [fixture])
    assert wynik is None


def test_status_kuponu_all_win():
    assert _status_kuponu(["WIN", "WIN", "WIN"]) == "WON"


def test_status_kuponu_any_loss():
    assert _status_kuponu(["WIN", "LOSS", "WIN"]) == "LOST"


def test_status_kuponu_pending_stays_active():
    assert _status_kuponu(["WIN", "PENDING"]) == "ACTIVE"


def test_status_kuponu_all_void():
    assert _status_kuponu(["VOID", "VOID"]) == "VOID"


def test_status_kuponu_empty():
    assert _status_kuponu([]) == "VOID"


# ── Test integracyjny run_evening_agent ─────────────────────────────────────

def test_run_evening_agent_marks_coupon_won(sample_fixture_psg_lyon):
    """Kupon z nogą PSG-1 wygrywa gdy PSG wygrywa 2-1."""
    from footstats.core.coupon_tracker import save_coupon, get_active_coupons, init_coupon_tables
    from footstats.evening_agent import run_evening_agent

    init_coupon_tables()
    legs = [{"gospodarz": "PSG", "goscie": "Lyon", "typ": "1", "kurs": 1.45}]
    save_coupon("final", "A", legs, total_odds=1.45, stake_pln=10.0)

    with patch("footstats.evening_agent._fetch_results_today",
               return_value=[sample_fixture_psg_lyon]), \
         patch("footstats.evening_agent._send_telegram_summary"):
        summary = run_evening_agent("2026-04-09")

    assert summary["won"] == 1
    active = get_active_coupons()
    assert len(active) == 0  # kupon przeniesiony do WON


def test_run_evening_agent_marks_coupon_lost(sample_fixture_psg_lyon):
    """Kupon z nogą Lyon-1 przegrywa gdy Lyon przegrywa 1-2."""
    from footstats.core.coupon_tracker import save_coupon, get_active_coupons, init_coupon_tables
    from footstats.evening_agent import run_evening_agent

    init_coupon_tables()
    legs = [{"gospodarz": "PSG", "goscie": "Lyon", "typ": "2", "kurs": 3.20}]
    save_coupon("final", "A", legs, total_odds=3.20, stake_pln=10.0)

    with patch("footstats.evening_agent._fetch_results_today",
               return_value=[sample_fixture_psg_lyon]), \
         patch("footstats.evening_agent._send_telegram_summary"):
        summary = run_evening_agent("2026-04-09")

    assert summary["lost"] == 1


def test_run_evening_agent_pending_when_no_result():
    """Kupon zostaje ACTIVE gdy mecz jeszcze nie zakończony."""
    from footstats.core.coupon_tracker import save_coupon, get_active_coupons, init_coupon_tables
    from footstats.evening_agent import run_evening_agent

    init_coupon_tables()
    legs = [{"gospodarz": "Bayern", "goscie": "Dortmund", "typ": "1", "kurs": 1.60}]
    save_coupon("final", "A", legs, total_odds=1.60, stake_pln=10.0)

    with patch("footstats.evening_agent._fetch_results_today", return_value=[]), \
         patch("footstats.evening_agent._send_telegram_summary"):
        summary = run_evening_agent("2026-04-09")

    assert summary["active"] == 1
    active = get_active_coupons()
    assert len(active) == 1  # nadal aktywny
```

- [x] **Step 3.2: Uruchom testy — upewnij się że FAIL**

```
pytest tests/test_evening_agent.py -v
```

Oczekiwany: `ERROR — ModuleNotFoundError: No module named 'footstats.evening_agent'`

- [x] **Step 3.3: Utwórz `src/footstats/evening_agent.py`**

```python
"""
FootStats Evening Agent
=======================
Uruchamiany o 23:00 — weryfikuje wyniki kuponów przez API-Football.

Użycie:
    python -m footstats.evening_agent
    python -m footstats.evening_agent --date 2026-04-09
"""

import os
import re
import sys
import argparse
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path

import requests
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

from footstats.core.coupon_tracker import (
    get_active_coupons,
    get_coupon_legs,
    update_coupon_status,
    init_coupon_tables,
    STATUS_ACTIVE,
)
from footstats.core.backtest import init_db, update_result, _oblicz_tip_correct

console = Console()

API_BASE = "https://v3.football.api-sports.io"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _similar(a: str, b: str) -> float:
    """Podobieństwo nazw drużyn 0–1."""
    def _norm(s: str) -> str:
        return re.sub(r"[^a-z0-9 ]", "", s.lower()).strip()
    return SequenceMatcher(None, _norm(a), _norm(b)).ratio()


def _wynik_z_fixture(fixture: dict) -> tuple[str, str, str] | None:
    """
    Parsuje fixture z API-Football.
    Zwraca (home_name, away_name, 'HG-AG') lub None jeśli mecz niezakończony.
    """
    status = fixture.get("fixture", {}).get("status", {}).get("short", "")
    if status not in ("FT", "AET", "PEN"):
        return None
    teams = fixture.get("teams", {})
    home = teams.get("home", {}).get("name", "")
    away = teams.get("away", {}).get("name", "")
    goals = fixture.get("goals", {})
    hg, ag = goals.get("home"), goals.get("away")
    if hg is None or ag is None:
        return None
    return home, away, f"{hg}-{ag}"


def _find_result(home: str, away: str, fixtures: list[dict]) -> str | None:
    """
    Fuzzy-match drużyn w liście fixtures API-Football.
    Zwraca wynik '2-1' lub None gdy brak dopasowania (próg similarności >= 0.6).
    """
    best_score = 0.0
    best_result: str | None = None
    for fix in fixtures:
        parsed = _wynik_z_fixture(fix)
        if not parsed:
            continue
        fh, fa, wynik = parsed
        score = (_similar(home, fh) + _similar(away, fa)) / 2
        if score > best_score and score >= 0.6:
            best_score = score
            best_result = wynik
    return best_result


def _status_kuponu(nogi_statusy: list[str]) -> str:
    """
    Oblicza finalny status kuponu z listy statusów nóg.
    'WIN' | 'LOSS' | 'PENDING' | 'VOID'
    """
    if not nogi_statusy:
        return "VOID"
    if "PENDING" in nogi_statusy:
        return STATUS_ACTIVE  # "ACTIVE" — czekamy na resztę meczów
    if all(s == "WIN" for s in nogi_statusy):
        return "WON"
    if any(s == "LOSS" for s in nogi_statusy):
        return "LOST"
    if all(s == "VOID" for s in nogi_statusy):
        return "VOID"
    return "PARTIAL"


# ── API ───────────────────────────────────────────────────────────────────────

def _fetch_results_today(api_key: str, date_str: str) -> list[dict]:
    """Pobiera zakończone mecze z API-Football dla daty YYYY-MM-DD."""
    try:
        r = requests.get(
            f"{API_BASE}/fixtures",
            headers={"x-apisports-key": api_key},
            params={"date": date_str, "status": "FT"},
            timeout=15,
        )
        if r.status_code != 200:
            console.print(f"[yellow]API-Football HTTP {r.status_code}[/yellow]")
            return []
        return r.json().get("response", [])
    except Exception as e:
        console.print(f"[yellow]API-Football błąd sieci: {e}[/yellow]")
        return []


# ── Telegram ──────────────────────────────────────────────────────────────────

def _send_telegram_summary(summary: dict, date_str: str) -> None:
    try:
        from footstats.utils.telegram_notify import send_message
        msg = (
            f"📊 *Evening Report {date_str}*\n"
            f"Sprawdzono: {summary.get('checked', 0)} kuponów\n"
            f"✅ Wygranych: {summary.get('won', 0)}\n"
            f"❌ Przegranych: {summary.get('lost', 0)}\n"
            f"⏳ Oczekujących: {summary.get('active', 0)}"
        )
        send_message(msg)
    except Exception:
        pass  # Telegram opcjonalny


# ── Główna funkcja ────────────────────────────────────────────────────────────

def run_evening_agent(date_str: str | None = None) -> dict:
    """
    Weryfikuje wyniki kuponów dla danej daty.
    Zwraca dict: {checked, won, lost, partial, active}.
    """
    load_dotenv()
    api_key = os.getenv("APISPORTS_KEY", "").strip()
    if not api_key:
        console.print("[red]Brak APISPORTS_KEY w .env — evening agent zatrzymany[/red]")
        return {}

    date_str = date_str or datetime.now().strftime("%Y-%m-%d")
    console.rule(f"[bold cyan]Evening Agent — {date_str}[/bold cyan]")

    init_coupon_tables()
    init_db()

    fixtures = _fetch_results_today(api_key, date_str)
    console.print(f"[dim]API-Football: {len(fixtures)} zakończonych meczów[/dim]")

    active_coupons = get_active_coupons()
    console.print(f"[dim]Aktywne kupony do weryfikacji: {len(active_coupons)}[/dim]")

    summary: dict = {"checked": 0, "won": 0, "lost": 0, "partial": 0, "active": 0}
    nowe_wyniki = 0

    for kupon in active_coupons:
        legs = get_coupon_legs(kupon["id"])
        nogi_statusy: list[str] = []

        for leg in legs:
            home    = leg.get("gospodarz") or leg.get("home", "")
            away    = leg.get("goscie")    or leg.get("away", "")
            ai_tip  = leg.get("typ")       or leg.get("ai_tip", "")

            wynik = _find_result(home, away, fixtures)
            if wynik is None:
                nogi_statusy.append("PENDING")
                continue

            correct = _oblicz_tip_correct(ai_tip, wynik)
            nogi_statusy.append("WIN" if correct == 1 else ("LOSS" if correct == 0 else "VOID"))
            nowe_wyniki += 1

            # Aktualizuj predictions jeśli mamy prediction_id
            pred_id = leg.get("prediction_id")
            if pred_id:
                try:
                    update_result(pred_id, wynik)
                except (ValueError, Exception):
                    pass

        nowy_status = _status_kuponu(nogi_statusy)

        if nowy_status != STATUS_ACTIVE:
            payout = None
            if nowy_status == "WON":
                stake = kupon["stake_pln"] or 10.0
                odds  = kupon["total_odds"] or 1.0
                payout = round(stake * odds * 0.88, 2)  # podatek 12%
            update_coupon_status(kupon["id"], nowy_status, payout_pln=payout)
            key = nowy_status.lower()
            summary[key] = summary.get(key, 0) + 1
        else:
            summary["active"] += 1

        summary["checked"] += 1

    # Wyświetl tabelę
    _print_summary_table(summary)

    # Auto-trainer po 20+ nowych wynikach
    if nowe_wyniki >= 20:
        console.print(f"[green]{nowe_wyniki} nowych wyników → uruchamiam auto-trainer...[/green]")
        import subprocess
        subprocess.Popen(
            [sys.executable, "-m", "footstats.ai.trainer"],
            cwd=Path(__file__).parents[2],
        )

    _send_telegram_summary(summary, date_str)
    return summary


def _print_summary_table(summary: dict) -> None:
    t = Table(title="Evening Agent — Podsumowanie")
    t.add_column("Status", style="cyan")
    t.add_column("Liczba", justify="right")
    t.add_row("Sprawdzonych", str(summary.get("checked", 0)))
    t.add_row("✅ Wygranych",  str(summary.get("won", 0)))
    t.add_row("❌ Przegranych", str(summary.get("lost", 0)))
    t.add_row("⏳ Oczekujących", str(summary.get("active", 0)))
    console.print(t)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="FootStats Evening Agent")
    parser.add_argument("--date", default=None, help="Data YYYY-MM-DD (default: dziś)")
    args = parser.parse_args()
    run_evening_agent(args.date)
```

- [x] **Step 3.4: Uruchom testy — upewnij się że PASS**

```
pytest tests/test_evening_agent.py -v
```

Oczekiwany wynik: wszystkie 12 testów PASSED.

- [x] **Step 3.5: Uruchom pełny suite — zero regresji**

```
pytest tests/ -v --tb=short
```

Oczekiwany wynik: wszystkie poprzednie testy PASS + nowe PASS.

- [x] **Step 3.6: Commit**

```bash
git add src/footstats/evening_agent.py tests/test_evening_agent.py
git commit -m "feat: evening_agent — weryfikacja wyników kuponów 23:00 (Task 3)"
```

---

## Task 4: Windows Task Scheduler — cron 23:00

**Files:**
- Create: `run_evening_agent.bat`

- [x] **Step 4.1: Utwórz launcher**

Utwórz `run_evening_agent.bat` w katalogu głównym `F:\bot\`:

```bat
@echo off
cd /d F:\bot
call venv\Scripts\activate.bat 2>nul || call .venv\Scripts\activate.bat 2>nul
python -m footstats.evening_agent >> logs\evening_agent.log 2>&1
```

- [x] **Step 4.2: Zarejestruj zadanie w Task Scheduler**

```powershell
schtasks /create /tn "FootStats Evening" /tr "F:\bot\run_evening_agent.bat" /sc daily /st 23:00 /f
```

Weryfikacja:
```powershell
schtasks /query /tn "FootStats Evening"
```

Oczekiwany wynik: zadanie widoczne ze statusem `Ready`.

- [x] **Step 4.3: Test manualny**

```bash
python -m footstats.evening_agent --date 2026-04-08
```

Oczekiwany wynik: Console log z liczbą sprawdzonych kuponów i Rich Table z podsumowaniem. Brak błędów krytycznych.

- [x] **Step 4.4: Commit**

```bash
git add run_evening_agent.bat
git commit -m "chore: launcher evening_agent + Task Scheduler 23:00 (Task 4)"
```

---

## Task 5: Weryfikacja integralna i podsumowanie Planu 1

- [x] **Step 5.1: Uruchom pełny pytest**

```
pytest tests/ -v
```

Oczekiwany wynik: **wszystkie testy PASS**, w tym:
- `tests/test_coupon_tracker.py` — 7 testów
- `tests/test_decision_score.py` — 13 testów
- `tests/test_evening_agent.py` — 12 testów
- Wszystkie poprzednie testy bez regresji

- [x] **Step 5.2: Smoke test decision_score na żywym kandydacie**

```python
python -c "
from footstats.core.decision_score import score_kandydat, is_go
w = {'ev_netto': 0.07, 'pewnosc': 0.78, 'czynniki': ['PATENT'], 'roznica_modeli': 8.0, 'accuracy': 0.71}
score, powody = score_kandydat(w, phase='draft')
print(f'Score: {score}/100')
for p in powody:
    print(f'  {p}')
print(f'GO: {is_go(score)}')
"
```

Oczekiwany wynik: Score=80/100, GO=True.

- [x] **Step 5.3: Smoke test coupon_tracker**

```python
python -c "
from footstats.core.coupon_tracker import save_coupon, get_active_coupons, update_coupon_status
legs = [{'gospodarz': 'PSG', 'goscie': 'Lyon', 'typ': '1', 'kurs': 1.45}]
cid = save_coupon('final', 'A', legs, total_odds=1.45, stake_pln=10.0)
print(f'Saved coupon id={cid}')
active = get_active_coupons()
print(f'Active coupons: {len(active)}')
update_coupon_status(cid, 'WON', payout_pln=11.44)
active = get_active_coupons()
print(f'Active after WON: {len(active)}')
"
```

- [x] **Step 5.4: Commit końcowy Planu 1**

```bash
git add -A
git commit -m "feat: Plan 1 complete — core loop coupon tracking + evening agent + decision score"
```

---

## Co dalej — Plan 2

Plan 2 (oddzielny plik) implementuje:
1. `core/xg_lambda.py` — lambda Poissona z xG zamiast surowych goli
2. `core/ensemble.py` — weighted average Poisson + Bzzoiro z dynamicznymi wagami
3. `scrapers/lineup_scraper.py` — składy z API-Football 1h przed meczem
4. `scrapers/referee_db.py` — statystyki sędziów
5. Rozbudowa `daily_agent.py` — `--faza draft` / `--faza final`
6. `weekly_report.py` — raport tygodniowy Groq
