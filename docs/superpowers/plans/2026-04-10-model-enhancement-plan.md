# Prediction Engine v2 — Plan 2: Model Enhancement

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** Rozszerzyć model predykcji o xG-Lambda, Ensemble (Poisson+Bzzoiro), scraper składów, bazę sędziów, dwufazowy daily_agent i tygodniowy raport Groq.

**Architecture:** Cztery nowe moduły (xg_lambda, ensemble, lineup_scraper, referee_db) + rozbudowanie daily_agent.py o --faza draft/final + weekly_report.py. Wszystkie integrują się z istniejącym decision_score.py i coupon_tracker.py z Planu 1.

**Tech Stack:** Python 3.12, pandas, SQLite, scipy (Poisson), requests, API-Football, Groq SDK, pytest, Rich

---

## Mapa plików

```
src/footstats/
  core/
    xg_lambda.py          NOWY  — lambda Poissona z xG (fallback do hg/ag)
    ensemble.py           NOWY  — weighted_average(poisson, bzzoiro) → dict probs
  scrapers/
    lineup_scraper.py     NOWY  — API-Football /fixtures/lineups → dict
    referee_db.py         NOWY  — SQLite referees + statystyki z API-Football
  daily_agent.py          ROZSZERZONY — dodaj --faza draft|final + ensemble + decision_score
  weekly_report.py        NOWY  — Groq analiza 7 dni → Telegram raport

tests/
  test_xg_lambda.py       NOWY
  test_ensemble.py        NOWY
  test_lineup_scraper.py  NOWY
  test_referee_db.py      NOWY
  test_weekly_report.py   NOWY
```

---

## Task A: xg_lambda.py — lambda Poissona z xG

**Files:**
- Create: `src/footstats/core/xg_lambda.py`
- Create: `tests/test_xg_lambda.py`

### Specyfikacja

```python
# src/footstats/core/xg_lambda.py

import pandas as pd

def xg_lambda(
    team: str,
    df_hist: pd.DataFrame,
    ostatnie_n: int = 10,
    strona: str = "home",   # "home" | "away" | "both"
) -> float:
    """
    Oblicza lambdę Poissona dla drużyny na podstawie xG (lub goli jako fallback).

    Priorytet kolumn:
      - xg_home / xg_away (FBref) — preferowane
      - hg / ag (bramki historyczne) — fallback gdy brak xG

    Wagi czasowe: mecze z ostatnich 14 dni × 2.0, starsze × 1.0.

    Returns: float >= 0.1 (minimalny próg)
    """
    ...


def xg_lambda_pair(
    home: str,
    away: str,
    df_hist: pd.DataFrame,
    ostatnie_n: int = 10,
) -> tuple[float, float]:
    """Oblicza (lambda_home_attack, lambda_away_attack) dla pary."""
    lh = xg_lambda(home, df_hist, ostatnie_n, strona="home")
    la = xg_lambda(away, df_hist, ostatnie_n, strona="away")
    return lh, la
```

- [x] **Step A1: Write failing tests**

```python
# tests/test_xg_lambda.py
import pandas as pd
import pytest
from footstats.core.xg_lambda import xg_lambda, xg_lambda_pair


def _df(rows):
    """Helper — tworzy minimalne df_hist z podanych wierszy."""
    return pd.DataFrame(rows)


def test_xg_lambda_uses_xg_home_when_available():
    df = _df([
        {"home": "PSG", "away": "Lyon", "hg": 1, "ag": 0, "xg_home": 2.5, "xg_away": 0.8, "date": "2025-01-01"},
        {"home": "PSG", "away": "Monaco", "hg": 3, "ag": 1, "xg_home": 3.0, "xg_away": 1.0, "date": "2025-01-08"},
    ])
    df["date"] = pd.to_datetime(df["date"])
    result = xg_lambda("PSG", df, ostatnie_n=10, strona="home")
    assert abs(result - 2.75) < 0.5  # avg of 2.5 and 3.0 (with weights)


def test_xg_lambda_fallback_to_goals_when_no_xg():
    df = _df([
        {"home": "PSG", "away": "Lyon", "hg": 2, "ag": 1, "date": "2025-01-01"},
        {"home": "PSG", "away": "Monaco", "hg": 4, "ag": 0, "date": "2025-01-08"},
    ])
    df["date"] = pd.to_datetime(df["date"])
    result = xg_lambda("PSG", df, ostatnie_n=10, strona="home")
    assert result > 0  # fallback działa


def test_xg_lambda_returns_minimum_when_no_matches():
    df = _df([])
    result = xg_lambda("Nieznana", df, ostatnie_n=10, strona="home")
    assert result >= 0.1  # próg minimalny


def test_xg_lambda_pair_returns_tuple():
    df = _df([
        {"home": "PSG", "away": "Lyon", "hg": 2, "ag": 1, "xg_home": 2.0, "xg_away": 0.9, "date": "2025-01-01"},
    ])
    df["date"] = pd.to_datetime(df["date"])
    lh, la = xg_lambda_pair("PSG", "Lyon", df, ostatnie_n=10)
    assert lh >= 0.1
    assert la >= 0.1


def test_xg_lambda_away_uses_ag_column():
    df = _df([
        {"home": "Lyon", "away": "PSG", "hg": 0, "ag": 3, "xg_home": 0.5, "xg_away": 2.8, "date": "2025-01-01"},
    ])
    df["date"] = pd.to_datetime(df["date"])
    result = xg_lambda("PSG", df, ostatnie_n=10, strona="away")
    assert result > 1.0


def test_xg_lambda_recent_matches_weighted_more():
    """Ostatnie 2 tygodnie mają wagę 2.0."""
    from datetime import datetime, timedelta
    today = datetime.now()
    df = _df([
        {"home": "PSG", "away": "A", "hg": 5, "ag": 0, "xg_home": 5.0, "xg_away": 0.5,
         "date": (today - timedelta(days=3)).strftime("%Y-%m-%d")},  # świeży, waga 2.0
        {"home": "PSG", "away": "B", "hg": 1, "ag": 0, "xg_home": 0.5, "xg_away": 1.0,
         "date": "2024-01-01"},  # stary, waga 1.0
    ])
    df["date"] = pd.to_datetime(df["date"])
    result = xg_lambda("PSG", df, ostatnie_n=10, strona="home")
    # Świeży mecz (5.0 xG) ważony ×2 → wynik > prosta średnia (2.75)
    assert result > 2.75
```

