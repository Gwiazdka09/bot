"""
historical_loader.py – pobiera i normalizuje dane historyczne z trzech źródeł:
  1. football-data.co.uk  (CSV per sezon, Eredivisie + inne)
  2. football-data.co.uk  (nowy format "new/", Ekstraklasa)
  3. xgabora GitHub       (226k meczów 2000-2025 + Elo ratings)

Użycie:
    from footstats.data.historical_loader import download_all, load_cached

    df = download_all()          # pobiera i cache'uje
    df = load_cached()           # tylko z dysku (szybkie)
"""

import io
import logging
from pathlib import Path

import pandas as pd
import requests

log = logging.getLogger(__name__)

CACHE_DIR = Path(__file__).parents[3] / "data" / "hist_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

BASE_FDCO = "https://www.football-data.co.uk"

# Sezony do pobrania (format YYYY/YY → "2324")
FDCO_SEASONS = [
    "2526", "2425", "2324", "2223", "2122",
    "2021", "1920", "1819", "1718", "1617",
]

# Ligi z plików sezonowych (kod → (kod_pliku, nazwa_ligi))
FDCO_LEAGUES = {
    "N1":  "NED-Eredivisie",
    "D1":  "GER-Bundesliga",
    "E0":  "ENG-Premier League",
    "SP1": "ESP-La Liga",
    "I1":  "ITA-Serie A",
    "F1":  "FRA-Ligue 1",
}

# Ligi z nowego formatu (jeden plik zbiorczy z całą historią)
FDCO_NEW_LEAGUES = {
    "POL": "POL-Ekstraklasa",
    "AUT": "AUT-Bundesliga",
    "BEL": "BEL-First Division A",
    "SCO": "SCO-Premiership",
}

XGABORA_MATCHES_URL = (
    "https://raw.githubusercontent.com/xgabora/"
    "Club-Football-Match-Data-2000-2025/main/data/Matches.csv"
)
XGABORA_ELO_URL = (
    "https://raw.githubusercontent.com/xgabora/"
    "Club-Football-Match-Data-2000-2025/main/data/EloRatings.csv"
)


# ─────────────────────────── helpers ──────────────────────────────────────

def _get(url: str, timeout: int = 30) -> bytes | None:
    try:
        r = requests.get(url, timeout=timeout, headers={"User-Agent": "FootStats/3.0"})
        r.raise_for_status()
        return r.content
    except Exception as e:
        log.warning("HTTP error %s → %s", url, e)
        return None


def _parse_date(s: str) -> pd.Timestamp | None:
    for fmt in ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d", "%d.%m.%Y"):
        try:
            return pd.to_datetime(s, format=fmt)
        except (ValueError, TypeError):
            pass
    return pd.NaT


# ─────────────────────────── FDCO sezonowy ────────────────────────────────

