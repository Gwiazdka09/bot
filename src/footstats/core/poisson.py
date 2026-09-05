import functools
import logging
import pandas as pd
import numpy as np
from scipy.stats import poisson
from footstats.config import (
    MAX_GOLE, BONUS_DOMOWY, OSTATNIE_N, DC_RHO_CLASSIC,
)

logger = logging.getLogger(__name__)
from footstats.core.h2h import AnalizaH2H
from footstats.core.classifier import _korekta_dwumecz, _czy_knockout, _korekta_rewanz_v26
from footstats.core.form import _oblicz_sile_wazona

# ================================================================
#  MODUL 10 - PREDYKCJA POISSONA
# ================================================================

@functools.lru_cache(maxsize=512)
def _macierz(lambda_g: float, lambda_a: float, N: int, rho: float = 0.0) -> tuple:
    """
    Cached Poisson matrix with Laplace smoothing and Dixon-Coles tau.

    Args should be pre-rounded to 4dp.
    Smoothing prevents zero probabilities and numerical instability.

    `rho` to korekta Dixona-Colesa (1997): mnozy CZTERY komorki niskiego wyniku,
    reszte macierzy zostawia nietknieta. Przy rho<0 rosna 0-0 i 1-1, maleja 1-0
    i 0-1 — Poisson notorycznie zaniza remisy niskobramkowe i zmierzylismy to
    u siebie (1.36 pp na holdoucie, patrz `config.DC_RHO_CLASSIC`).

    Poprawki sumuja sie TOZSAMOSCIOWO do zera, wiec `over25` i `btts` sa od rho
    NIEZALEZNE — obie te wielkosci licza sie z komorek o sumie goli, ktorej tau
    nie przesuwa. Pilnuje tego `tests/test_poisson_rho.py`.

    `rho` JEST czescia klucza cache — inaczej pierwsze wywolanie zatruloby
    wszystkie nastepne.
    """
    SMOOTHING_EPS = 1e-8

    pmf_g = poisson.pmf(np.arange(N), lambda_g)
    pmf_a = poisson.pmf(np.arange(N), lambda_a)

    pmf_g = (pmf_g + SMOOTHING_EPS) / (1.0 + N * SMOOTHING_EPS)
    pmf_a = (pmf_a + SMOOTHING_EPS) / (1.0 + N * SMOOTHING_EPS)

    M = np.outer(pmf_g, pmf_a)

    if rho != 0.0 and N >= 2:
        for (i, j), tau in (
            ((0, 0), 1.0 - lambda_g * lambda_a * rho),
            ((0, 1), 1.0 + lambda_g * rho),
            ((1, 0), 1.0 + lambda_a * rho),
            ((1, 1), 1.0 - rho),
        ):
            # Obciecie od dolu: przy duzych lambdach i mocnym rho wzor potrafi
            # zejsc ponizej zera, a ujemne prawdopodobienstwo zepsulo by rozklad.
            M[i, j] *= max(0.0, tau)

    M_sum = np.sum(M)
    if M_sum > 0:
        M = M / M_sum

    pw  = float(np.sum(np.tril(M, -1)))
    pr  = float(np.sum(np.diag(M)))
    pp  = float(np.sum(np.triu(M,  1)))
    btts = float((1 - pmf_g[0]) * (1 - pmf_a[0]))
    i_idx, j_idx = np.meshgrid(np.arange(N), np.arange(N), indexing="ij")
    over25_raw = 1.0 - float(M[i_idx + j_idx <= 2].sum())
    idx = np.unravel_index(np.argmax(M), M.shape)
    top5_raw = np.argsort(M, axis=None)[::-1][:5]
    rows_, cols_ = np.unravel_index(top5_raw, M.shape)
    top5_data = tuple((int(r), int(c), float(M[r, c])) for r, c in zip(rows_, cols_))
    return (pw, pr, pp, btts, over25_raw, int(idx[0]), int(idx[1]), top5_data)


# Mapa "nazwa znormalizowana → nazwa z historii", trzymana w `df.attrs`.
#
# Nie jako dodatkowe KOLUMNY: `predict_match` dostaje zwykle wycinek ramki,
# więc zapis kolumny leci na widok i pandas słusznie krzyczy
# SettingWithCopyWarning — cache mógłby się nie utrwalić, a przy 50 meczach
# dziennie normalizacja 30k+ wierszy za każdym razem to czysta strata.
# `attrs` to oficjalny worek na metadane ramki i nie rusza jej danych.
_ATR_MAPA = "_footstats_mapa_nazw"

