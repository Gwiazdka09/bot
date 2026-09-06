"""core/poisson_bayesian.py — Bayesian Poisson extension with att/def ratings + recency weighting."""
from __future__ import annotations

import logging
from typing import Optional

import numpy as np
import pandas as pd
from scipy.stats import poisson

from footstats.config import DC_RHO, MAX_GOLE, USE_DC_TAU

_log = logging.getLogger(__name__)

# Recency weights: last 5 matches get 3x weight vs older
_W_RECENT = 3.0
_W_OLDER = 1.0
_N_RECENT = 5

# Bayesian prior strength: 1 = fully trust data, 0 = fully trust prior
# Higher value = more shrinkage toward league average (safer for small samples)
_PRIOR_WEIGHT = 3.0  # equivalent to 3 "pseudo-matches" at league average


def tau_dixon_coles(
    h: int, a: int, lam_h: float, lam_a: float, rho: float
) -> float:
    """Współczynnik korekty Dixona-Colesa (1997) dla jednego wyniku.

    Niezależne rozkłady Poissona źle opisują mecze o niskim wyniku: 0-0 i 1-1
    padają CZĘŚCIEJ, a 1-0 i 0-1 RZADZIEJ, niż wychodzi z iloczynu. τ mnoży
    dokładnie te cztery pola, resztę macierzy zostawia nietkniętą:

        τ(0,0) = 1 - λ·μ·ρ      τ(0,1) = 1 + λ·ρ
        τ(1,0) = 1 + μ·ρ        τ(1,1) = 1 - ρ

    ρ < 0 przesuwa masę na remisy niskie. Obcinamy do zera od dołu, bo przy
    dużych λ i mocnym ρ wzór potrafi zejść poniżej — a ujemne prawdopodobieństwo
    zepsułoby cały rozkład.
    """
    if rho == 0.0:
        return 1.0
    if h == 0 and a == 0:
        return max(0.0, 1.0 - lam_h * lam_a * rho)
    if h == 0 and a == 1:
        return max(0.0, 1.0 + lam_h * rho)
    if h == 1 and a == 0:
        return max(0.0, 1.0 + lam_a * rho)
    if h == 1 and a == 1:
        return max(0.0, 1.0 - rho)
    return 1.0


def macierz_dixon_coles(lam_h: float, lam_a: float, rho: float = 0.0) -> np.ndarray:
    """Macierz prawdopodobieństw wyników, z korektą τ i renormalizacją.

    `rho=0.0` daje dokładnie dotychczasowy iloczyn zewnętrzny — dzięki temu
    włączenie flagi jest jedyną różnicą, a wyłączona flaga nie zmienia nic.
    """
    pmf_h = poisson.pmf(np.arange(MAX_GOLE), lam_h)
    pmf_a = poisson.pmf(np.arange(MAX_GOLE), lam_a)
    M = np.outer(pmf_h, pmf_a)

    if rho != 0.0:
        for h in range(min(2, MAX_GOLE)):
            for a in range(min(2, MAX_GOLE)):
                M[h, a] *= tau_dixon_coles(h, a, lam_h, lam_a, rho)

    suma = M.sum()
    return M / suma if suma > 0 else M


def _compute_ratings(
    team: str, df: pd.DataFrame, is_home: bool
) -> dict[str, float]:
    """
    Compute attack and defense rating for one team from match data.
    Returns {att, def, n} or None if insufficient data.
    """
    if is_home:
        mask = df["gospodarz"] == team
        goals_scored_col, goals_conceded_col = "gole_g", "gole_a"
    else:
        mask = df["goscie"] == team
        goals_scored_col, goals_conceded_col = "gole_a", "gole_g"

    rows = df[mask].copy()
    if rows.empty:
        return {"att": None, "def": None, "n": 0}

    # Recency weights
    n = len(rows)
    cutoff = max(0, n - _N_RECENT)
    weights = np.array([_W_OLDER] * cutoff + [_W_RECENT] * (n - cutoff))

    scored = rows[goals_scored_col].values
    conceded = rows[goals_conceded_col].values

    w_sum = weights.sum()
    att = float(np.dot(weights, scored) / w_sum)
    def_ = float(np.dot(weights, conceded) / w_sum)

    return {"att": att, "def": def_, "n": int(n)}