def _download_fdco_season(league_code: str, season: str) -> pd.DataFrame | None:
    url = f"{BASE_FDCO}/mmz4281/{season}/{league_code}.csv"
    raw = _get(url)
    if raw is None:
        return None
    try:
        df = pd.read_csv(io.BytesIO(raw), encoding="latin-1", on_bad_lines="skip")
    except Exception as e:
        log.warning("Błąd parsowania %s: %s", url, e)
        return None
    if df.empty or "HomeTeam" not in df.columns:
        return None

    # Normalizacja → wspólny schemat
    out = pd.DataFrame()
    out["date"]    = df["Date"].apply(_parse_date)
    out["league"]  = FDCO_LEAGUES.get(league_code, league_code)
    out["season"]  = f"20{season[:2]}/{season[2:]}"
    out["home"]    = df["HomeTeam"].str.strip()
    out["away"]    = df["AwayTeam"].str.strip()
    out["hg"]      = pd.to_numeric(df.get("FTHG", df.get("HG")), errors="coerce")
    out["ag"]      = pd.to_numeric(df.get("FTAG", df.get("AG")), errors="coerce")
    out["result"]  = df.get("FTR", df.get("Res", ""))
    out["ht_hg"]   = pd.to_numeric(df.get("HTHG", pd.Series(dtype=float)), errors="coerce")
    out["ht_ag"]   = pd.to_numeric(df.get("HTAG", pd.Series(dtype=float)), errors="coerce")
    out["hs"]      = pd.to_numeric(df.get("HS"),  errors="coerce")
    out["as_"]     = pd.to_numeric(df.get("AS"),  errors="coerce")
    out["hst"]     = pd.to_numeric(df.get("HST"), errors="coerce")
    out["ast"]     = pd.to_numeric(df.get("AST"), errors="coerce")
    out["hc"]      = pd.to_numeric(df.get("HC"),  errors="coerce")
    out["ac"]      = pd.to_numeric(df.get("AC"),  errors="coerce")
    out["hy"]      = pd.to_numeric(df.get("HY"),  errors="coerce")
    out["ay"]      = pd.to_numeric(df.get("AY"),  errors="coerce")

    # Kursy – preferuj Bet365, fallback na Average
    for h_col, d_col, a_col in [
        ("B365H", "B365D", "B365A"),
        ("BbAvH", "BbAvD", "BbAvA"),
        ("AvgH",  "AvgD",  "AvgA"),
        ("WHH",   "WHD",   "WHA"),
    ]:
        if h_col in df.columns:
            out["odds_h"] = pd.to_numeric(df[h_col], errors="coerce")
            out["odds_d"] = pd.to_numeric(df[d_col], errors="coerce")
            out["odds_a"] = pd.to_numeric(df[a_col], errors="coerce")
            break

    # Over 2.5
    for oh, ou in [("B365>2.5", "B365<2.5"), ("BbAv>2.5", "BbAv<2.5"), ("Avg>2.5", "Avg<2.5")]:
        if oh in df.columns:
            out["odds_over25"]  = pd.to_numeric(df[oh], errors="coerce")
            out["odds_under25"] = pd.to_numeric(df[ou], errors="coerce")
            break

    out["source"] = "fdco_season"
    return out.dropna(subset=["home", "away", "hg", "ag"])


def download_fdco_seasons(
    leagues: list[str] | None = None,
    seasons: list[str] | None = None,
) -> pd.DataFrame:
    """Pobiera ligi sezonowe z football-data.co.uk."""
    leagues = leagues or list(FDCO_LEAGUES.keys())
    seasons = seasons or FDCO_SEASONS
    frames = []
    for lg in leagues:
        for s in seasons:
            cache_f = CACHE_DIR / f"fdco_{lg}_{s}.parquet"
            if cache_f.exists():
                frames.append(pd.read_parquet(cache_f))
                continue
            df = _download_fdco_season(lg, s)
            if df is not None and not df.empty:
                df.to_parquet(cache_f, index=False)
                frames.append(df)
                log.info("Pobrano %s %s → %d meczów", lg, s, len(df))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


# ─────────────────────────── FDCO new format ──────────────────────────────

def _download_fdco_new(country_code: str) -> pd.DataFrame | None:
    url = f"{BASE_FDCO}/new/{country_code}.csv"
    raw = _get(url)
    if raw is None:
        return None
    try:
        df = pd.read_csv(io.BytesIO(raw), encoding="latin-1", on_bad_lines="skip")
    except Exception as e:
        log.warning("Błąd parsowania %s: %s", url, e)
        return None
    if df.empty or "Home" not in df.columns:
        return None

    out = pd.DataFrame()
    out["date"]    = df["Date"].apply(_parse_date)
    out["league"]  = FDCO_NEW_LEAGUES.get(country_code, country_code)
    out["season"]  = df.get("Season", "").astype(str)
    out["home"]    = df["Home"].str.strip()
    out["away"]    = df["Away"].str.strip()
    out["hg"]      = pd.to_numeric(df.get("HG"), errors="coerce")
    out["ag"]      = pd.to_numeric(df.get("AG"), errors="coerce")
    out["result"]  = df.get("Res", "")

    # Kursy (format "new" używa B365CH/B365CD/B365CA lub AvgCH itd.)
    for h_col, d_col, a_col in [
        ("B365CH", "B365CD", "B365CA"),
        ("AvgCH",  "AvgCD",  "AvgCA"),
        ("MaxCH",  "MaxCD",  "MaxCA"),
    ]:
        if h_col in df.columns:
            out["odds_h"] = pd.to_numeric(df[h_col], errors="coerce")
            out["odds_d"] = pd.to_numeric(df[d_col], errors="coerce")
            out["odds_a"] = pd.to_numeric(df[a_col], errors="coerce")
            break

    out["source"] = "fdco_new"
    return out.dropna(subset=["home", "away", "hg", "ag"])