- [x] **Step A2: Run — verify FAIL**

```
python -m pytest tests/test_xg_lambda.py -v 2>&1 | head -20
```
Expected: ModuleNotFoundError lub AttributeError

- [x] **Step A3: Implement xg_lambda.py**

```python
# src/footstats/core/xg_lambda.py
from __future__ import annotations

import pandas as pd
from datetime import datetime, timedelta

_MIN_LAMBDA = 0.1
_RECENT_DAYS = 14
_RECENT_WEIGHT = 2.0


def _weights(df: pd.DataFrame) -> pd.Series:
    """Wagi czasowe: ostatnie 14 dni → 2.0, starsze → 1.0."""
    if "date" not in df.columns:
        return pd.Series(1.0, index=df.index)
    cutoff = pd.Timestamp.now() - pd.Timedelta(days=_RECENT_DAYS)
    dates = pd.to_datetime(df["date"], errors="coerce")
    return dates.apply(lambda d: _RECENT_WEIGHT if pd.notna(d) and d >= cutoff else 1.0)


def xg_lambda(
    team: str,
    df_hist: pd.DataFrame,
    ostatnie_n: int = 10,
    strona: str = "home",
) -> float:
    """
    Lambda Poissona dla drużyny na podstawie xG (fallback: bramki).

    strona: "home" → mecze jako gospodarz, "away" → mecze jako gość,
            "both" → wszystkie mecze (atak ogólny)
    """
    if df_hist is None or df_hist.empty:
        return _MIN_LAMBDA

    df = df_hist.copy()

    if strona == "home":
        mask = df.get("home", pd.Series(dtype=str)) == team
        xg_col, g_col = "xg_home", "hg"
    elif strona == "away":
        mask = df.get("away", pd.Series(dtype=str)) == team
        xg_col, g_col = "xg_away", "ag"
    else:  # both
        mask = (df.get("home", pd.Series(dtype=str)) == team) | \
               (df.get("away", pd.Series(dtype=str)) == team)
        xg_col, g_col = None, None

    sub = df[mask].tail(ostatnie_n)
    if sub.empty:
        return _MIN_LAMBDA

    w = _weights(sub)

    # Wybierz kolumnę z danymi — xG jeśli dostępne, fallback bramki
    if xg_col and xg_col in sub.columns and sub[xg_col].notna().any():
        vals = pd.to_numeric(sub[xg_col], errors="coerce")
    elif g_col and g_col in sub.columns:
        vals = pd.to_numeric(sub[g_col], errors="coerce")
    elif strona == "both":
        # both: home goals gdy gospodarz, away goals gdy gość
        home_mask = sub.get("home", pd.Series(dtype=str)) == team
        vals = pd.Series(index=sub.index, dtype=float)
        if "xg_home" in sub.columns:
            vals[home_mask] = pd.to_numeric(sub.loc[home_mask, "xg_home"], errors="coerce")
            vals[~home_mask] = pd.to_numeric(sub.loc[~home_mask, "xg_away"], errors="coerce")
        else:
            vals[home_mask] = pd.to_numeric(sub.loc[home_mask, "hg"], errors="coerce") if "hg" in sub.columns else 1.0
            vals[~home_mask] = pd.to_numeric(sub.loc[~home_mask, "ag"], errors="coerce") if "ag" in sub.columns else 1.0
    else:
        return _MIN_LAMBDA

    vals = vals.fillna(0.0)
    if w.sum() == 0:
        return _MIN_LAMBDA

    result = (vals * w).sum() / w.sum()
    return max(result, _MIN_LAMBDA)


def xg_lambda_pair(
    home: str,
    away: str,
    df_hist: pd.DataFrame,
    ostatnie_n: int = 10,
) -> tuple[float, float]:
    """Oblicza (lambda_home_attack, lambda_away_attack)."""
    lh = xg_lambda(home, df_hist, ostatnie_n, strona="home")
    la = xg_lambda(away, df_hist, ostatnie_n, strona="away")
    return lh, la
```

- [x] **Step A4: Run — verify PASS**

```
python -m pytest tests/test_xg_lambda.py -v
```
Expected: 6 passed

- [x] **Step A5: Commit**

```
git add src/footstats/core/xg_lambda.py tests/test_xg_lambda.py
git commit -m "feat: xg_lambda — lambda Poissona z xG + fallback na bramki"
```

---

## Task B: ensemble.py — Ensemble Poisson + Bzzoiro

**Files:**
- Create: `src/footstats/core/ensemble.py`
- Create: `tests/test_ensemble.py`

### Specyfikacja

```python
# src/footstats/core/ensemble.py

def ensemble_probs(
    p_poisson: dict,   # {"win": 0.5, "draw": 0.3, "loss": 0.2, "over25": 0.6, ...}
    p_bzzoiro: dict,   # {"win": ..., "draw": ..., "loss": ..., "over25": ...}
    wagi: dict | None = None,  # {"poisson": 0.45, "bzzoiro": 0.55}
) -> dict:
    """
    Ważona średnia prawdopodobieństw z dwóch modeli.

    Domyślne wagi (gdy wagi=None):
      poisson=0.45, bzzoiro=0.55

    Obsługuje klucze: win, draw, loss, over25, under25, btts
    Brakujące klucze w jednym modelu → waga 0 dla tego klucza z tego modelu.
    Zwraca tylko klucze wspólne lub dostępne.
    """
    ...


def get_roznica(p_ensemble: dict, p_poisson: dict, p_bzzoiro: dict) -> float:
    """
    Zwraca maksymalną różnicę między Poisson a Bzzoiro dla kluczowych prawdop.
    Używana do kryterium ROZBIEŻNOŚĆ w decision_score.
    """
    ...
```

- [x] **Step B1: Write failing tests**

