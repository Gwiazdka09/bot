"""Dziennik zapisuje sie ZANIM policzymy team-news — kolumny nie mialy szansy.

STAN ZASTANY (2026-09-07, zmierzone na produkcji). `model_log` ma 1078 wierszy,
78 od wlaczenia flagi `FOOTSTATS_TEAM_NEWS=1`, i **0 (zero) wierszy z niepustym
`p_over_abs`, `edge_absencje`, `rynek_p_over` czy `absencje_pewne_home`**.
74% wierszy dotyczy meczow granych TEGO SAMEGO DNIA, wiec to nie jest kwestia
horyzontu ani zrodla — FotMob oddaje 121 meczow dziennie i odpowiada 200.

Przyczyna jest w KOLEJNOSCI w `daily_agent.main()`:

    linia ~1038   zapisz_partie(wyniki)          <- INSERT do model_log
    linia ~1089   _enrichuj_finalna_faza(wyniki) <- dopiero tu powstaja pola

Cztery kolumny sa w INSERT-cie (pilnuje tego `test_model_log_absencje.py`)
i nadal nie moga byc niepuste, bo w chwili INSERT-a nikt ich jeszcze nie
policzyl. Poprzednia naprawa dodala pola do zapytania i nikt nie sprawdzil,
czy zapytanie biegnie po ich policzeniu.

Przeniesienie zapisu za wzbogacenie NIE JEST rozwiazaniem: miedzy jednym
a drugim stoja cztery filtry (28 -> 6 na przebiegu 06.09), a `model_log`
istnieje wlasnie po to, zeby widziec WSZYSTKIE oceny, nie te 5%, ktore
przetrwaly. Stad druga faza: INSERT zostaje, po wzbogaceniu leci UPDATE.
"""
from __future__ import annotations

import re
from pathlib import Path


from footstats.core import kalibracja_log as kl
from tests.test_model_log_absencje import _Conn, _kandydat, baza  # noqa: F401


def test_zapisz_partie_znakuje_kandydata_identyfikatorem(baza):  # noqa: F811
    """Bez tego nie da sie potem trafic w ten sam wiersz."""
    k = _kandydat()
    kl.zapisz_partie([k], zrodlo="final")
    assert k["_model_log_id"] == 7


def test_uzupelnia_pola_team_news_po_wzbogaceniu(baza):  # noqa: F811
    k = _kandydat()
    kl.zapisz_partie([k], zrodlo="final")
    baza.zapytania.clear()

    # Tu, w produkcji, dzieje sie `_enrichuj_finalna_faza`.
    k.update({"p_over_abs": 0.472, "edge_absencje": -0.031,
              "rynek_p_over": 0.503, "absencje_pewne_home": 2,
              "absencje_pewne_away": 0, "absencje_udzial_home": 0.18,
              "absencje_udzial_away": 0.0})

    assert kl.uzupelnij_team_news([k]) == 1
    aktualizacje = [z for z in baza.zapytania if z[0].upper().startswith("UPDATE")]
    assert len(aktualizacje) == 1
    sql, params = aktualizacje[0]
    assert "model_log" in sql and "WHERE id = ?" in sql
    assert params[-1] == 7, "UPDATE musi celowac w zapisany wiersz"
    for kolumna in ("p_over_abs", "edge_absencje", "rynek_p_over",
                    "absencje_pewne_home", "absencje_pewne_away",
                    "absencje_udzial_home", "absencje_udzial_away"):
        assert kolumna in sql, f"brak {kolumna} w UPDATE"
    assert 0.472 in params and -0.031 in params and 0.503 in params


def test_kandydat_bez_team_news_nie_generuje_zapytania(baza):  # noqa: F811
    """Pusty UPDATE nadpisalby wartosci NULL-ami przy drugim przebiegu."""
    k = _kandydat()
    kl.zapisz_partie([k], zrodlo="final")
    baza.zapytania.clear()
    assert kl.uzupelnij_team_news([k]) == 0
    assert not [z for z in baza.zapytania if z[0].upper().startswith("UPDATE")]


def test_kandydat_bez_identyfikatora_jest_pomijany(baza):  # noqa: F811
    """Dedup w `zapisz_ocene` moze nie zwrocic id — to nie moze wysadzic runu."""
    k = _kandydat(p_over_abs=0.4)
    assert kl.uzupelnij_team_news([k]) == 0


def test_awaria_bazy_nie_wysadza_przebiegu(monkeypatch):
    """Dziennik to obserwacja, nie warunek dzialania."""
    def _pada(*a, **kw):
        raise RuntimeError("pula polaczen padla")

    monkeypatch.setattr(kl, "_connect", _pada)
    k = _kandydat(p_over_abs=0.4)
    k["_model_log_id"] = 7
    assert kl.uzupelnij_team_news([k]) == 0


def test_zero_jest_zapisywane_a_brak_klucza_nie():
    """`0` znaczy 'policzone i wyszlo zero' — inny stan niz 'nie liczylismy'."""
    assert kl._pola_team_news({"absencje_pewne_home": 0}) == {"absencje_pewne_home": 0}
    assert kl._pola_team_news({"gospodarz": "Legia"}) == {}


def test_kolejnosc_wolan_w_daily_agent():
    """Straznik na blad, ktory tu naprawiamy.

    Nie da sie tego sprawdzic jednostkowo bez odpalenia calego `main()`, a to
    jest dokladnie ta klasa bledu, ktora przezyla dwie naprawy — wiec pilnuje
    jej test na kolejnosci wywolan w zrodle.
    """
    zrodlo = (Path(__file__).resolve().parents[1]
              / "src" / "footstats" / "daily_agent.py").read_text(encoding="utf-8")
    linie = zrodlo.splitlines()

    def numer(wzorzec: str) -> int:
        trafienia = [i for i, w in enumerate(linie)
                     if re.search(wzorzec, w) and not w.strip().startswith("#")
                     and "import" not in w]
        assert trafienia, f"nie znalazlem wywolania {wzorzec}"
        return trafienia[0]

    zapis = numer(r"zapisz_partie\(")
    wzbogacenie = numer(r"_enrichuj_finalna_faza\(")
    uzupelnienie = numer(r"uzupelnij_team_news\(")
    assert zapis < wzbogacenie, "INSERT ma zostac przed filtrami"
    assert wzbogacenie < uzupelnienie, (
        "UPDATE z team-news musi isc PO wzbogaceniu — inaczej kolumny beda NULL, "
        "co bylo stanem produkcji do 2026-09-07")