def download_fdco_new(countries: list[str] | None = None) -> pd.DataFrame:
    """Pobiera historię ligową z nowego formatu football-data.co.uk."""
    countries = countries or list(FDCO_NEW_LEAGUES.keys())
    frames = []
    for cc in countries:
        cache_f = CACHE_DIR / f"fdco_new_{cc}.parquet"
        # Plik new/ jest aktualizowany, trzymaj max 1 dzień cache
        if cache_f.exists():
            age_h = (pd.Timestamp.now() - pd.Timestamp(cache_f.stat().st_mtime, unit="s")).total_seconds() / 3600
            if age_h < 24:
                frames.append(pd.read_parquet(cache_f))
                continue
        df = _download_fdco_new(cc)
        if df is not None and not df.empty:
            df.to_parquet(cache_f, index=False)
            frames.append(df)
            log.info("Pobrano fdco_new %s → %d meczów", cc, len(df))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


# ─────────────────────────── xgabora ──────────────────────────────────────

def _download_xgabora_matches() -> pd.DataFrame | None:
    cache_f = CACHE_DIR / "xgabora_matches.parquet"
    if cache_f.exists():
        age_days = (pd.Timestamp.now() - pd.Timestamp(cache_f.stat().st_mtime, unit="s")).total_seconds() / 86400
        if age_days < 7:
            return pd.read_parquet(cache_f)

    raw = _get(XGABORA_MATCHES_URL, timeout=60)
    if raw is None:
        return None
    try:
        df = pd.read_csv(io.BytesIO(raw), encoding="utf-8", on_bad_lines="skip", low_memory=False)
    except Exception as e:
        log.warning("Błąd xgabora matches: %s", e)
        return None
    if df.empty:
        return None

    log.info("xgabora MATCHES raw kolumny: %s", df.columns.tolist())
    df.to_parquet(cache_f, index=False)
    return df


def _download_xgabora_elo() -> pd.DataFrame | None:
    cache_f = CACHE_DIR / "xgabora_elo.parquet"
    if cache_f.exists():
        age_days = (pd.Timestamp.now() - pd.Timestamp(cache_f.stat().st_mtime, unit="s")).total_seconds() / 86400
        if age_days < 7:
            return pd.read_parquet(cache_f)

    raw = _get(XGABORA_ELO_URL, timeout=60)
    if raw is None:
        return None
    try:
        df = pd.read_csv(io.BytesIO(raw), encoding="utf-8", on_bad_lines="skip", low_memory=False)
    except Exception as e:
        log.warning("Błąd xgabora elo: %s", e)
        return None
    if df.empty:
        return None

    df.to_parquet(cache_f, index=False)
    return df