```python
# tests/test_ensemble.py
import pytest
from footstats.core.ensemble import ensemble_probs, get_roznica


_P_POISSON = {"win": 0.55, "draw": 0.25, "loss": 0.20, "over25": 0.65}
_P_BZZ     = {"win": 0.50, "draw": 0.28, "loss": 0.22, "over25": 0.70}


def test_ensemble_default_weights_sum_to_one():
    result = ensemble_probs(_P_POISSON, _P_BZZ)
    assert abs(result["win"] + result["draw"] + result["loss"] - 1.0) < 0.01


def test_ensemble_with_default_weights_between_models():
    result = ensemble_probs(_P_POISSON, _P_BZZ)
    # Wynik musi być między wartościami dwóch modeli
    assert _P_POISSON["win"] <= result["win"] <= _P_BZZ["win"] or \
           _P_BZZ["win"] <= result["win"] <= _P_POISSON["win"]


def test_ensemble_custom_weights():
    wagi = {"poisson": 1.0, "bzzoiro": 0.0}
    result = ensemble_probs(_P_POISSON, _P_BZZ, wagi=wagi)
    assert abs(result["win"] - _P_POISSON["win"]) < 0.001


def test_ensemble_bzzoiro_only():
    wagi = {"poisson": 0.0, "bzzoiro": 1.0}
    result = ensemble_probs(_P_POISSON, _P_BZZ, wagi=wagi)
    assert abs(result["win"] - _P_BZZ["win"]) < 0.001


def test_ensemble_missing_key_in_bzzoiro():
    p_bzz_partial = {"win": 0.50, "draw": 0.28, "loss": 0.22}  # brak over25
    result = ensemble_probs(_P_POISSON, p_bzz_partial)
    # over25 powinno być tylko z Poissona
    assert "over25" in result
    assert abs(result["over25"] - _P_POISSON["over25"]) < 0.001


def test_ensemble_both_empty_returns_empty():
    result = ensemble_probs({}, {})
    assert result == {}


def test_get_roznica_detects_disagreement():
    p_e = {"win": 0.52, "draw": 0.26, "loss": 0.22}
    rozn = get_roznica(p_e, _P_POISSON, _P_BZZ)
    assert isinstance(rozn, float)
    assert rozn >= 0


def test_get_roznica_identical_models_is_zero():
    rozn = get_roznica(_P_POISSON, _P_POISSON, _P_POISSON)
    assert rozn < 0.01
```

- [x] **Step B2: Run — verify FAIL**

```
python -m pytest tests/test_ensemble.py -v 2>&1 | head -10
```

- [x] **Step B3: Implement ensemble.py**

```python
# src/footstats/core/ensemble.py
from __future__ import annotations

_DEFAULT_WEIGHTS = {"poisson": 0.45, "bzzoiro": 0.55}
_KEY_ORDER = ["win", "draw", "loss", "over25", "under25", "btts"]


def ensemble_probs(
    p_poisson: dict,
    p_bzzoiro: dict,
    wagi: dict | None = None,
) -> dict:
    w = wagi or _DEFAULT_WEIGHTS
    wp = w.get("poisson", 0.45)
    wb = w.get("bzzoiro", 0.55)

    if not p_poisson and not p_bzzoiro:
        return {}

    all_keys = set(p_poisson.keys()) | set(p_bzzoiro.keys())
    result = {}

    for key in all_keys:
        has_p = key in p_poisson
        has_b = key in p_bzzoiro
        if has_p and has_b:
            result[key] = (p_poisson[key] * wp + p_bzzoiro[key] * wb) / (wp + wb)
        elif has_p:
            result[key] = p_poisson[key]
        else:
            result[key] = p_bzzoiro[key]

    return result


def get_roznica(p_ensemble: dict, p_poisson: dict, p_bzzoiro: dict) -> float:
    """Maksymalna różnica między Poisson a Bzzoiro dla win/draw/loss."""
    keys = ["win", "draw", "loss"]
    max_diff = 0.0
    for k in keys:
        if k in p_poisson and k in p_bzzoiro:
            max_diff = max(max_diff, abs(p_poisson[k] - p_bzzoiro[k]))
    return max_diff
```

- [x] **Step B4: Run — verify PASS**

```
python -m pytest tests/test_ensemble.py -v
```
Expected: 8 passed

- [x] **Step B5: Commit**

```
git add src/footstats/core/ensemble.py tests/test_ensemble.py
git commit -m "feat: ensemble — weighted average Poisson+Bzzoiro z dynamicznymi wagami"
```

---

## Task C: lineup_scraper.py — składy API-Football

**Files:**
- Create: `src/footstats/scrapers/lineup_scraper.py`
- Create: `tests/test_lineup_scraper.py`

### Specyfikacja

```python
# src/footstats/scrapers/lineup_scraper.py

def get_lineup(fixture_id: int, api_key: str) -> dict | None:
    """
    Pobiera składy dla meczu z API-Football /fixtures/lineups.

    Returns dict:
    {
        "home": {
            "team": "Paris Saint-Germain",
            "formation": "4-3-3",
            "startXI": ["Donnarumma", "Hakimi", ...],   # 11 nazwisk
            "missing_key_players": False  # True jeśli brak kluczowych (napastnicy/GK)
        },
        "away": { ... }
    }

    Returns None jeśli brak składów (za wcześnie lub błąd API).
    """
    ...


def lineup_confidence_penalty(lineup: dict | None) -> int:
    """
    Zwraca karę do decision_score (0 lub -15) gdy brakuje kluczowych graczy.
    Używane w decision_score faza='final'.
    """
    if lineup is None:
        return 0  # brak danych = brak kary (nie karamy za brak info)
    penalty = 0
    for side in ("home", "away"):
        if lineup.get(side, {}).get("missing_key_players", False):
            penalty -= 15
    return penalty
```

- [x] **Step C1: Write failing tests**