# Klucz cache tabeli sił ligowych — liczenie jej dla każdego meczu z osobna
# przy 40 ligach i 139k meczów kosztowałoby więcej niż cała reszta predykcji.
_ATR_SILY_LIG = "_footstats_sily_ligowe"


def _sila_ligowa_on() -> bool:
    """Czy λ ma się liczyć wobec ligi (env `SILA_LIGOWA`).

    Domyślnie WŁĄCZONE po pomiarze walk-forward na dwóch niezależnych próbach:
    Brier 0.6557→0.6089 (4 ligi top) i 0.6639→0.6142 (6 innych lig), przy
    0.6001/0.5924 dla rynku. Escape-hatch `SILA_LIGOWA=0` wraca do starej λ.
    """
    import os
    return os.getenv("SILA_LIGOWA", "1").strip().lower() not in ("0", "false", "no", "")


def _liga_pary(df_f: pd.DataFrame) -> str | None:
    """Liga, w której ta para realnie gra — najczęstsza w jej ostatnich meczach."""
    if "league" not in df_f.columns or df_f.empty:
        return None
    ligi = df_f["league"].dropna()
    return str(ligi.mode().iloc[0]) if not ligi.empty else None


def _baza_ligowa(
    df_mecze: pd.DataFrame, df_f: pd.DataFrame, g_h: str, a_h: str
) -> tuple[float, float, dict, dict] | None:
    """(λ bazowa gospodarza, λ bazowa gościa, siły g, siły a) wobec ligi.

    None, gdy tej drogi nie da się przejść uczciwie: brak flagi, brak kolumny
    `league`, brak historii którejś drużyny w tej lidze. Wtedy `predict_match`
    wraca do starej ścieżki — gorsza λ jest lepsza niż żadna.

    BEZ `BONUS_DOMOWY`: średnia goli gospodarzy w lidze JUŻ zawiera atut
    własnego boiska, więc mnożenie przez niego liczyłoby go drugi raz.
    """
    if not _sila_ligowa_on():
        return None
    liga = _liga_pary(df_f)
    if liga is None:
        return None

    cache = df_mecze.attrs.setdefault(_ATR_SILY_LIG, {})
    if liga not in cache:
        from footstats.core.form import sily_ligowe
        cache[liga] = sily_ligowe(df_mecze[df_mecze["league"] == liga])
    wynik = cache[liga]
    if not wynik:
        return None

    tabela, sr_dom, sr_wyj = wynik
    if g_h not in tabela or a_h not in tabela:
        return None

    sg_l, sa_l = tabela[g_h], tabela[a_h]
    baza_g = sg_l["atak_dom"] * sa_l["obrona_wyj"] * sr_dom
    baza_a = sa_l["atak_wyj"] * sg_l["obrona_dom"] * sr_wyj

    # Kształt zgodny ze starą ścieżką — reszta `predict_match` (opis, pola
    # wyjściowe `sila_at_*`) czyta te same klucze i nie musi o niczym wiedzieć.
    def _zgodny(s: dict, atak: str, obrona: str) -> dict:
        return {"atak": s[atak], "obrona": s[obrona], "mecze": s["mecze"],
                "gole_sr": round(s[atak] * sr_dom, 2),
                "strac_sr": round(s[obrona] * sr_wyj, 2),
                "forma_pkt": 0.0}

    return (baza_g, baza_a,
            _zgodny(sg_l, "atak_dom", "obrona_dom"),
            _zgodny(sa_l, "atak_wyj", "obrona_wyj"))


def _kanoniczne_nazwy(df_mecze: pd.DataFrame, g: str, a: str) -> tuple[str, str]:
    """Nazwy obu drużyn tak, jak zapisuje je historia.

    Źródło predykcji i źródło historii piszą inaczej ("Górnik Zabrze" vs
    "Gornik Zabrze", "SC Cambuur" vs "Cambuur"). Reszta `predict_match` —
    maska meczów i słownik sił z `_oblicz_sile_wazona` — operuje na nazwach
    Z RAMKI, więc tłumaczymy raz tutaj, zamiast łatać każde użycie osobno.

    Nazwa nierozpoznana wraca bez zmian: dalszy kod i tak potraktuje ją jako
    brak historii, a podstawianie czegokolwiek liczyłoby λ z cudzych meczów.

    Świadomie BEZ dopasowania rozmytego: `team_similarity` daje 0.800 zarówno
    dla ("Wisła Kraków", "Wisla") jak i ("Wisła Płock", "Wisla") — żaden próg
    nie rozdzieli tych dwóch klubów, a pomyłka psuje λ po cichu, bo nic nie pada.
    """
    from footstats.utils.normalize import normalize_team_name

    mapa = df_mecze.attrs.get(_ATR_MAPA)
    if mapa is None:
        mapa = {}
        for kolumna in ("gospodarz", "goscie"):
            for oryginal in df_mecze[kolumna].dropna().unique():
                nazwa = str(oryginal).strip()
                if nazwa:
                    mapa.setdefault(normalize_team_name(nazwa), nazwa)
        df_mecze.attrs[_ATR_MAPA] = mapa

    return (
        mapa.get(normalize_team_name(g), g),
        mapa.get(normalize_team_name(a), a),
    )