def normalize_xgabora(df: pd.DataFrame) -> pd.DataFrame:
    """Normalizuje xgabora Matches.csv do wspólnego schematu.
    Kolumny: Division, MatchDate, HomeTeam, AwayTeam, FTHome, FTAway,
             FTResult, HomeElo, AwayElo, Form3Home/5, OddHome/Draw/Away,
             Over25, Under25, HomeShots, AwayShots itd.
    """
    out = pd.DataFrame()
    out["date"]    = pd.to_datetime(df["MatchDate"], errors="coerce")
    out["league"]  = df["Division"].astype(str).str.strip()
    out["home"]    = df["HomeTeam"].astype(str).str.strip()
    out["away"]    = df["AwayTeam"].astype(str).str.strip()
    out["hg"]      = pd.to_numeric(df["FTHome"],  errors="coerce")
    out["ag"]      = pd.to_numeric(df["FTAway"],  errors="coerce")
    out["result"]  = df["FTResult"].astype(str).str.strip()
    out["ht_hg"]   = pd.to_numeric(df.get("HTHome"), errors="coerce")
    out["ht_ag"]   = pd.to_numeric(df.get("HTAway"), errors="coerce")
    out["hs"]      = pd.to_numeric(df.get("HomeShots"),  errors="coerce")
    out["as_"]     = pd.to_numeric(df.get("AwayShots"),  errors="coerce")
    out["hst"]     = pd.to_numeric(df.get("HomeTarget"), errors="coerce")
    out["ast"]     = pd.to_numeric(df.get("AwayTarget"), errors="coerce")
    out["hc"]      = pd.to_numeric(df.get("HomeCorners"), errors="coerce")
    out["ac"]      = pd.to_numeric(df.get("AwayCorners"), errors="coerce")
    out["hy"]      = pd.to_numeric(df.get("HomeYellow"), errors="coerce")
    out["ay"]      = pd.to_numeric(df.get("AwayYellow"), errors="coerce")
    out["odds_h"]  = pd.to_numeric(df.get("OddHome"),  errors="coerce")
    out["odds_d"]  = pd.to_numeric(df.get("OddDraw"),  errors="coerce")
    out["odds_a"]  = pd.to_numeric(df.get("OddAway"),  errors="coerce")
    out["odds_over25"]  = pd.to_numeric(df.get("Over25"),   errors="coerce")
    out["odds_under25"] = pd.to_numeric(df.get("Under25"),  errors="coerce")
    out["elo_home"] = pd.to_numeric(df.get("HomeElo"), errors="coerce")
    out["elo_away"] = pd.to_numeric(df.get("AwayElo"), errors="coerce")
    # Forma (punkty z ost. 3/5 meczów — gotowe z datasetu)
    out["form3_home"] = pd.to_numeric(df.get("Form3Home"), errors="coerce")
    out["form5_home"] = pd.to_numeric(df.get("Form5Home"), errors="coerce")
    out["form3_away"] = pd.to_numeric(df.get("Form3Away"), errors="coerce")
    out["form5_away"] = pd.to_numeric(df.get("Form5Away"), errors="coerce")
    out["source"] = "xgabora"
    return out.dropna(subset=["home", "away", "hg", "ag"])


def download_xgabora() -> pd.DataFrame:
    """Pobiera i normalizuje xgabora dataset."""
    raw = _download_xgabora_matches()
    if raw is None or raw.empty:
        return pd.DataFrame()
    return normalize_xgabora(raw)


# ─────────────────────────── soccerdata / FBref (xG) ─────────────────────

# Mapowanie naszych nazw lig na formaty soccerdata/FBref
_FBREF_LEAGUE_MAP: dict[str, str] = {
    "ENG-Premier League": "ENG-Premier League",
    "GER-Bundesliga":     "GER-Bundesliga",
    "ESP-La Liga":        "ESP-La Liga",
    "ITA-Serie A":        "ITA-Serie A",
    "FRA-Ligue 1":        "FRA-Ligue 1",
    "NED-Eredivisie":     "NED-Eredivisie",
    # Skróty alternatywne
    "Premier League":     "ENG-Premier League",
    "Bundesliga":         "GER-Bundesliga",
    "La Liga":            "ESP-La Liga",
    "Serie A":            "ITA-Serie A",
    "Ligue 1":            "FRA-Ligue 1",
    "Eredivisie":         "NED-Eredivisie",
}

FBREF_DEFAULT_LEAGUES = list(_FBREF_LEAGUE_MAP.values())[:6]
FBREF_DEFAULT_SEASONS = ["2024", "2023", "2022"]


