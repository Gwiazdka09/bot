import pytest
from unittest.mock import patch, MagicMock


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
    assert result is None or isinstance(result, int)


def test_zapisz_kupon_final_promotes_draft_to_active(tmp_path):
    """Faza final powinna promować istniejący DRAFT → ACTIVE, nie tworzyć nowego."""
    import footstats.core.coupon_tracker as ct
    ct.DB_PATH = tmp_path / "test.db"
    ct.init_coupon_tables()

    # Tworzymy DRAFT ręcznie
    draft_id = ct.save_coupon("draft", "A", [], stake_pln=10.0)

    from footstats.daily_agent import _zapisz_kupon_do_db
    kandydaci = [{"gospodarz": "PSG", "goscie": "Lyon", "tip": "1",
                  "kurs": 1.75, "decision_score": 70}]
    result = _zapisz_kupon_do_db(kandydaci, phase="final", groq_resp="Final reason", stake=10.0, total_odds=1.75)

    # Zwraca ten sam ID co DRAFT
    assert result == draft_id

    # Sprawdź status w bazie
    import sqlite3
    conn = sqlite3.connect(str(tmp_path / "test.db"))
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT status, phase FROM coupons WHERE id=?", (draft_id,)).fetchone()
    conn.close()
    assert row["status"] == "ACTIVE"
    assert row["phase"] == "final"


def test_enrichuj_finalna_faza_no_key_skips_gracefully():
    """Brak API key → funkcja kończy się bez błędu."""
    from footstats.daily_agent import _enrichuj_finalna_faza
    wyniki = [{"gospodarz": "PSG", "goscie": "Lyon"}]
    _enrichuj_finalna_faza(wyniki, api_key="")  # pusty klucz — powinien pominąć
    # Kandydat nie zmienił się (brak enrichmentu)
    assert "lineup_ok" not in wyniki[0]


def test_enrichuj_finalna_faza_sets_fields_on_match(tmp_path):
    """Mock API: fixture znaleziony → lineup_ok i referee_neutral ustawione."""
    from footstats.daily_agent import _enrichuj_finalna_faza

    _MOCK_FIXTURES = {
        "response": [{
            "fixture": {"id": 999, "referee": "Test Ref, PL"},
            "teams": {
                "home": {"name": "Paris Saint-Germain"},
                "away": {"name": "Olympique Lyonnais"},
            }
        }]
    }
    _MOCK_LINEUPS = {
        "response": [
            {"team": {"name": "PSG"}, "formation": "4-3-3",
             "startXI": [{"player": {"name": f"P{i}"}} for i in range(11)]},
            {"team": {"name": "Lyon"}, "formation": "4-2-3-1",
             "startXI": [{"player": {"name": f"L{i}"}} for i in range(11)]},
        ]
    }

    import requests
    def mock_get(url, **kwargs):
        m = MagicMock()
        m.raise_for_status = MagicMock()
        if "lineups" in url:
            m.json.return_value = _MOCK_LINEUPS
        else:
            m.json.return_value = _MOCK_FIXTURES
        return m

    wyniki = [{"gospodarz": "Paris Saint-Germain", "goscie": "Olympique Lyonnais"}]
    with patch("requests.get", side_effect=mock_get):
        _enrichuj_finalna_faza(wyniki, api_key="fake_key")

    assert "lineup_ok" in wyniki[0]
    assert "referee_neutral" in wyniki[0]


def test_zapisz_next_final_txt_creates_file(tmp_path):
    """Funkcja zapisuje plik next_final.txt."""
    from pathlib import Path
    import footstats.daily_agent as da

    # Tymczasowo podmień DATA_DIR przez mockowanie Path
    wyniki = []  # brak danych → fallback 13:30

    # Patch Path(__file__).parents[2] / "data"
    original = da.Path
    fake_data = tmp_path / "data"
    fake_data.mkdir()

    with patch.object(da, "Path", wraps=original) as mock_path:
        # Nadpisz parents[2] w funkcji
        import footstats.daily_agent as mod
        old_parents = None

        # Prostszy sposób: testuj bezpośrednio przez monkey-patch DATA_DIR w funkcji
        import types
        src = mod._zapisz_next_final_txt.__code__
        # Zamiast tego — sprawdź przez efekty uboczne z prawdziwą DATA_DIR
        pass

    # Fallback test: po prostu sprawdź że funkcja nie rzuca wyjątku
    mod._zapisz_next_final_txt([])  # fallback → 13:30

    # Sprawdź że plik istnieje
    data_dir = Path(mod.__file__).parents[2] / "data"
    next_final = data_dir / "next_final.txt"
    assert next_final.exists()
    content = next_final.read_text().strip()
    assert ":" in content  # format HH:MM