def _league_averages(df: pd.DataFrame) -> dict[str, float]:
    """Compute league-wide avg goals scored/conceded per match."""
    if df.empty or "gole_g" not in df.columns:
        return {"home_avg": 1.5, "away_avg": 1.1}
    home_avg = float(df["gole_g"].mean())
    away_avg = float(df["gole_a"].mean())
    return {
        "home_avg": max(0.5, home_avg),
        "away_avg": max(0.5, away_avg),
    }


def _bayesian_shrink(observed: float, n: int, prior: float) -> float:
    """
    Bayesian shrinkage estimator:
    posterior = (n * observed + prior_weight * prior) / (n + prior_weight)
    """
    return (n * observed + _PRIOR_WEIGHT * prior) / (n + _PRIOR_WEIGHT)


def predict_match_bayesian(
    g: str,
    a: str,
    df: pd.DataFrame,
    home_advantage: float = 1.0,
) -> Optional[dict]:
    """
    Bayesian Poisson prediction using separate attack/defense ratings.

    Model:
        lambda_home = home_att * (away_def / league_home_avg) * home_advantage
        lambda_away = away_att * (home_def / league_away_avg)

    Both attack and defense ratings shrunk toward league prior via Bayesian update.

    NAPRAWIONE 06.09.2026 — PIEC STALYCH BYLO PO ZLEJ STRONIE BOISKA.
    Do tego dnia funkcja liczyla lambda 2.1585 / 0.9515 przy faktycznych
    1.5087 / 1.2146 (holdout n=31 628): gospodarz przeszacowany o 43%, gosc
    zanizony o 22%. Byl to blad JEDNOSTEK, nie wybor modelowy:

      * `away_away["def"]` to gole, ktore gosc TRACI NA WYJEZDZIE — czyli gole
        GOSPODARZY. Sciagalo sie je do `league_away` i dzielilo przez
        `league_away`; obie wielkosci musza byc `league_home`;
      * `home_home["def"]` to gole tracone U SIEBIE — czyli gole GOSCI.
        Sciagalo sie do `league_home` i dzielilo przez `league_home`; obie
        musza byc `league_away`;
      * `BONUS_DOMOWY = 1.15` mnozylo lambda gospodarza, choc `home_att`
        liczy sie ze sredniej goli GOSPODARZY, ktora atut wlasnego boiska juz
        zawiera. Atut byl liczony dwa razy. Dokladnie ten sam blad jest opisany
        i naprawiony w docstringu `form.sily_ligowe`, po drugiej stronie kodu.

    Sprawdzian bez zadnych danych, ktory to lapie: druzyna doskonale
    przecietna — kazda jej wielkosc rowna swojej sredniej ligowej — musi dostac
    lambda dokladnie (league_home, league_away), przy KAZDEJ liczbie meczow.
    Stara wersja dawala tam 1.42x sredniej gospodarza. Pilnuje tego
    `tests/test_ramie_bayesian_naprawa.py`.

    Po naprawie lambda wychodzi 1.4943 / 1.1933 — na poziomie ramienia classic.

    CZEGO TO NIE NAPRAWIA, a dalej jest zepsute: ta funkcja NIE FILTRUJE LIGI
    (`_league_averages` liczy srednia z calej przekazanej ramki, a produkcja
    przekazuje 40 lig naraz), nie ma ZADNEGO okna, i obcina macierz na
    `MAX_GOLE` komorkach, podczas gdy glowna sciezka wola `MAX_GOLE + 1`.
    Trzy osobne zmiany projektowe, kazda wymaga wlasnego pomiaru.
    """
    if df.empty or "gole_g" not in df.columns:
        return None

    avgs = _league_averages(df)
    league_home = avgs["home_avg"]
    league_away = avgs["away_avg"]

    # Home team ratings (as home team)
    home_home = _compute_ratings(g, df, is_home=True)

    # Away team ratings (as away team)
    away_away = _compute_ratings(a, df, is_home=False)

    # Bayesian-shrunk attack/defense rates
    if home_home["att"] is None or away_away["att"] is None:
        return None

    # Home team attack (as home) — gole strzelone u siebie, prior league_home.
    home_att = _bayesian_shrink(home_home["att"], home_home["n"], league_home)
    # Away team defense (as away) — gole STRACONE na wyjezdzie, czyli gole
    # GOSPODARZY. Prior league_home, nie league_away.
    away_def = _bayesian_shrink(away_away["def"], away_away["n"], league_home)

    # Away team attack (as away) — gole strzelone na wyjezdzie, prior league_away.
    away_att = _bayesian_shrink(away_away["att"], away_away["n"], league_away)
    # Home team defense (as home) — gole STRACONE u siebie, czyli gole GOSCI.
    # Prior league_away, nie league_home.
    home_def_val = (
        _bayesian_shrink(home_home["def"], home_home["n"], league_away)
        if home_home["def"] is not None
        else league_away
    )

    # Mianowniki musza pasowac do STRONY BOISKA, po ktorej padly gole:
    # `away_def` liczy gole gospodarzy -> dzielimy przez league_home,
    # `home_def_val` liczy gole gosci  -> dzielimy przez league_away.
    lambda_h = max(0.05, home_att * (away_def / league_home) * home_advantage)
    lambda_a = max(0.05, away_att * (home_def_val / league_away))

    # Macierz wynikow. `USE_DC_TAU` wylaczone -> rho=0 -> dokladnie poprzedni
    # iloczyn zewnetrzny, bez zadnej roznicy numerycznej.
    M = macierz_dixon_coles(lambda_h, lambda_a, DC_RHO if USE_DC_TAU else 0.0)

    pw = float(np.sum(np.tril(M, -1)))   # home win
    pr = float(np.trace(M))               # draw
    pa = float(np.sum(np.triu(M, 1)))    # away win

    return {
        "lambda_g": round(lambda_h, 4),
        "lambda_a": round(lambda_a, 4),
        "pw": round(pw, 4),
        "pr": round(pr, 4),
        "pa": round(pa, 4),
        "n_home": home_home["n"],
        "n_away": away_away["n"],
        "league_home_avg": round(league_home, 3),
        "league_away_avg": round(league_away, 3),
        "model": "bayesian",
    }