def _download_fbref_one(league: str, season: str) -> pd.DataFrame | None:
    """
    Pobiera xG z FBref dla jednej ligi/sezonu przez soccerdata.
    Zwraca DataFrame z kolumnami: date, league, home, away, xg_home, xg_away.
    Zwraca None jeśli brak soccerdata lub błąd.
    """
    try:
        import soccerdata as sd  # type: ignore
    except ImportError:
        log.debug("soccerdata niedostępne (pip install soccerdata)")
        return None

    fbref_league = _FBREF_LEAGUE_MAP.get(league, league)
    cache_f = CACHE_DIR / f"fbref_{fbref_league.replace(' ', '_').replace('-', '_')}_{season}.parquet"
    if cache_f.exists():
        age_days = (
            pd.Timestamp.now() - pd.Timestamp(cache_f.stat().st_mtime, unit="s")
        ).total_seconds() / 86400
        if age_days < 30:  # FBref dane historyczne — cache 30 dni
            return pd.read_parquet(cache_f)

    try:
        fbref = sd.FBref(leagues=fbref_league, seasons=int(season))
        sched = fbref.read_schedule()
    except Exception as e:
        log.warning("FBref schedule error %s %s: %s", league, season, e)
        return None

    if sched is None or sched.empty:
        return None

    # Spłaszcz MultiIndex (soccerdata zwraca go w niektórych wersjach)
    if isinstance(sched.index, pd.MultiIndex):
        sched = sched.reset_index()
    else:
        sched = sched.reset_index()

    # Normalizuj nazwy kolumn (soccerdata zmienia je między wersjami)
    cols = {c.lower(): c for c in sched.columns}

    def _col(*candidates: str) -> str | None:
        for c in candidates:
            if c in cols:
                return cols[c]
        return None

    date_col  = _col("date")
    home_col  = _col("home_team", "home", "hometeam")
    away_col  = _col("away_team", "away", "awayteam")
    xgh_col   = _col("home_xg", "xg_home", "xgh", "home_xgoals")
    xga_col   = _col("away_xg", "xg_away", "xga", "away_xgoals")

    if not date_col or not home_col or not away_col:
        log.warning("FBref: brak kluczowych kolumn w %s %s. Dostępne: %s",
                    league, season, list(sched.columns))
        return None

    out = pd.DataFrame()
    out["date"]    = pd.to_datetime(sched[date_col], errors="coerce")
    out["league"]  = fbref_league
    out["home"]    = sched[home_col].astype(str).str.strip()
    out["away"]    = sched[away_col].astype(str).str.strip()
    out["xg_home"] = pd.to_numeric(sched[xgh_col], errors="coerce") if xgh_col else pd.NA
    out["xg_away"] = pd.to_numeric(sched[xga_col], errors="coerce") if xga_col else pd.NA
    out["source_xg"] = "fbref"

    out = out.dropna(subset=["date", "home", "away"])
    out = out[out["xg_home"].notna() | out["xg_away"].notna()]

    if out.empty:
        log.warning("FBref %s %s: brak danych xG (schedule nie zawiera home_xg/away_xg)", league, season)
        # Spróbuj pobrać ze statystyk strzeleckich
        out = _try_fbref_shooting(fbref, fbref_league, sched, date_col, home_col, away_col)

    if out is not None and not out.empty:
        out.to_parquet(cache_f, index=False)
        log.info("FBref xG %s %s -> %d meczów", league, season, len(out))
    return out if out is not None and not out.empty else None


