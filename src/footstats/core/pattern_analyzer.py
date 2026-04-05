"""
pattern_analyzer.py – analiza wzorców i schematów na danych historycznych.

Wykrywa:
  - home advantage per liga
  - over/under, BTTS rates per liga
  - kalibrację kursów (implied prob vs actual)
  - wpływ formy (ostatnie 3/5 meczów) na wynik
  - rozkład goli (Poisson fit)
  - wzorce "marchewki" (silne sygnały) i "kije" (mity do odrzucenia)

Użycie:
    from footstats.core.pattern_analyzer import analyze_all, format_report

    df   = load_cached()
    rep  = analyze_all(df)
    print(format_report(rep))
"""

import logging
from collections import defaultdict

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

MIN_MATCHES = 50   # minimalna liczba meczów do statystyk per liga


# ─────────────────────────── utils ────────────────────────────────────────

def _safe_pct(num: float, den: float, decimals: int = 1) -> float | None:
    return round(num / den * 100, decimals) if den >= 1 else None


def _implied_prob(odds: float) -> float:
    return 1.0 / odds if odds > 1.0 else 0.0


# ─────────────────────────── 1. Wyniki per liga ───────────────────────────

def analyze_results_by_league(df: pd.DataFrame) -> dict:
    """Home/Draw/Away win rates, avg gole per liga."""
    out = {}
    for league, grp in df.groupby("league"):
        n = len(grp)
        if n < MIN_MATCHES:
            continue
        res = grp["result"].value_counts()
        out[league] = {
            "n":          n,
            "home_win":   _safe_pct(res.get("H", 0), n),
            "draw":       _safe_pct(res.get("D", 0), n),
            "away_win":   _safe_pct(res.get("A", 0), n),
            "avg_goals":  round(grp["total_goals"].mean(), 2) if "total_goals" in grp else None,
            "over25_pct": round(grp["over25"].mean() * 100, 1) if "over25" in grp else None,
            "btts_pct":   round(grp["btts"].mean() * 100, 1) if "btts" in grp else None,
        }
    return out


# ─────────────────────────── 2. Kalibracja kursów ─────────────────────────

def analyze_odds_calibration(df: pd.DataFrame, n_bins: int = 10) -> dict:
    """
    Sprawdza czy kursy bukmacherów są skalibrowane.
    Dla każdego przedziału implied probability:
      - ile meczów zakończyło się tym wynikiem (actual)
      - ile implied probability mówiła (expected)
    Jeśli actual < implied → bukmacher zawyża szanse → zły rynek dla gracza
    """
    results = {}
    for mkt, res_val, odds_col in [
        ("1",    "H", "odds_h"),
        ("X",    "D", "odds_d"),
        ("2",    "A", "odds_a"),
    ]:
        sub = df[["result", odds_col]].dropna() if odds_col in df.columns else pd.DataFrame()
        if sub.empty:
            continue

        sub = sub[sub[odds_col].between(1.01, 30.0)].copy()
        sub["implied"] = sub[odds_col].apply(_implied_prob)
        sub["actual"]  = (sub["result"] == res_val).astype(float)

        # Bins po implied probability
        sub["bin"] = pd.cut(sub["implied"], bins=n_bins)
        bins_data = []
        for b, g in sub.groupby("bin", observed=True):
            if len(g) < 20:
                continue
            bins_data.append({
                "implied_center": round(float(b.mid), 3),
                "actual_pct":     round(g["actual"].mean() * 100, 1),
                "implied_pct":    round(g["implied"].mean() * 100, 1),
                "n":              len(g),
                "edge":           round((g["actual"].mean() - g["implied"].mean()) * 100, 2),
            })
        results[mkt] = bins_data

    return results


# ─────────────────────────── 3. Forma ─────────────────────────────────────

