"""Fixtures wspólne dla wszystkich testów FootStats."""
import pandas as pd
import pytest
from datetime import datetime, timedelta


@pytest.fixture
def df_mecze_minimal():
    """Minimalne DataFrame meczów do testów (kolumny polskie: gospodarz/goscie/gole_g/gole_a)."""
    today = datetime.now()
    mecze = []
    druzyny = ["Arsenal", "Chelsea", "Liverpool", "Man Utd"]
    for i in range(20):
        g = druzyny[i % 4]
        a = druzyny[(i + 1) % 4]
        if g == a:
            a = druzyny[(i + 2) % 4]
        mecze.append({
            "gospodarz": g,
            "goscie": a,
            "gole_g": (i % 4),
            "gole_a": (i % 3),
            "data": (today - timedelta(days=i * 7)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "faza": "REGULAR_SEASON",
        })
    return pd.DataFrame(mecze)


@pytest.fixture
def klucze_env():
    """Przykładowe klucze API (fake)."""
    return {
        "FOOTBALL_API_KEY": "test_fdb_key",
        "APISPORTS_KEY": "test_af_key",
        "BZZOIRO_KEY": "test_bzz_key",
    }