def _try_fbref_shooting(fbref, league: str, sched, date_col, home_col, away_col) -> pd.DataFrame | None:
    """Fallback: pobierz xG ze statystyk drużynowych jeśli nie ma w schedule."""
    try:
        shots = fbref.read_team_match_stats(stat_type="shooting")
    except Exception as e:
        log.debug("FBref shooting fallback error: %s", e)
        return None

    if shots is None or shots.empty:
        return None

    # Statystyki shooting mają MultiIndex (team, game_id) lub (game_id, team)
    shots_flat = shots.reset_index()
    scols = {c.lower(): c for c in shots_flat.columns}

    xg_col = next((shots_flat.columns[i] for i, c in enumerate(shots_flat.columns)
                   if c.lower() in ("xg", "expected_goals", "xgoals")), None)
    team_col = next((shots_flat.columns[i] for i, c in enumerate(shots_flat.columns)
                     if c.lower() in ("team", "squad")), None)

    if xg_col is None or team_col is None:
        return None

    # Połącz schedule ze strzałami per mecz/drużyna
    sched_flat = sched.reset_index()
    game_col = next((c for c in shots_flat.columns if c.lower() in ("game", "game_id", "match_id")), None)
    sched_game_col = next((c for c in sched_flat.columns if c.lower() in ("game", "game_id")), None)

    if game_col and sched_game_col:
        merged = sched_flat.merge(shots_flat[[game_col, team_col, xg_col]], on=game_col, how="left")
        # Pivot home/away xG
        home_xg = merged[merged[team_col] == merged[home_col]][[sched_game_col, xg_col]].rename(
            columns={xg_col: "xg_home"})
        away_xg = merged[merged[team_col] == merged[away_col]][[sched_game_col, xg_col]].rename(
            columns={xg_col: "xg_away"})
        out2 = sched_flat[[date_col, home_col, away_col]].copy()
        out2["league"] = league
        out2["xg_home"] = home_xg["xg_home"].values if len(home_xg) == len(out2) else pd.NA
        out2["xg_away"] = away_xg["xg_away"].values if len(away_xg) == len(out2) else pd.NA
        out2 = out2.rename(columns={date_col: "date", home_col: "home", away_col: "away"})
        out2["source_xg"] = "fbref_shooting"
        return out2.dropna(subset=["date", "home", "away"])
    return None


def download_fbref_xg(
    leagues: list[str] | None = None,
    seasons: list[str] | None = None,
) -> pd.DataFrame:
    """
    Pobiera xG z FBref dla wielu lig i sezonów.
    Wymaga: pip install soccerdata

    Zwraca DataFrame z kolumnami: date, league, home, away, xg_home, xg_away
    """
    leagues = leagues or FBREF_DEFAULT_LEAGUES
    seasons = seasons or FBREF_DEFAULT_SEASONS
    frames  = []

    for lg in leagues:
        for s in seasons:
            df = _download_fbref_one(lg, s)
            if df is not None and not df.empty:
                frames.append(df)

    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def merge_xg_into_dataset(df_main: pd.DataFrame, df_xg: pd.DataFrame) -> pd.DataFrame:
    """
    Wzbogaca główny DataFrame o kolumny xg_home i xg_away z FBref.

    Dopasowanie po: league + home + away + date (tolerancja ±1 dzień).
    Tylko mecze które już mają xg_home=NaN dostają uzupełnienie.
    """
    if df_xg.empty or df_main.empty:
        return df_main

    # Normalizuj daty
    df_xg = df_xg.copy()
    df_xg["date"] = pd.to_datetime(df_xg["date"], errors="coerce")
    df_main = df_main.copy()

    if "xg_home" not in df_main.columns:
        df_main["xg_home"] = pd.NA
    if "xg_away" not in df_main.columns:
        df_main["xg_away"] = pd.NA

    # Indeks xG: (home_lower, away_lower, date_str)
    xg_map: dict[tuple, tuple[float, float]] = {}
    for _, r in df_xg.iterrows():
        if pd.isna(r.get("xg_home")) and pd.isna(r.get("xg_away")):
            continue
        key = (
            str(r["home"]).lower()[:12],
            str(r["away"]).lower()[:12],
            str(r["date"])[:10],
        )
        xg_map[key] = (r.get("xg_home"), r.get("xg_away"))

    def _lookup(row):
        h = str(row["home"]).lower()[:12]
        a = str(row["away"]).lower()[:12]
        d = str(row["date"])[:10]
        # Dokładne dopasowanie
        v = xg_map.get((h, a, d))
        if v:
            return pd.Series({"xg_home": v[0], "xg_away": v[1]})
        # ±1 dzień
        for offset in (-1, 1):
            try:
                d2 = (pd.Timestamp(d) + pd.Timedelta(days=offset)).strftime("%Y-%m-%d")
                v = xg_map.get((h, a, d2))
                if v:
                    return pd.Series({"xg_home": v[0], "xg_away": v[1]})
            except Exception:
                pass
        return pd.Series({"xg_home": pd.NA, "xg_away": pd.NA})

    # Uzupełnij tylko wiersze bez xG
    mask = df_main["xg_home"].isna()
    if mask.any():
        updates = df_main[mask].apply(_lookup, axis=1)
        df_main.loc[mask, "xg_home"] = updates["xg_home"].values
        df_main.loc[mask, "xg_away"] = updates["xg_away"].values

    n_filled = df_main["xg_home"].notna().sum()
    log.info("xG uzupełnione: %d meczów", n_filled)
    return df_main