def blend_with_classic(
    bayesian: dict,
    classic: dict,
    w_bayesian: float = 0.5,
) -> dict:
    """
    Blend Bayesian and classic Poisson predictions.
    w_bayesian=0.5 → equal weight; 1.0 → full Bayesian.
    """
    w_c = 1.0 - w_bayesian
    return {
        "lambda_g": round(w_bayesian * bayesian["lambda_g"] + w_c * classic.get("lambda_g", bayesian["lambda_g"]), 4),
        "lambda_a": round(w_bayesian * bayesian["lambda_a"] + w_c * classic.get("lambda_a", bayesian["lambda_a"]), 4),
        "pw": round(w_bayesian * bayesian["pw"] + w_c * classic.get("pw", bayesian["pw"]), 4),
        "pr": round(w_bayesian * bayesian["pr"] + w_c * classic.get("pr", bayesian["pr"]), 4),
        "pa": round(w_bayesian * bayesian["pa"] + w_c * classic.get("pa", bayesian["pa"]), 4),
        "model": f"blend_{w_bayesian:.1f}b",
    }


def blend_dixon_coles(
    p_model: dict,
    g: str,
    a: str,
    df: pd.DataFrame,
    w_bayesian: float = 0.5,
) -> dict:
    """Blenduje ramie Dixon-Coles do p_model (TYLKO pw/pr/pp).

    p_model: dict {pw,pr,pp,...} w procentach 0-100 (z classic predict_match).
    DC zwraca pa (away win) jako ulamek 0-1 -> remap pa->pp + x100.
    Gdy DC zwroci None (za malo danych) -> p_model bez zmian (graceful, = baseline).
    Klucze spoza {pw,pr,pp} (np. bt/o25) NIE sa modyfikowane.
    Renormalizacja pw/pr/pp do 100 (zdarzenia rozlaczne i wyczerpujace).
    """
    bay = predict_match_bayesian(g, a, df)
    if not bay:
        return p_model

    p_bay = {"pw": bay["pw"] * 100.0, "pr": bay["pr"] * 100.0, "pp": bay["pa"] * 100.0}
    w_c = 1.0 - w_bayesian
    blended = {k: p_model[k] * w_c + p_bay[k] * w_bayesian for k in ("pw", "pr", "pp")}

    s = blended["pw"] + blended["pr"] + blended["pp"] or 1.0
    out = dict(p_model)  # zachowaj bt/o25 i pozostale klucze
    out["pw"] = round(blended["pw"] / s * 100.0, 4)
    out["pr"] = round(blended["pr"] / s * 100.0, 4)
    out["pp"] = round(blended["pp"] / s * 100.0, 4)
    return out