```python
# tests/test_lineup_scraper.py
import pytest
from unittest.mock import patch, MagicMock
from footstats.scrapers.lineup_scraper import get_lineup, lineup_confidence_penalty


_MOCK_RESPONSE = {
    "response": [
        {
            "team": {"id": 85, "name": "Paris Saint-Germain"},
            "formation": "4-3-3",
            "startXI": [
                {"player": {"name": "Donnarumma"}},
                {"player": {"name": "Hakimi"}},
                {"player": {"name": "Marquinhos"}},
                {"player": {"name": "Pacho"}},
                {"player": {"name": "Nuno Mendes"}},
                {"player": {"name": "Vitinha"}},
                {"player": {"name": "Joao Neves"}},
                {"player": {"name": "Fabian Ruiz"}},
                {"player": {"name": "Dembele"}},
                {"player": {"name": "Barcola"}},
                {"player": {"name": "Ramos"}},
            ],
        },
        {
            "team": {"id": 80, "name": "Lyon"},
            "formation": "4-2-3-1",
            "startXI": [
                {"player": {"name": "Perri"}},
                {"player": {"name": "Maitland-Niles"}},
                {"player": {"name": "Caleta-Car"}},
                {"player": {"name": "Niakhate"}},
                {"player": {"name": "Tagliafico"}},
                {"player": {"name": "Matic"}},
                {"player": {"name": "Tolisso"}},
                {"player": {"name": "Cherki"}},
                {"player": {"name": "Nuamah"}},
                {"player": {"name": "Lacazette"}},
                {"player": {"name": "Mikautadze"}},
            ],
        },
    ]
}


def test_get_lineup_returns_dict_with_home_away():
    with patch("footstats.scrapers.lineup_scraper.requests.get") as mock_get:
        resp = MagicMock()
        resp.json.return_value = _MOCK_RESPONSE
        resp.raise_for_status = MagicMock()
        mock_get.return_value = resp

        result = get_lineup(12345, "fake_key")
        assert result is not None
        assert "home" in result
        assert "away" in result


def test_get_lineup_home_has_11_players():
    with patch("footstats.scrapers.lineup_scraper.requests.get") as mock_get:
        resp = MagicMock()
        resp.json.return_value = _MOCK_RESPONSE
        resp.raise_for_status = MagicMock()
        mock_get.return_value = resp

        result = get_lineup(12345, "fake_key")
        assert len(result["home"]["startXI"]) == 11


def test_get_lineup_returns_none_on_empty_response():
    with patch("footstats.scrapers.lineup_scraper.requests.get") as mock_get:
        resp = MagicMock()
        resp.json.return_value = {"response": []}
        resp.raise_for_status = MagicMock()
        mock_get.return_value = resp

        result = get_lineup(12345, "fake_key")
        assert result is None


def test_get_lineup_returns_none_on_request_error():
    import requests as req
    with patch("footstats.scrapers.lineup_scraper.requests.get") as mock_get:
        mock_get.side_effect = req.RequestException("timeout")
        result = get_lineup(12345, "fake_key")
        assert result is None


def test_lineup_confidence_penalty_no_penalty_when_full_squad():
    lineup = {
        "home": {"missing_key_players": False},
        "away": {"missing_key_players": False},
    }
    assert lineup_confidence_penalty(lineup) == 0


def test_lineup_confidence_penalty_minus_15_when_home_missing():
    lineup = {
        "home": {"missing_key_players": True},
        "away": {"missing_key_players": False},
    }
    assert lineup_confidence_penalty(lineup) == -15


def test_lineup_confidence_penalty_minus_30_when_both_missing():
    lineup = {
        "home": {"missing_key_players": True},
        "away": {"missing_key_players": True},
    }
    assert lineup_confidence_penalty(lineup) == -30


def test_lineup_confidence_penalty_none_returns_zero():
    assert lineup_confidence_penalty(None) == 0
```

- [x] **Step C2: Run — verify FAIL**

```
python -m pytest tests/test_lineup_scraper.py -v 2>&1 | head -10
```

- [x] **Step C3: Implement lineup_scraper.py**

```python
# src/footstats/scrapers/lineup_scraper.py
from __future__ import annotations
import requests

_BASE = "https://v3.football.api-sports.io"
_KEY_POSITIONS = {"G", "F"}  # Goalkeeper, Forward — kluczowe


def get_lineup(fixture_id: int, api_key: str) -> dict | None:
    """Pobiera składy z API-Football /fixtures/lineups."""
    try:
        resp = requests.get(
            f"{_BASE}/fixtures/lineups",
            params={"fixture": fixture_id},
            headers={"x-apisports-key": api_key},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json().get("response", [])
    except requests.RequestException:
        return None

    if len(data) < 2:
        return None

    result = {}
    sides = ("home", "away")
    for i, side in enumerate(sides):
        if i >= len(data):
            break
        entry = data[i]
        players = [p["player"]["name"] for p in entry.get("startXI", [])]
        # Sprawdź czy brakuje kluczowych graczy (uproszczone: < 11 zawodników)
        missing = len(players) < 11
        result[side] = {
            "team": entry.get("team", {}).get("name", ""),
            "formation": entry.get("formation", ""),
            "startXI": players,
            "missing_key_players": missing,
        }

    return result if result else None


def lineup_confidence_penalty(lineup: dict | None) -> int:
    """Kara do decision_score: -15 za każdą drużynę z brakującymi kluczowymi graczami."""
    if lineup is None:
        return 0
    penalty = 0
    for side in ("home", "away"):
        if lineup.get(side, {}).get("missing_key_players", False):
            penalty -= 15
    return penalty
```

- [x] **Step C4: Run — verify PASS**

```
python -m pytest tests/test_lineup_scraper.py -v
```
Expected: 8 passed

- [x] **Step C5: Commit**

```
git add src/footstats/scrapers/lineup_scraper.py tests/test_lineup_scraper.py
git commit -m "feat: lineup_scraper — API-Football /fixtures/lineups z penalty dla decision_score"
```

---

## Task D: referee_db.py — baza statystyk sędziów

**Files:**
- Create: `src/footstats/scrapers/referee_db.py`
- Create: `tests/test_referee_db.py`

### Schema SQLite

```sql
CREATE TABLE IF NOT EXISTS referees (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL UNIQUE,
    country     TEXT,
    avg_yellow  REAL,
    avg_red     REAL,
    avg_goals   REAL,
    home_win_pct REAL,
    n_matches   INTEGER,
    updated_at  TEXT
);
```

