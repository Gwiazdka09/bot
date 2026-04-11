"""tests/test_normalize.py — testy dla utils.normalize.normalize_team_name"""
import pytest
from footstats.utils.normalize import normalize_team_name, reload_mappings


# ── Prefiksy ────────────────────────────────────────────────────────────────

def test_removes_fc_prefix():
    assert normalize_team_name("FC Augsburg") == "augsburg"

def test_removes_ks_prefix():
    assert normalize_team_name("KS Lechia Gdansk") == "lechia gdansk"

def test_removes_tsg_prefix():
    assert normalize_team_name("TSG Hoffenheim") == "hoffenheim"

def test_removes_al_prefix():
    assert normalize_team_name("Al-Taawoun") == "taawoun"

def test_removes_rb_prefix():
    assert normalize_team_name("RB Leipzig") == "leipzig"

def test_removes_ac_prefix():
    assert normalize_team_name("AC Milan") == "milan"

def test_removes_as_prefix():
    assert normalize_team_name("AS Roma") == "roma"

def test_removes_sc_prefix():
    assert normalize_team_name("SC Freiburg") == "freiburg"


# ── Sufiksy ────────────────────────────────────────────────────────────────

def test_removes_united_suffix():
    assert normalize_team_name("Manchester United") == "manchester"

def test_removes_city_suffix():
    assert normalize_team_name("Manchester City") == "manchester"

def test_keeps_name_without_suffix():
    assert normalize_team_name("Arsenal") == "arsenal"


# ── Diakrytyki ────────────────────────────────────────────────────────────

def test_strips_polish_diacritics():
    assert normalize_team_name("Wisła Płock") == "wisla plock"

def test_strips_lechia_diacritics():
    assert normalize_team_name("KS Lechia Gdańsk") == "lechia gdansk"

def test_strips_ks_and_diacritics():
    # KS prefix usunięty, ń → n
    result = normalize_team_name("KS Lechia Gdańsk")
    assert "ks" not in result
    assert "gdansk" in result


# ── Znaki specjalne ──────────────────────────────────────────────────────

def test_handles_hyphen():
    # Al-Taawoun: al prefix usunięty, myślnik → spacja
    assert normalize_team_name("Al-Taawoun") == "taawoun"

def test_handles_apostrophe():
    assert "'" not in normalize_team_name("Borussia M'gladbach")

def test_handles_saint_germain():
    # Spacja, nie myślnik w znormalizowanej formie
    result = normalize_team_name("Paris Saint-Germain")
    assert "paris" in result
    assert "saint" in result
    assert "germain" in result


# ── Przypadki brzegowe ───────────────────────────────────────────────────

def test_empty_string():
    assert normalize_team_name("") == ""

def test_only_prefix():
    # Sam FC bez nazwy → pusty string
    result = normalize_team_name("FC")
    assert result == "" or result == "fc"  # zależy od długości tokenu

def test_already_normalized():
    assert normalize_team_name("arsenal") == "arsenal"

def test_case_insensitive():
    assert normalize_team_name("FC AUGSBURG") == normalize_team_name("fc augsburg")


# ── Mappingi ────────────────────────────────────────────────────────────

def test_psg_mapping(tmp_path, monkeypatch):
    """mapping PSG -> paris saint germain z team_mappings.json"""
    import footstats.utils.normalize as n_mod
    mappings_file = tmp_path / "team_mappings.json"
    mappings_file.write_text('{"psg": "paris saint germain"}', encoding="utf-8")
    monkeypatch.setattr(n_mod, "_MAPPINGS_PATH", mappings_file)
    reload_mappings()
    result = normalize_team_name("PSG", use_mappings=True)
    assert result == "paris saint germain"
    reload_mappings()  # reset

def test_use_mappings_false_skips_mapping(tmp_path, monkeypatch):
    import footstats.utils.normalize as n_mod
    mappings_file = tmp_path / "team_mappings.json"
    mappings_file.write_text('{"arsenal": "the gunners"}', encoding="utf-8")
    monkeypatch.setattr(n_mod, "_MAPPINGS_PATH", mappings_file)
    reload_mappings()
    result = normalize_team_name("Arsenal", use_mappings=False)
    assert result == "arsenal"  # bez mappingu
    reload_mappings()


# ── Integracja z evening_agent fuzzy match ───────────────────────────────

def test_similar_after_normalize():
    """Po normalizacji KS Lechia Gdansk i Lechia Gdansk powinny mieć similarity ~1.0"""
    from difflib import SequenceMatcher
    a = normalize_team_name("KS Lechia Gdańsk")
    b = normalize_team_name("Lechia Gdansk")
    score = SequenceMatcher(None, a, b).ratio()
    assert score >= 0.90

def test_fc_augsburg_matches_augsburg():
    a = normalize_team_name("FC Augsburg")
    b = normalize_team_name("Augsburg")
    assert a == b