def _compute_form(df: pd.DataFrame, n: int = 5) -> pd.DataFrame:
    """
    Oblicza formę obu drużyn przed każdym meczem (pkt z ost. N meczów).
    Zwraca df z kolumnami: form_home_pts, form_away_pts (0-15 dla n=5).
    """
    df = df.sort_values("date").copy()
    df["form_home_pts"] = np.nan
    df["form_away_pts"] = np.nan

    # Zbierz historię punktów per drużyna
    team_pts: dict[str, list[tuple]] = defaultdict(list)  # team → [(date, pts)]

    def _pts_from_result(result: str, is_home: bool) -> float:
        if result == "H":
            return 3.0 if is_home else 0.0
        if result == "A":
            return 0.0 if is_home else 3.0
        return 1.0  # remis

    form_home = []
    form_away = []

    for _, row in df.iterrows():
        h, a, d, res = row["home"], row["away"], row["date"], row["result"]

        # Forma przed meczem
        h_hist = [p for _, p in sorted(team_pts[h])[-n:]]
        a_hist = [p for _, p in sorted(team_pts[a])[-n:]]
        form_home.append(sum(h_hist) if h_hist else np.nan)
        form_away.append(sum(a_hist) if a_hist else np.nan)

        # Aktualizuj historię po meczu
        if isinstance(res, str) and res in ("H", "D", "A"):
            team_pts[h].append((d, _pts_from_result(res, True)))
            team_pts[a].append((d, _pts_from_result(res, False)))

    df["form_home_pts"] = form_home
    df["form_away_pts"] = form_away
    df["form_diff"]     = df["form_home_pts"] - df["form_away_pts"]
    return df


def analyze_form_vs_result(df: pd.DataFrame, n: int = 5) -> dict:
    """
    Dzieli mecze wg różnicy formy i liczy win rates.
    Zwraca: ile procent wygrała drużyna lepsza/gorsza w formie.
    """
    df_f = _compute_form(df, n).dropna(subset=["form_diff", "result"])

    bins = [
        ("dom_lepsza >9",  df_f["form_diff"] > 9),
        ("dom_lepsza 5-9", (df_f["form_diff"] >= 5) & (df_f["form_diff"] <= 9)),
        ("wyrównane 0-4",  df_f["form_diff"].abs() <= 4),
        ("gość_lepszy 5-9", (df_f["form_diff"] <= -5) & (df_f["form_diff"] >= -9)),
        ("gość_lepszy >9", df_f["form_diff"] < -9),
    ]

    result = {}
    for label, mask in bins:
        grp = df_f[mask]
        if len(grp) < 20:
            continue
        res = grp["result"].value_counts()
        n_grp = len(grp)
        result[label] = {
            "n":        n_grp,
            "home_win": _safe_pct(res.get("H", 0), n_grp),
            "draw":     _safe_pct(res.get("D", 0), n_grp),
            "away_win": _safe_pct(res.get("A", 0), n_grp),
        }
    return result


# ─────────────────────────── 4. Poisson – rozkład goli ───────────────────

def analyze_goals_distribution(df: pd.DataFrame) -> dict:
    """
    Porównuje rzeczywisty rozkład goli z rozkładem Poisson.
    Zwraca: lambda (avg gole), rozkład actual vs poisson, goodness of fit.
    """
    goals = df["total_goals"].dropna()
    if goals.empty:
        return {}

    lam = goals.mean()
    max_g = min(int(goals.max()), 10)

    from math import factorial, exp
    poisson_p = [exp(-lam) * lam**k / factorial(k) for k in range(max_g + 1)]
    actual_p  = [round((goals == k).mean(), 4) for k in range(max_g + 1)]

    # Mean Absolute Error
    mae = round(np.mean([abs(a - p) for a, p in zip(actual_p, poisson_p)]), 4)

    return {
        "lambda":        round(lam, 3),
        "poisson_fit_mae": mae,
        "actual_dist":   dict(enumerate(actual_p)),
        "poisson_dist":  dict(enumerate([round(p, 4) for p in poisson_p])),
        "over25_actual": round((goals > 2.5).mean() * 100, 1),
        "over25_poisson": round((1 - sum(poisson_p[:3])) * 100, 1),
    }


# ─────────────────────────── 5. Wzorce sezonowe ──────────────────────────