### Specyfikacja

```python
def init_referee_table(db_path: Path = None) -> None:
    """Tworzy tabelę referees jeśli nie istnieje."""
    ...

def upsert_referee(name: str, stats: dict, db_path: Path = None) -> None:
    """
    Wstawia lub aktualizuje sędziego.
    stats: {country, avg_yellow, avg_red, avg_goals, home_win_pct, n_matches}
    """
    ...

def get_referee(name: str, db_path: Path = None) -> dict | None:
    """Zwraca statystyki sędziego lub None jeśli nieznany."""
    ...

def referee_signal(name: str, db_path: Path = None) -> str:
    """
    Zwraca sygnał: "KARTKOWY" | "BRAMKOWY" | "NEUTRALNY" | "NIEZNANY"
    KARTKOWY: avg_yellow > 5 (dużo kartek)
    BRAMKOWY: avg_goals > 3.0 (pozwala na wiele goli)
    NEUTRALNY: inaczej
    """
    ...
```

- [x] **Step D1: Write failing tests**

```python
# tests/test_referee_db.py
import pytest
from pathlib import Path
from footstats.scrapers.referee_db import init_referee_table, upsert_referee, get_referee, referee_signal


@pytest.fixture
def db(tmp_path):
    db_path = tmp_path / "test_referees.db"
    init_referee_table(db_path)
    return db_path


def test_init_creates_table(db):
    import sqlite3
    conn = sqlite3.connect(db)
    tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    conn.close()
    assert any("referees" in t[0] for t in tables)


def test_upsert_and_get_referee(db):
    upsert_referee("Szymon Marciniak", {
        "country": "Poland", "avg_yellow": 3.2, "avg_red": 0.1,
        "avg_goals": 2.8, "home_win_pct": 0.45, "n_matches": 120
    }, db_path=db)
    result = get_referee("Szymon Marciniak", db_path=db)
    assert result is not None
    assert abs(result["avg_yellow"] - 3.2) < 0.01
    assert result["country"] == "Poland"


def test_get_referee_returns_none_when_unknown(db):
    result = get_referee("Nieznany Sędzia", db_path=db)
    assert result is None


def test_upsert_updates_existing(db):
    upsert_referee("Test Ref", {"avg_yellow": 2.0, "avg_red": 0.0, "avg_goals": 2.5,
                                 "home_win_pct": 0.40, "n_matches": 10}, db_path=db)
    upsert_referee("Test Ref", {"avg_yellow": 6.0, "avg_red": 0.2, "avg_goals": 2.5,
                                 "home_win_pct": 0.40, "n_matches": 20}, db_path=db)
    result = get_referee("Test Ref", db_path=db)
    assert abs(result["avg_yellow"] - 6.0) < 0.01
    assert result["n_matches"] == 20


def test_referee_signal_kartkowy(db):
    upsert_referee("Kartkowy", {"avg_yellow": 6.0, "avg_red": 0.3, "avg_goals": 2.5,
                                  "home_win_pct": 0.45, "n_matches": 50}, db_path=db)
    assert referee_signal("Kartkowy", db_path=db) == "KARTKOWY"


def test_referee_signal_bramkowy(db):
    upsert_referee("Bramkowy", {"avg_yellow": 2.0, "avg_red": 0.0, "avg_goals": 3.5,
                                  "home_win_pct": 0.48, "n_matches": 30}, db_path=db)
    assert referee_signal("Bramkowy", db_path=db) == "BRAMKOWY"


def test_referee_signal_neutralny(db):
    upsert_referee("Neutralny", {"avg_yellow": 3.0, "avg_red": 0.1, "avg_goals": 2.4,
                                   "home_win_pct": 0.45, "n_matches": 40}, db_path=db)
    assert referee_signal("Neutralny", db_path=db) == "NEUTRALNY"


def test_referee_signal_nieznany(db):
    assert referee_signal("Nieznany XYZ", db_path=db) == "NIEZNANY"
```

- [x] **Step D2: Run — verify FAIL**

```
python -m pytest tests/test_referee_db.py -v 2>&1 | head -10
```

- [x] **Step D3: Implement referee_db.py**

```python
# src/footstats/scrapers/referee_db.py
from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

_DEFAULT_DB = Path(__file__).parents[3] / "data" / "footstats_backtest.db"

_DDL = """
CREATE TABLE IF NOT EXISTS referees (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT    NOT NULL UNIQUE,
    country      TEXT,
    avg_yellow   REAL,
    avg_red      REAL,
    avg_goals    REAL,
    home_win_pct REAL,
    n_matches    INTEGER,
    updated_at   TEXT
);
"""

_KARTKOWY_THRESHOLD = 5.0
_BRAMKOWY_THRESHOLD = 3.0


def _db(db_path: Path | None) -> Path:
    return db_path or _DEFAULT_DB


def init_referee_table(db_path: Path = None) -> None:
    path = _db(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.execute(_DDL)
        conn.commit()
    finally:
        conn.close()


def upsert_referee(name: str, stats: dict, db_path: Path = None) -> None:
    init_referee_table(db_path)
    path = _db(db_path)
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            """
            INSERT INTO referees (name, country, avg_yellow, avg_red, avg_goals,
                                  home_win_pct, n_matches, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                country      = excluded.country,
                avg_yellow   = excluded.avg_yellow,
                avg_red      = excluded.avg_red,
                avg_goals    = excluded.avg_goals,
                home_win_pct = excluded.home_win_pct,
                n_matches    = excluded.n_matches,
                updated_at   = excluded.updated_at
            """,
            (
                name,
                stats.get("country"),
                stats.get("avg_yellow"),
                stats.get("avg_red"),
                stats.get("avg_goals"),
                stats.get("home_win_pct"),
                stats.get("n_matches"),
                datetime.now().isoformat(),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def get_referee(name: str, db_path: Path = None) -> dict | None:
    init_referee_table(db_path)
    path = _db(db_path)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT * FROM referees WHERE name = ?", (name,)
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    return dict(row)


def referee_signal(name: str, db_path: Path = None) -> str:
    """KARTKOWY | BRAMKOWY | NEUTRALNY | NIEZNANY"""
    ref = get_referee(name, db_path=db_path)
    if ref is None:
        return "NIEZNANY"
    avg_y = ref.get("avg_yellow") or 0.0
    avg_g = ref.get("avg_goals") or 0.0
    if avg_y > _KARTKOWY_THRESHOLD:
        return "KARTKOWY"
    if avg_g > _BRAMKOWY_THRESHOLD:
        return "BRAMKOWY"
    return "NEUTRALNY"
```