# ─────────────────────────── główna funkcja ───────────────────────────────

def download_all(
    fdco_leagues: list[str] | None = None,
    fdco_seasons: list[str] | None = None,
    fdco_new_countries: list[str] | None = None,
    include_xgabora: bool = True,
    include_xg: bool = False,
    xg_leagues: list[str] | None = None,
    xg_seasons: list[str] | None = None,
) -> pd.DataFrame:
    """
    Pobiera dane ze wszystkich źródeł i łączy w jeden DataFrame.
    Domyślnie: Eredivisie (10 sezonów) + Ekstraklasa + xgabora.
    """
    frames = []

    print("[HistLoader] Pobieram football-data.co.uk (sezony)...")
    df_fdco = download_fdco_seasons(
        leagues=fdco_leagues or ["N1"],
        seasons=fdco_seasons or FDCO_SEASONS,
    )
    if not df_fdco.empty:
        print(f"  -> {len(df_fdco)} meczow (fdco_season)")
        frames.append(df_fdco)

    print("[HistLoader] Pobieram football-data.co.uk (nowy format)...")
    df_new = download_fdco_new(countries=fdco_new_countries or ["POL"])
    if not df_new.empty:
        print(f"  -> {len(df_new)} meczow (fdco_new)")
        frames.append(df_new)

    if include_xgabora:
        print("[HistLoader] Pobieram xgabora dataset (226k meczow)...")
        df_xgab = download_xgabora()
        if not df_xgab.empty:
            print(f"  -> {len(df_xgab)} meczow (xgabora)")
            frames.append(df_xgab)

    if not frames:
        return pd.DataFrame()

    df = pd.concat(frames, ignore_index=True)
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date", "home", "away"])
    df = df.sort_values("date").reset_index(drop=True)

    # Totale
    df["total_goals"] = df["hg"] + df["ag"]
    df["over25"]  = (df["total_goals"] > 2.5).astype(float)
    df["over15"]  = (df["total_goals"] > 1.5).astype(float)
    df["btts"]    = ((df["hg"] > 0) & (df["ag"] > 0)).astype(float)

    # Opcjonalne: xG z FBref
    if include_xg:
        print("[HistLoader] Pobieram xG z FBref (soccerdata)...")
        df_xg = download_fbref_xg(
            leagues=xg_leagues or FBREF_DEFAULT_LEAGUES,
            seasons=xg_seasons or FBREF_DEFAULT_SEASONS,
        )
        if not df_xg.empty:
            n_before = df["xg_home"].notna().sum() if "xg_home" in df.columns else 0
            df = merge_xg_into_dataset(df, df_xg)
            n_after = df["xg_home"].notna().sum()
            print(f"  -> xG uzupelnione: {n_after - n_before} meczow")
        else:
            print("  -> brak danych xG (soccerdata niedostepne lub brak polaczenia)")

    # Cache pełny dataset
    out_f = CACHE_DIR / "full_dataset.parquet"
    df.to_parquet(out_f, index=False)
    print(f"\n[HistLoader] Lacznie: {len(df):,} meczow -> zapisano do {out_f}")
    return df


def load_cached() -> pd.DataFrame:
    """Wczytuje pełny dataset z dysku (bez pobierania)."""
    f = CACHE_DIR / "full_dataset.parquet"
    if not f.exists():
        raise FileNotFoundError(f"Brak cache. Uruchom najpierw download_all(). Szukałem w: {f}")
    return pd.read_parquet(f)