def analyze_seasonal_patterns(df: pd.DataFrame) -> dict:
    """
    Sprawdza czy jest różnica home/away win rate na początku vs końcu sezonu.
    Używa numeru kolejki (pozycja meczu w sezonie per liga).
    """
    if "season" not in df.columns or "league" not in df.columns:
        return {}

    out = {}
    for (league, season), grp in df.groupby(["league", "season"]):
        if len(grp) < 30:
            continue
        grp = grp.sort_values("date").reset_index(drop=True)
        mid = len(grp) // 2
        for label, part in [("early", grp.iloc[:mid]), ("late", grp.iloc[mid:])]:
            if len(part) < 10:
                continue
            res = part["result"].value_counts()
            n   = len(part)
            key = f"{league} {season}"
            if key not in out:
                out[key] = {}
            out[key][label] = {
                "home_win": _safe_pct(res.get("H", 0), n),
                "draw":     _safe_pct(res.get("D", 0), n),
                "away_win": _safe_pct(res.get("A", 0), n),
            }

    # Agreguj: czy jest trend early vs late?
    home_early = [v["early"]["home_win"] for v in out.values() if "early" in v and v["early"]["home_win"] is not None]
    home_late  = [v["late"]["home_win"]  for v in out.values() if "late" in v  and v["late"]["home_win"]  is not None]

    return {
        "seasons_analyzed": len(out),
        "avg_home_win_early": round(np.mean(home_early), 1) if home_early else None,
        "avg_home_win_late":  round(np.mean(home_late),  1) if home_late  else None,
        "trend": "home_stronger_early" if home_early and home_late and np.mean(home_early) > np.mean(home_late) else "no_trend",
    }


# ─────────────────────────── 6. Marchewki i Kije ─────────────────────────

def extract_marchewki_i_kije(
    results_by_league: dict,
    form_vs_result: dict,
    odds_calibration: dict,
) -> dict:
    """
    Na podstawie analizy generuje listę:
      - marchewki: silne sygnały które NAPRAWDĘ działają
      - kije: mity / pułapki typera
    """
    marchewki = []
    kije = []

    # Analiza home advantage
    for league, stats in results_by_league.items():
        if stats["home_win"] and stats["home_win"] > 48:
            marchewki.append(
                f"W {league}: dom wygrywa {stats['home_win']}% → silna marchewka dla '1'"
            )
        if stats["home_win"] and stats["home_win"] < 38:
            kije.append(
                f"W {league}: dom wygrywa tylko {stats['home_win']}% → uważaj na typ '1'"
            )
        if stats["over25_pct"] and stats["over25_pct"] > 60:
            marchewki.append(
                f"W {league}: Over 2.5 trafia {stats['over25_pct']}% → marchewka dla Over"
            )
        if stats["over25_pct"] and stats["over25_pct"] < 42:
            kije.append(
                f"W {league}: Over 2.5 tylko {stats['over25_pct']}% → kij dla Over, liga defensywna"
            )
        if stats["draw"] and stats["draw"] > 30:
            kije.append(
                f"W {league}: remisy {stats['draw']}% → unikaj '12' i podwójnych szans bez 'X'"
            )

    # Analiza formy
    for label, stats in form_vs_result.items():
        if "dom_lepsza >9" in label and stats.get("home_win", 0) and stats["home_win"] > 60:
            marchewki.append(
                f"Forma: gdy dom ma >9 pkt przewagi formy → wygrywa {stats['home_win']}% → marchewka"
            )
        if "wyrównane" in label and stats.get("draw", 0) and stats["draw"] > 30:
            marchewki.append(
                f"Forma wyrównana (diff 0-4 pkt): remisy częstsze ({stats['draw']}%) → rozważ X/1X/X2"
            )

    # Analiza kalibracji kursów
    for mkt, bins in odds_calibration.items():
        overpriced = [b for b in bins if b["edge"] < -3 and b["n"] > 50]
        underpriced = [b for b in bins if b["edge"] > 3 and b["n"] > 50]
        if overpriced:
            avg_edge = round(np.mean([b["edge"] for b in overpriced]), 1)
            kije.append(
                f"Rynek '{mkt}': przy implied ~{overpriced[0]['implied_pct']}%+ bukmacher zawyża o {abs(avg_edge)}% → kij (zły EV)"
            )
        if underpriced:
            avg_edge = round(np.mean([b["edge"] for b in underpriced]), 1)
            marchewki.append(
                f"Rynek '{mkt}': przy implied ~{underpriced[0]['implied_pct']}% actual wyższy o {avg_edge}% → marchewka (pozytywny EV)"
            )

    return {"marchewki": marchewki, "kije": kije}


# ─────────────────────────── główna analiza ───────────────────────────────