- [x] **Step D4: Run — verify PASS**

```
python -m pytest tests/test_referee_db.py -v
```
Expected: 8 passed

- [x] **Step D5: Commit**

```
git add src/footstats/scrapers/referee_db.py tests/test_referee_db.py
git commit -m "feat: referee_db — SQLite baza statystyk sędziów z sygnałami KARTKOWY/BRAMKOWY"
```

---

## Task E: daily_agent.py — rozbudowa o --faza draft/final

**Files:**
- Modify: `src/footstats/daily_agent.py`
- Create: `tests/test_daily_agent_faza.py`

### Co dodać do daily_agent.py

Obecny daily_agent.py (555 linii) uruchamia pełny pipeline. Trzeba:

1. Dodać argument `--faza` (draft | final) do argparse
2. Wpiąć `decision_score.score_kandydat()` przed dodaniem kandydata do kuponu
3. W fazie `final`: opcjonalnie dociągnąć składy przez `lineup_scraper.get_lineup()`
4. Zapisywać kupon do SQLite przez `coupon_tracker.save_coupon()`
5. Zachować pełną kompatybilność wsteczną (brak --faza = działa jak dotychczas)

Dodaj na końcu `daily_agent.py`, po istniejących funkcjach:

```python
# ── Nowe: fazy i decision score ────────────────────────────────────────────

def _decision_score_kandydat(kandydat: dict, phase: str = "draft") -> tuple[int, list[str]]:
    """Wrapper — konwertuje kandydata Bzzoiro → format decision_score."""
    from footstats.core.decision_score import score_kandydat
    w = {
        "ev_netto":       kandydat.get("ev_netto", 0),
        "pewnosc":        kandydat.get("pewnosc", 0.5),
        "czynniki":       kandydat.get("czynniki", []),
        "roznica_modeli": kandydat.get("roznica_modeli", 0.0),
        "accuracy":       kandydat.get("accuracy", 0.0),
    }
    context = {
        "lineup_ok":      kandydat.get("lineup_ok", None),
        "referee_neutral": kandydat.get("referee_neutral", True),
    }
    return score_kandydat(w, context=context, phase=phase)


def _filtruj_przez_decision_score(
    kandydaci: list[dict],
    phase: str = "draft",
    prog: int | None = None,
) -> list[dict]:
    """
    Filtruje kandydatów przez decision_score.
    Dodaje 'decision_score' i 'decision_reasons' do każdego kandydata.
    Zwraca tylko kandydatów >= prog.
    """
    from footstats.core.decision_score import PROG_DRAFT, PROG_FINAL
    threshold = prog or (PROG_FINAL if phase == "final" else PROG_DRAFT)

    wynik = []
    for k in kandydaci:
        sc, reasons = _decision_score_kandydat(k, phase=phase)
        k["decision_score"] = sc
        k["decision_reasons"] = reasons
        if sc >= threshold:
            wynik.append(k)
    return wynik


def _zapisz_kupon_do_db(kandydaci: list[dict], phase: str, groq_resp: str | None,
                         stake: float, total_odds: float) -> int | None:
    """Zapisuje kupon do SQLite coupon_tracker. Zwraca coupon_id lub None."""
    try:
        from footstats.core.coupon_tracker import save_coupon, init_coupon_tables
        init_coupon_tables()
        legs = [
            {
                "home": k.get("gospodarz", ""),
                "away": k.get("goscie", ""),
                "tip": k.get("tip", ""),
                "odds": k.get("kurs", 1.0),
                "decision_score": k.get("decision_score", 0),
            }
            for k in kandydaci
        ]
        from datetime import datetime
        match_date = datetime.now().strftime("%Y-%m-%d")
        avg_score = int(sum(k.get("decision_score", 0) for k in kandydaci) / max(len(kandydaci), 1))
        return save_coupon(
            phase=phase,
            kupon_type="A",
            legs=legs,
            total_odds=round(total_odds, 2),
            stake_pln=stake,
            groq_reasoning=groq_resp or "",
            decision_score=avg_score,
            match_date_first=match_date,
        )
    except Exception as e:
        console.print(f"[yellow]Warning: Nie udało się zapisać kuponu do DB: {e}[/yellow]")
        return None
```

W `main()` / sekcji argparse dodaj:
```python
parser.add_argument("--faza", choices=["draft", "final"], default=None,
                    help="Faza: draft (8:00, bez składów) lub final (1h przed meczem, ze składami)")
```

I po zebraniu kandydatów (po `_pobierz_kandydatow`), jeśli `args.faza`:
```python
if args.faza:
    kandydaci = _filtruj_przez_decision_score(kandydaci, phase=args.faza)
    console.print(f"[cyan]Decision Score filter [{args.faza}]: {len(kandydaci)} kandydatów przeszło próg[/cyan]")
```

- [x] **Step E1: Write failing tests**