def predict_match(
    g: str, a: str,
    df_mecze: pd.DataFrame,
    importance_g: dict = None,
    importance_a: dict = None,
    heurystyka_g: dict = None,
    heurystyka_a: dict = None,
    h2h_g: dict = None,
    h2h_a: dict = None,
    fortress_g: dict = None,
    first_leg_g=None, first_leg_a=None,
    stage: str = "REGULAR_SEASON",
    klasyfikacja: dict = None,
    use_xg: bool = True,
    use_calibration: bool = True,
) -> dict | None:
    """
    Kompletna predykcja v2.6 z:
      1. Wazona forma historyczna
      2. Stage Recognition: LIGA vs PUCHAR vs REWANZ vs FINAL
      3. Fallback turniejowy: gdy brak statystyk pary, uzyj sredniej turniejowej
      4. Importance Index 2.0
      5. Heurystyka zmeczenia/rotacji
      6. AnalizaH2H: Patent +10%, Zemsta +15%
      7. HomeFortress: +10% obrona
      8. Rewanz Vabank v2.6 (+30% / Parking Bus)
      9. Single-Match Finals: boost remisu + uwaga 'dogr./karne'
    Zwraca dict lub None jesli za malo danych.
    """
    importance_g = importance_g or {"bonus_atak": 1.0, "komentarz": "", "status": "NORMAL"}
    importance_a = importance_a or {"bonus_atak": 1.0, "komentarz": "", "status": "NORMAL"}
    heurystyka_g = heurystyka_g or {"mnoznik_atak": 1.0, "mnoznik_obr": 1.0, "opis": ""}
    heurystyka_a = heurystyka_a or {"mnoznik_atak": 1.0, "mnoznik_obr": 1.0, "opis": ""}
    h2h_g        = h2h_g or {"mnoznik_atak": 1.0, "mnoznik_szans": 1.0, "opis": "", "pewnosc": 20, "n_h2h": 0}
    h2h_a        = h2h_a or {"mnoznik_atak": 1.0, "mnoznik_szans": 1.0, "opis": "", "pewnosc": 20, "n_h2h": 0}
    fortress_g   = fortress_g or {"bonus_obrona": 1.0, "fortress": False, "opis": ""}
    klasyfikacja = klasyfikacja or {"typ": "LIGA", "rewanz": False, "single": False,
                                    "agg_g": None, "agg_a": None, "opis": ""}

    stage_up     = str(stage).upper()
    is_liga      = (stage_up == "REGULAR_SEASON")
    jest_rewanz  = klasyfikacja.get("rewanz", False)
    jest_single  = klasyfikacja.get("single", False)

    # ── Zbierz mecze do analizy ──────────────────────────────────────
    # `g_h`/`a_h` = nazwy w zapisie historii; `g`/`a` zostają nietknięte, bo
    # wracają w wyniku i po nich rozliczane są potem kupony.
    g_h, a_h = _kanoniczne_nazwy(df_mecze, g, a)
    maska = (
        df_mecze["gospodarz"].isin((g_h, a_h))
        | df_mecze["goscie"].isin((g_h, a_h))
    )
    df_f = df_mecze[maska].tail(OSTATNIE_N)

    # ── v2.6 STABILNOSC: fallback turniejowy ─────────────────────────
    # Jesli brak danych pary w fazie pucharowej, nie zwracamy None —
    # uzyj ogolnej sredniej z df_mecze (min 4 mecze dowolnych).
    if len(df_f) < 4:
        if is_liga:
            return None  # Liga: normalna sciezka, brak danych = brak predykcji
        # Tryb turniejowy: probuj z calym df
        df_f_all = df_mecze.tail(OSTATNIE_N * 2)
        if len(df_f_all) < 4:
            return None
        # Policz srednia turniejowa i syntetyczne sily dla pary
        sily_all, srednia_all = _oblicz_sile_wazona(df_f_all)
        if not sily_all:
            return None
        # Szacuj sily jako srednia turniejowa (fallback)
        avg_atak  = float(np.mean([v["atak"]   for v in sily_all.values()]))
        avg_obr   = float(np.mean([v["obrona"] for v in sily_all.values()]))
        avg_gsr   = float(np.mean([v["gole_sr"] for v in sily_all.values()]))
        avg_strac = float(np.mean([v["strac_sr"] for v in sily_all.values()]))
        avg_forma = float(np.mean([v["forma_pkt"] for v in sily_all.values()]))
        syntetyczna = {
            "atak": avg_atak, "obrona": avg_obr,
            "gole_sr": avg_gsr, "strac_sr": avg_strac, "forma_pkt": avg_forma
        }
        sg = sily_all.get(g_h, syntetyczna)
        sa = sily_all.get(a_h, syntetyczna)
        srednia = srednia_all
        df_f    = df_f_all   # do confidence
    else:
        sily, srednia = _oblicz_sile_wazona(df_f)
        if g_h not in sily or a_h not in sily:
            return None
        sg, sa = sily[g_h], sily[a_h]

    # ── Lambda bazowa ────────────────────────────────────────────────
    # Dwie drogi do (baza_g, baza_a). Ligowa jest lepsza i zmierzona, ale
    # potrzebuje kolumny `league` i historii obu drużyn w tej lidze — czego
    # nie ma np. przy meczach reprezentacji. Brak któregokolwiek warunku cofa
    # do starej drogi, bo gorsza λ jest lepsza niż żadna.
    baza = _baza_ligowa(df_mecze, df_f, g_h, a_h)
    if baza is not None:
        baza_g, baza_a, sg, sa = baza
    else:
        baza_g = sg["atak"] * sa["obrona"] * srednia * BONUS_DOMOWY
        baza_a = sa["atak"] * sg["obrona"] * srednia

    lambda_g = max(0.05,
        baza_g
        * importance_g["bonus_atak"]
        * heurystyka_g["mnoznik_atak"]
        * h2h_g["mnoznik_atak"]
        / heurystyka_a["mnoznik_obr"]
    )
    lambda_a = max(0.05,
        baza_a
        * importance_a["bonus_atak"]
        * heurystyka_a["mnoznik_atak"]
        * h2h_a["mnoznik_atak"]
        / heurystyka_g["mnoznik_obr"]
        / fortress_g["bonus_obrona"]
    )

    # Patent H2H
    lambda_g *= h2h_g.get("mnoznik_szans", 1.0)
    lambda_a *= h2h_a.get("mnoznik_szans", 1.0)
    lambda_g = max(0.05, lambda_g)
    lambda_a = max(0.05, lambda_a)

    # ── v2.6 Korekta rewanzowa ───────────────────────────────────────
    korekta_opis = ""
    jest_knockout = _czy_knockout(stage)

    if jest_rewanz:
        agg_g = klasyfikacja.get("agg_g")
        agg_a = klasyfikacja.get("agg_a")
        if agg_g is not None and agg_a is not None:
            lambda_g, lambda_a, korekta_opis = _korekta_rewanz_v26(
                lambda_g, lambda_a, int(agg_g), int(agg_a))
        elif first_leg_g is not None:
            lambda_g, lambda_a, korekta_opis = _korekta_dwumecz(
                lambda_g, lambda_a, first_leg_g, first_leg_a, jest_gospodarzem_1=False)
    elif jest_knockout and first_leg_g is not None:
        lambda_g, lambda_a, korekta_opis = _korekta_dwumecz(
            lambda_g, lambda_a, first_leg_g, first_leg_a, jest_gospodarzem_1=False)

    lambda_g = max(0.05, lambda_g)
    lambda_a = max(0.05, lambda_a)

    # ── Kalibracja modelu (walk-forward bias correction) ─────────────
    if use_calibration:
        try:
            from footstats.core.lambda_optimizer import load_calibration
            _cal_h, _cal_a = load_calibration()
            lambda_g *= _cal_h
            lambda_a *= _cal_a
        except (ImportError, OSError, ValueError):
            pass  # Brak pliku kalibracji → działaj z domyślnymi lambdami

        lambda_g = max(0.05, lambda_g)
        lambda_a = max(0.05, lambda_a)

    # ── xG blend (Understat cache-only, no live request) ─────────────
    # λ_dom = atak gospodarza (xGF) ZDERZONY z obroną gościa (xGA): (xGF_h + xGA_a)/2.
    # Wcześniej brano tylko xGF własny — ignorowało słabość/siłę obrony rywala.
    if use_xg:
        try:
            from footstats.scrapers.understat_xg import _cache_get, _to_slug
            from datetime import datetime as _dt
            _season = _dt.now().year if _dt.now().month >= 7 else _dt.now().year - 1
            xg_h = _cache_get(_to_slug(g), _season) or {}
            xg_a = _cache_get(_to_slug(a), _season) or {}
            _XG_W = 0.20

            h_xgf, h_xga = xg_h.get("xg_for_avg"), xg_h.get("xga_avg")
            a_xgf, a_xga = xg_a.get("xg_for_avg"), xg_a.get("xga_avg")

            # Gospodarz strzela: jego atak vs obrona gościa
            if h_xgf and h_xgf > 0:
                xg_lambda_g = (h_xgf + a_xga) / 2 if (a_xga and a_xga > 0) else h_xgf
                lambda_g = round((1 - _XG_W) * lambda_g + _XG_W * xg_lambda_g, 4)
            # Gość strzela: jego atak vs obrona gospodarza
            if a_xgf and a_xgf > 0:
                xg_lambda_a = (a_xgf + h_xga) / 2 if (h_xga and h_xga > 0) else a_xgf
                lambda_a = round((1 - _XG_W) * lambda_a + _XG_W * xg_lambda_a, 4)
        except (ImportError, AttributeError, OSError, ValueError, KeyError):
            pass  # xG cache niedostępny → czyste lambdy Poissona

        lambda_g = max(0.05, lambda_g)
        lambda_a = max(0.05, lambda_a)

    # ── Macierz Poissona (cached) ────────────────────────────────────
    from footstats.config import FINAL_REMIS_BOOST
    N = MAX_GOLE + 1
    pw, pr, pp, btts, over25_raw, wynik_g, wynik_a, top5_data = _macierz(
        round(lambda_g, 4), round(lambda_a, 4), N, DC_RHO_CLASSIC
    )

    # ── v2.6 Final boost: wiekszy remis w meczach bez rewanzu ────────
    if jest_single:
        pr *= FINAL_REMIS_BOOST

    suma = pw + pr + pp or 1.0
    pw /= suma; pr /= suma; pp /= suma

    # ── Sufit p_remis (FAZA 16.3) ─────────────────────────────────────
    # Dla niskich lambd (slabe/egzotyczne druzyny) czysty Poisson + FINAL_REMIS_BOOST
    # daje p_remis >50%, co przewyzsza realne stopy remisow nawet w najbardziej
    # zachowawczych ligach (~35-40%). Nadwyzke przenosimy proporcjonalnie na 1/2,
    # zeby "X" nie dominowal listy kandydatow dla slabych meczow miedzynarodowych.
    _PR_CAP = 0.40
    if pr > _PR_CAP:
        nadwyzka = pr - _PR_CAP
        pr = _PR_CAP
        reszta = pw + pp or 1.0
        pw += nadwyzka * (pw / reszta)
        pp += nadwyzka * (pp / reszta)

    over25 = min(over25_raw / suma, 1.0)
    top5 = [(f"{r}:{c}", round(v * 100, 1)) for r, c, v in top5_data]

    n_h2h_srednia = (h2h_g.get("n_h2h", 0) + h2h_a.get("n_h2h", 0)) // 2
    pewnosc = AnalizaH2H.oblicz_pewnosc_laczna(n_h2h_srednia, len(df_f))

    return {
        "gospodarz":    g,
        "gosc":         a,
        "lambda_g":     round(lambda_g, 2),
        "lambda_a":     round(lambda_a, 2),
        "p_wygrana":    round(pw  * 100, 1),
        "p_remis":      round(pr  * 100, 1),
        "p_przegrana":  round(pp  * 100, 1),
        "btts":         round(btts  * 100, 1),
        "over25":       round(over25 * 100, 1),
        "under25":      round((1 - over25) * 100, 1),
        "wynik_g":      wynik_g,
        "wynik_a":      wynik_a,
        "top5":         top5,
        "sila_at_g":    round(sg["atak"],   2),
        "sila_ob_g":    round(sg["obrona"], 2),
        "sila_at_a":    round(sa["atak"],   2),
        "sila_ob_a":    round(sa["obrona"], 2),
        "forma_g":      sg["forma_pkt"],
        "forma_a":      sa["forma_pkt"],
        "imp_g":        importance_g,
        "imp_a":        importance_a,
        "heur_g":       heurystyka_g,
        "heur_a":       heurystyka_a,
        "h2h_g":        h2h_g,
        "h2h_a":        h2h_a,
        "fortress_g":   fortress_g,
        "knockout":     jest_knockout,
        "rewanz":       jest_rewanz,
        "single":       jest_single,
        "korekta_opis": korekta_opis,
        "klasyfikacja": klasyfikacja,
        "pewnosc":      pewnosc,
    }