def analyze_all(df: pd.DataFrame, league_filter: list[str] | None = None) -> dict:
    """
    Uruchamia pełną analizę wzorców.
    league_filter: opcjonalnie ogranicz do podanych lig (np. ["NED-Eredivisie", "POL-Ekstraklasa"])
    """
    if league_filter:
        df = df[df["league"].isin(league_filter)].copy()

    if df.empty:
        return {}

    print(f"[PatternAnalyzer] Analizuje {len(df):,} meczow...")

    results_by_league = analyze_results_by_league(df)
    print(f"  -> {len(results_by_league)} lig z wystarczajaca liczba meczow")

    odds_cal = analyze_odds_calibration(df)
    print(f"  -> kalibracja kursow: {list(odds_cal.keys())} rynki")

    form_res = analyze_form_vs_result(df)
    print(f"  -> analiza formy: {len(form_res)} przedzialow")

    goals_dist = analyze_goals_distribution(df)
    print(f"  -> rozklad goli: lambda={goals_dist.get('lambda', '?')}, MAE Poisson={goals_dist.get('poisson_fit_mae', '?')}")

    seasonal = analyze_seasonal_patterns(df)

    marchewki_kije = extract_marchewki_i_kije(results_by_league, form_res, odds_cal)
    print(f"  -> marchewki: {len(marchewki_kije['marchewki'])}, kije: {len(marchewki_kije['kije'])}")

    return {
        "total_matches":    len(df),
        "leagues":          sorted(df["league"].unique().tolist()),
        "date_range":       (str(df["date"].min())[:10], str(df["date"].max())[:10]),
        "results_by_league": results_by_league,
        "odds_calibration":  odds_cal,
        "form_vs_result":    form_res,
        "goals_distribution": goals_dist,
        "seasonal_patterns": seasonal,
        "marchewki_i_kije":  marchewki_kije,
    }


# ─────────────────────────── formatowanie raportu ─────────────────────────

def format_report(analysis: dict, top_n: int = 5) -> str:
    """Formatuje wyniki analizy do czytelnego tekstu (do promptu Groq lub terminala)."""
    lines = []
    lines.append("=" * 65)
    lines.append("  RAPORT ANALIZY HISTORYCZNEJ – FootStats Pattern Analyzer")
    lines.append("=" * 65)
    lines.append(f"  Meczów:     {analysis.get('total_matches', 0):,}")
    dr = analysis.get("date_range", ("?", "?"))
    lines.append(f"  Zakres dat: {dr[0]} → {dr[1]}")
    lines.append(f"  Ligi:       {', '.join(analysis.get('leagues', []))}")
    lines.append("")

    # Wyniki per liga
    lines.append("─── WIN RATES PER LIGA ───────────────────────────────────")
    for lg, s in sorted(analysis.get("results_by_league", {}).items()):
        lines.append(
            f"  {lg:<28} n={s['n']:>5}  "
            f"1={s['home_win']:>4}%  X={s['draw']:>4}%  2={s['away_win']:>4}%  "
            f"Avg={s['avg_goals']:>4}G  Over2.5={s['over25_pct']:>4}%  BTTS={s['btts_pct']:>4}%"
        )

    # Forma
    lines.append("")
    lines.append("─── FORMA vs WYNIK (ost. 5 meczów) ──────────────────────")
    for label, s in analysis.get("form_vs_result", {}).items():
        lines.append(
            f"  {label:<25} n={s['n']:>5}  "
            f"1={s['home_win']:>4}%  X={s['draw']:>4}%  2={s['away_win']:>4}%"
        )

    # Rozkład goli
    gd = analysis.get("goals_distribution", {})
    if gd:
        lines.append("")
        lines.append("─── ROZKŁAD GOLI ─────────────────────────────────────────")
        lines.append(f"  λ (avg gole/mecz) = {gd.get('lambda', '?')}")
        lines.append(f"  Poisson MAE       = {gd.get('poisson_fit_mae', '?')} (im mniejszy tym lepszy fit)")
        lines.append(f"  Over 2.5 actual   = {gd.get('over25_actual', '?')}%")
        lines.append(f"  Over 2.5 Poisson  = {gd.get('over25_poisson', '?')}%")

    # Marchewki i Kije
    mk = analysis.get("marchewki_i_kije", {})
    if mk.get("marchewki"):
        lines.append("")
        lines.append("─── MARCHEWKI (silne sygnały) ───────────────────────────")
        for m in mk["marchewki"][:top_n]:
            lines.append(f"  + {m}")

    if mk.get("kije"):
        lines.append("")
        lines.append("─── KIJE (mity / pułapki) ───────────────────────────────")
        for k in mk["kije"][:top_n]:
            lines.append(f"  - {k}")

    lines.append("")
    lines.append("=" * 65)
    return "\n".join(str(l) for l in lines)