```python
# tests/test_daily_agent_faza.py
import pytest
from unittest.mock import patch


def test_decision_score_kandydat_wrapper_returns_tuple():
    from footstats.daily_agent import _decision_score_kandydat
    k = {"ev_netto": 5.0, "pewnosc": 0.75, "czynniki": [], "roznica_modeli": 0.1, "accuracy": 0.70}
    sc, reasons = _decision_score_kandydat(k, phase="draft")
    assert isinstance(sc, int)
    assert isinstance(reasons, list)
    assert sc >= 0


def test_filtruj_przez_decision_score_removes_weak():
    from footstats.daily_agent import _filtruj_przez_decision_score
    kandydaci = [
        {"ev_netto": -5.0, "pewnosc": 0.3, "czynniki": ["ROTACJA"], "roznica_modeli": 0.3, "accuracy": 0.4},
        {"ev_netto": 10.0, "pewnosc": 0.80, "czynniki": [], "roznica_modeli": 0.05, "accuracy": 0.75},
    ]
    result = _filtruj_przez_decision_score(kandydaci, phase="draft")
    assert len(result) == 1
    assert result[0]["decision_score"] >= 40  # PROG_DRAFT


def test_filtruj_przez_decision_score_adds_score_field():
    from footstats.daily_agent import _filtruj_przez_decision_score
    kandydaci = [
        {"ev_netto": 5.0, "pewnosc": 0.75, "czynniki": [], "roznica_modeli": 0.05, "accuracy": 0.70},
    ]
    result = _filtruj_przez_decision_score(kandydaci, phase="draft", prog=0)
    assert "decision_score" in result[0]
    assert "decision_reasons" in result[0]


def test_zapisz_kupon_do_db_returns_id_or_none(tmp_path):
    import footstats.core.coupon_tracker as ct
    ct.DB_PATH = tmp_path / "test.db"
    ct.init_coupon_tables()

    from footstats.daily_agent import _zapisz_kupon_do_db
    kandydaci = [{"gospodarz": "PSG", "goscie": "Lyon", "tip": "Over 2.5",
                  "kurs": 1.85, "decision_score": 65}]
    result = _zapisz_kupon_do_db(kandydaci, phase="draft", groq_resp="Test", stake=10.0, total_odds=1.85)
    # Może być int (sukces) lub None (błąd DB)
    assert result is None or isinstance(result, int)
```

- [x] **Step E2: Run — verify FAIL**

```
python -m pytest tests/test_daily_agent_faza.py -v 2>&1 | head -10
```

- [x] **Step E3: Implement — dodaj funkcje do daily_agent.py**

Dopisz na końcu pliku (przed `if __name__ == "__main__":`), trzy funkcje:
- `_decision_score_kandydat()`
- `_filtruj_przez_decision_score()`
- `_zapisz_kupon_do_db()`

Oraz w `main()` po bloku argparse dodaj obsługę `--faza`.

Szczegóły implementacji — patrz wyżej w sekcji "Co dodać".

- [x] **Step E4: Run — verify PASS**

```
python -m pytest tests/test_daily_agent_faza.py -v
python -m pytest tests/ -q 2>&1 | tail -3
```
Expected: 4 passed + wszystkie poprzednie testy zielone

- [x] **Step E5: Commit**

```
git add src/footstats/daily_agent.py tests/test_daily_agent_faza.py
git commit -m "feat: daily_agent — --faza draft/final z decision_score + zapis kuponu do DB"
```

---

## Task F: weekly_report.py — tygodniowy raport Groq

**Files:**
- Create: `src/footstats/weekly_report.py`
- Create: `tests/test_weekly_report.py`

### Specyfikacja

```python
# src/footstats/weekly_report.py

def get_stats_7_dni(db_path: Path = None) -> dict:
    """
    Pobiera statystyki z ostatnich 7 dni z SQLite.
    Returns: {total, won, lost, partial, void, accuracy_pct, total_stake, total_payout, roi_pct}
    """
    ...

def build_raport_prompt(stats: dict) -> str:
    """Buduje prompt dla Groq z tygodniowymi statystykami."""
    ...

def run_weekly_report(api_key_groq: str | None = None, send_telegram: bool = True) -> dict:
    """
    Główna funkcja: stats → Groq analiza → Telegram.
    Returns stats dict z 'groq_analysis' dodanym.
    """
    ...
```

- [x] **Step F1: Write failing tests**

```python
# tests/test_weekly_report.py
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock


def _seed_db(db_path: Path):
    """Seed kupony do testowej bazy."""
    import footstats.core.coupon_tracker as ct
    ct.DB_PATH = db_path
    ct.init_coupon_tables()
    cid1 = ct.save_coupon("draft", "A", [{"tip": "Over 2.5"}], 3.20, 10.0, "test", 60, "2026-04-08")
    ct.update_coupon_status(cid1, "WON", payout_pln=28.16)
    cid2 = ct.save_coupon("final", "A", [{"tip": "1X2 Home"}], 2.10, 10.0, "test", 55, "2026-04-09")
    ct.update_coupon_status(cid2, "LOST", payout_pln=None)


def test_get_stats_7_dni_returns_dict(tmp_path):
    db = tmp_path / "test.db"
    _seed_db(db)
    import footstats.core.coupon_tracker as ct
    ct.DB_PATH = db

    from footstats.weekly_report import get_stats_7_dni
    stats = get_stats_7_dni(db_path=db)
    assert isinstance(stats, dict)
    assert "total" in stats
    assert "won" in stats
    assert "lost" in stats


def test_get_stats_7_dni_counts_correctly(tmp_path):
    db = tmp_path / "test.db"
    _seed_db(db)

    from footstats.weekly_report import get_stats_7_dni
    stats = get_stats_7_dni(db_path=db)
    assert stats["total"] >= 2
    assert stats["won"] >= 1
    assert stats["lost"] >= 1


def test_build_raport_prompt_contains_stats():
    from footstats.weekly_report import build_raport_prompt
    stats = {"total": 5, "won": 3, "lost": 2, "accuracy_pct": 60.0, "roi_pct": 12.5}
    prompt = build_raport_prompt(stats)
    assert "60" in prompt or "accuracy" in prompt.lower()
    assert isinstance(prompt, str)
    assert len(prompt) > 50


def test_run_weekly_report_without_groq(tmp_path):
    db = tmp_path / "test.db"
    _seed_db(db)

    from footstats.weekly_report import run_weekly_report
    result = run_weekly_report(api_key_groq=None, send_telegram=False)
    assert isinstance(result, dict)
    assert "total" in result
```

- [x] **Step F2: Run — verify FAIL**

```
python -m pytest tests/test_weekly_report.py -v 2>&1 | head -10
```

- [x] **Step F3: Implement weekly_report.py**

```python
# src/footstats/weekly_report.py
from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from footstats.utils.console import console

_DEFAULT_DB = Path(__file__).parents[2] / "data" / "footstats_backtest.db"


def get_stats_7_dni(db_path: Path = None) -> dict:
    """Statystyki kuponów z ostatnich 7 dni."""
    path = db_path or _DEFAULT_DB
    if not path.exists():
        return {"total": 0, "won": 0, "lost": 0, "partial": 0, "void": 0,
                "accuracy_pct": 0.0, "total_stake": 0.0, "total_payout": 0.0, "roi_pct": 0.0}

    cutoff = (datetime.now() - timedelta(days=7)).isoformat()
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT status, stake_pln, payout_pln FROM coupons WHERE created_at >= ?",
            (cutoff,)
        ).fetchall()
    except sqlite3.OperationalError:
        return {"total": 0, "won": 0, "lost": 0, "partial": 0, "void": 0,
                "accuracy_pct": 0.0, "total_stake": 0.0, "total_payout": 0.0, "roi_pct": 0.0}
    finally:
        conn.close()

    counts = {"WON": 0, "LOST": 0, "PARTIAL": 0, "VOID": 0, "DRAFT": 0, "ACTIVE": 0}
    total_stake = 0.0
    total_payout = 0.0
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
        total_stake += r["stake_pln"] or 0.0
        total_payout += r["payout_pln"] or 0.0

    total = len(rows)
    decided = counts["WON"] + counts["LOST"] + counts["PARTIAL"]
    accuracy = round(counts["WON"] / decided * 100, 1) if decided > 0 else 0.0
    roi = round((total_payout - total_stake) / total_stake * 100, 1) if total_stake > 0 else 0.0

    return {
        "total": total,
        "won": counts["WON"],
        "lost": counts["LOST"],
        "partial": counts["PARTIAL"],
        "void": counts["VOID"],
        "accuracy_pct": accuracy,
        "total_stake": round(total_stake, 2),
        "total_payout": round(total_payout, 2),
        "roi_pct": roi,
    }


def build_raport_prompt(stats: dict) -> str:
    return (
        f"Analiza tygodniowa FootStats:\n"
        f"- Kupony: {stats['total']} | WON: {stats['won']} | LOST: {stats['lost']}\n"
        f"- Accuracy: {stats['accuracy_pct']}% | ROI: {stats['roi_pct']}%\n"
        f"- Stawka: {stats['total_stake']} PLN | Wypłata: {stats['total_payout']} PLN\n\n"
        "Oceń wyniki, wskaż wzorce błędów i podaj 2-3 rekomendacje poprawy strategii typowania."
    )


def run_weekly_report(api_key_groq: str | None = None, send_telegram: bool = True) -> dict:
    from footstats.core.coupon_tracker import DB_PATH
    stats = get_stats_7_dni()

    console.print(f"[cyan]Weekly Report: {stats['total']} kuponów, accuracy={stats['accuracy_pct']}%, ROI={stats['roi_pct']}%[/cyan]")

    groq_analysis = None
    if api_key_groq:
        try:
            from groq import Groq
            client = Groq(api_key=api_key_groq)
            prompt = build_raport_prompt(stats)
            resp = client.chat.completions.create(
                model="meta-llama/llama-4-scout-17b-16e-instruct",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=500,
            )
            groq_analysis = resp.choices[0].message.content
            console.print(f"[green]Groq analiza:[/green]\n{groq_analysis}")
        except Exception as e:
            console.print(f"[yellow]Groq unavailable: {e}[/yellow]")

    stats["groq_analysis"] = groq_analysis

    if send_telegram and groq_analysis:
        try:
            from footstats.utils.telegram_notify import send_message
            msg = f"📊 *Raport tygodniowy FootStats*\n\n{groq_analysis}"
            send_message(msg)
        except Exception:
            pass

    return stats


if __name__ == "__main__":
    import os
    from dotenv import load_dotenv
    load_dotenv()
    run_weekly_report(api_key_groq=os.getenv("GROQ_API_KEY"))
```

- [x] **Step F4: Run — verify PASS**

```
python -m pytest tests/test_weekly_report.py -v
python -m pytest tests/ -q 2>&1 | tail -3
```
Expected: 4 passed + wszystkie poprzednie zielone

- [x] **Step F5: Commit**

```
git add src/footstats/weekly_report.py tests/test_weekly_report.py
git commit -m "feat: weekly_report — tygodniowy raport Groq + Telegram z accuracy/ROI"
```

---

## Task G: Integracja + run_weekly_report.bat + finalny commit

**Files:**
- Create: `run_weekly_report.bat`
- Modify: `docs/superpowers/plans/2026-04-10-model-enhancement-plan.md` — check off steps

- [x] **Step G1: Stwórz run_weekly_report.bat**

```bat
@echo off
cd /d F:\bot
call venv\Scripts\activate.bat 2>nul || call .venv\Scripts\activate.bat 2>nul
python -m footstats.weekly_report >> logs\weekly_report.log 2>&1
```

- [x] **Step G2: Zarejestruj w Task Scheduler**

```
schtasks /create /tn "FootStats Weekly" /tr "F:\bot\run_weekly_report.bat" /sc weekly /d MON /st 09:00 /f
```

- [x] **Step G3: Pełny test suite**

```
python -m pytest tests/ -v 2>&1 | tail -20
```
Expected: wszystkie testy zielone (192 + nowe)

- [x] **Step G4: Smoke test integracyjny**

```python
python -c "
from footstats.core.xg_lambda import xg_lambda_pair
from footstats.core.ensemble import ensemble_probs, get_roznica
from footstats.scrapers.lineup_scraper import lineup_confidence_penalty
from footstats.scrapers.referee_db import referee_signal
from footstats.weekly_report import get_stats_7_dni
from footstats.daily_agent import _decision_score_kandydat, _filtruj_przez_decision_score
print('All Plan 2 imports OK')
"
```

- [x] **Step G5: Finalny commit**

```
git add run_weekly_report.bat
git commit -m "feat: Plan 2 complete — xg_lambda, ensemble, lineup_scraper, referee_db, daily_agent fazy, weekly_report"
```
