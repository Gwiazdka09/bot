"""
backtest.py – SQLite baza do śledzenia skuteczności typów AI FootStats

Użycie CLI:
    python -m footstats.core.backtest stats              → statystyki ostatnich 30 dni
    python -m footstats.core.backtest stats 90           → statystyki ostatnich 90 dni
    python -m footstats.core.backtest pending            → mecze bez wpisanego wyniku
    python -m footstats.core.backtest update 42 "2-1"   → wpisz wynik do rekordu ID=42
    python -m footstats.core.backtest weakness           → raport słabych punktów

Użycie jako moduł:
    from footstats.core.backtest import save_prediction, update_result, get_stats
"""

import json
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

from footstats.config import DB_PATH
from footstats.utils.betting import oblicz_tip_correct  # noqa: E402 (shared utility)

try:
    from tabulate import tabulate
    HAS_TABULATE = True
except ImportError:
    HAS_TABULATE = False
    def tabulate(rows, headers=(), tablefmt="simple", **kw):
        lines = []
        if headers:
            lines.append("  ".join(str(h).ljust(14) for h in headers))
            lines.append("-" * (16 * len(headers)))
        for row in rows:
            lines.append("  ".join(str(c).ljust(14) for c in row))
        return "\n".join(lines)

# DB w katalogu zdefiniowanym w config.py
# DB_PATH jest teraz importowane z footstats.config


# ── Inicjalizacja ─────────────────────────────────────────────────────────

def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    """Tworzy tabele jeśli nie istnieją. Bezpieczne przy wielokrotnym wywołaniu."""
    with _connect() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS predictions (
                id                   INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at           TEXT    NOT NULL DEFAULT (datetime('now')),
                match_date           TEXT    NOT NULL,
                team_home            TEXT    NOT NULL,
                team_away            TEXT    NOT NULL,
                league               TEXT    NOT NULL DEFAULT '',
                ai_tip               TEXT    NOT NULL,
                ai_confidence        INTEGER NOT NULL CHECK(ai_confidence BETWEEN 0 AND 100),
                ai_reasoning         TEXT    NOT NULL DEFAULT '',
                odds                 REAL,
                actual_result        TEXT,
                tip_correct          INTEGER CHECK(tip_correct IN (0, 1, NULL)),
                kupon_type           TEXT    DEFAULT '',
                kodeks_rules_checked TEXT    NOT NULL DEFAULT '[]',
                prompt_version       TEXT    NOT NULL DEFAULT '',
                factors              TEXT    NOT NULL DEFAULT '[]',
                match_stats          TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_match_date   ON predictions(match_date);
            CREATE INDEX IF NOT EXISTS idx_tip_correct  ON predictions(tip_correct);
            CREATE INDEX IF NOT EXISTS idx_kupon_type   ON predictions(kupon_type);
            CREATE INDEX IF NOT EXISTS idx_league       ON predictions(league);
        """)
        # Migration: factors column dla istniejących DB
        try:
            conn.execute("ALTER TABLE predictions ADD COLUMN match_stats TEXT")
        except sqlite3.OperationalError:
            pass

        # Tabela feedbacku AI (analiza porażek)
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS ai_feedback (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                match_id            INTEGER NOT NULL REFERENCES predictions(id),
                prediction_details  TEXT    NOT NULL DEFAULT '{}',
                reason_for_failure  TEXT    NOT NULL DEFAULT '',
                created_at          TEXT    NOT NULL DEFAULT (datetime('now'))
            );
            CREATE INDEX IF NOT EXISTS idx_ai_feedback_match ON ai_feedback(match_id);
            CREATE INDEX IF NOT EXISTS idx_ai_feedback_date  ON ai_feedback(created_at);
        """)


# ── 1. save_prediction ────────────────────────────────────────────────────

def save_prediction(
    match_date:           str,
    team_home:            str,
    team_away:            str,
    ai_tip:               str,
    ai_confidence:        int,
    league:               str  = "",
    ai_reasoning:         str  = "",
    odds:                 float | None = None,
    kupon_type:           str  = "",
    kodeks_rules_checked: list = None,
    prompt_version:       str  = "",
    factors:              list = None,
) -> int:
    """
    Zapisuje typ AI przed meczem. Zwraca id nowo utworzonego rekordu.
    """
    init_db()
    rules_json   = json.dumps(kodeks_rules_checked or [], ensure_ascii=False)
    factors_json = json.dumps(factors or [], ensure_ascii=False)

    with _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO predictions
                (match_date, team_home, team_away, league,
                 ai_tip, ai_confidence, ai_reasoning, odds,
                 kupon_type, kodeks_rules_checked, prompt_version, factors)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (match_date, team_home, team_away, league,
             ai_tip, ai_confidence, ai_reasoning, odds,
             kupon_type, rules_json, prompt_version, factors_json),
        )
        return cur.lastrowid


# ── 2. update_result ─────────────────────────────────────────────────────

def update_result(match_id: int, actual_result: str, match_stats: dict = None) -> dict:
    """
    Wpisuje wynik po meczu i automatycznie oblicza tip_correct.
    actual_result: np. "2-1", "0-0", "1", "X", "2"
    match_stats: opcjonalny słownik ze statystykami (xG, strzały itp.)
    """
    init_db()
    with _connect() as conn:
        row = conn.execute(
            "SELECT ai_tip, actual_result FROM predictions WHERE id = ?",
            (match_id,)
        ).fetchone()

        if not row:
            raise ValueError(f"Rekord ID={match_id} nie istnieje.")
        if row["actual_result"] is not None:
            print(f"[Backtest] Nadpisuję istniejący wynik (poprzedni: {row['actual_result']})")

        tip_correct = oblicz_tip_correct(row["ai_tip"], actual_result)

        conn.execute(
            "UPDATE predictions SET actual_result = ?, tip_correct = ?, match_stats = ? WHERE id = ?",
            (actual_result, tip_correct, json.dumps(match_stats or {}, ensure_ascii=False), match_id),
        )

    status = {None: "?? (nie obliczono)", 1: "TRAFIONY ✓", 0: "PUDŁO ✗"}
    info = {
        "id":            match_id,
        "actual_result": actual_result,
        "ai_tip":        row["ai_tip"],
        "tip_correct":   tip_correct,
        "status":        status[tip_correct],
    }
    _sprawdz_auto_trening()
    return info


# ── Auto-trening ──────────────────────────────────────────────────────────

AUTO_TRENING_CO_N = 20  # co ile nowych wyników odpala trening

def _sprawdz_auto_trening() -> None:
    """
    Sprawdza czy liczba ocenionych predykcji jest wielokrotnością AUTO_TRENING_CO_N.
    Jeśli tak — odpala trainer.py w tle i wysyła Telegram z nową kalibracją.
    """
    try:
        with _connect() as conn:
            n = conn.execute(
                "SELECT COUNT(*) FROM predictions WHERE tip_correct IS NOT NULL"
            ).fetchone()[0]

        if n > 0 and n % AUTO_TRENING_CO_N == 0:
            import subprocess, sys
            subprocess.Popen(
                [sys.executable, "-m", "footstats.ai.trainer"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            print(f"[Backtest] Auto-trening uruchomiony (n={n} wynikow).")
            try:
                from footstats.utils.telegram_notify import _send, telegram_dostepny
                if telegram_dostepny():
                    _send(
                        f"FootStats Auto-trening\n"
                        f"Zapisano {n} wynikow — Groq aktualizuje kalibracje w tle."
                    )
            except Exception:
                pass
    except Exception:
        pass


# ── 3. get_stats ─────────────────────────────────────────────────────────

def get_stats(days: int = 30) -> dict:
    """Zwraca statystyki skuteczności za ostatnie N dni."""
    init_db()
    date_from = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    date_to   = datetime.now().strftime("%Y-%m-%d")

    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT ai_tip, ai_confidence, odds, league, kupon_type,
                   tip_correct, actual_result
            FROM predictions
            WHERE match_date >= ? AND match_date <= ?
            """,
            (date_from, date_to),
        ).fetchall()

    if not rows:
        return {
            "total_tips": 0, "evaluated": 0, "accuracy_pct": None,
            "roi_pct": None, "by_market": {}, "by_league": {},
            "by_kupon": {}, "by_confidence_band": {},
            "best_market": None, "worst_market": None, "best_league": None,
            "date_from": date_from, "date_to": date_to,
        }

    evaluated   = [r for r in rows if r["tip_correct"] is not None]
    correct     = [r for r in evaluated if r["tip_correct"] == 1]
    accuracy    = (len(correct) / len(evaluated) * 100) if evaluated else None

    roi_num = sum(
        (r["odds"] - 1) if r["tip_correct"] == 1 else -1
        for r in evaluated if r["odds"]
    )
    roi_den = sum(1 for r in evaluated if r["odds"])
    roi = (roi_num / roi_den * 100) if roi_den else None

    def _group_stats(key_fn):
        groups: dict[str, dict] = {}
        for r in evaluated:
            k = key_fn(r)
            if k not in groups:
                groups[k] = {"total": 0, "correct": 0, "odds_sum": 0.0, "odds_n": 0}
            groups[k]["total"]   += 1
            groups[k]["correct"] += r["tip_correct"]
            if r["odds"]:
                groups[k]["odds_sum"] += r["odds"]
                groups[k]["odds_n"]   += 1
        result = {}
        for k, v in groups.items():
            acc = round(v["correct"] / v["total"] * 100, 1) if v["total"] else None
            avg_odds = round(v["odds_sum"] / v["odds_n"], 2) if v["odds_n"] else None
            result[k] = {
                "total": v["total"], "correct": v["correct"],
                "accuracy_pct": acc, "avg_odds": avg_odds,
            }
        return result

    by_market = _group_stats(lambda r: r["ai_tip"])
    by_league = _group_stats(lambda r: r["league"] or "Nieznana")
    by_kupon  = _group_stats(lambda r: r["kupon_type"] or "Brak")

    def _conf_band(r):
        c = r["ai_confidence"]
        if c < 50:   return "0-49%"
        if c < 65:   return "50-64%"
        if c < 80:   return "65-79%"
        return "80-100%"

    by_conf = _group_stats(_conf_band)

    def _best_worst(group_dict):
        filtered = {k: v for k, v in group_dict.items() if v["total"] >= 3}
        if not filtered:
            return None, None
        best  = max(filtered, key=lambda k: filtered[k]["accuracy_pct"] or 0)
        worst = min(filtered, key=lambda k: filtered[k]["accuracy_pct"] or 100)
        return best, worst

    best_market, worst_market = _best_worst(by_market)
    best_league, _            = _best_worst(by_league)

    return {
        "total_tips":         len(rows),
        "evaluated":          len(evaluated),
        "correct":            len(correct),
        "accuracy_pct":       round(accuracy, 1) if accuracy is not None else None,
        "roi_pct":            round(roi, 1) if roi is not None else None,
        "by_market":          by_market,
        "by_league":          by_league,
        "by_kupon":           by_kupon,
        "by_confidence_band": by_conf,
        "best_market":        best_market,
        "worst_market":       worst_market,
        "best_league":        best_league,
        "date_from":          date_from,
        "date_to":            date_to,
    }


# ── 4. get_pending_results ────────────────────────────────────────────────

def get_pending_results() -> list[dict]:
    """Mecze bez wpisanego wyniku, sortowane malejąco po dacie."""
    init_db()
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT id, match_date, team_home, team_away, league,
                   ai_tip, ai_confidence, odds, kupon_type
            FROM predictions
            WHERE actual_result IS NULL
            ORDER BY match_date DESC
            """
        ).fetchall()
    return [dict(r) for r in rows]


# ── 5. get_weakness_report ────────────────────────────────────────────────

def get_weakness_report(min_samples: int = 3, days: int = 90) -> dict:
    """Analizuje słabe punkty: typy i ligi z najniższą skutecznością."""
    stats = get_stats(days=days)

    def _rank(group_dict, ascending=True) -> list[dict]:
        items = [
            {"name": k, **v}
            for k, v in group_dict.items()
            if v["total"] >= min_samples and v["accuracy_pct"] is not None
        ]
        return sorted(items, key=lambda x: x["accuracy_pct"], reverse=not ascending)

    init_db()
    date_from = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT odds, tip_correct
            FROM predictions
            WHERE match_date >= ? AND tip_correct IS NOT NULL AND odds IS NOT NULL
            """,
            (date_from,)
        ).fetchall()

    def _odds_band(odds: float) -> str:
        if odds < 1.5:   return "1.01–1.49"
        if odds < 2.0:   return "1.50–1.99"
        if odds < 2.5:   return "2.00–2.49"
        if odds < 3.5:   return "2.50–3.49"
        return "3.50+"

    odds_groups: dict[str, dict] = {}
    for r in rows:
        k = _odds_band(r["odds"])
        if k not in odds_groups:
            odds_groups[k] = {"total": 0, "correct": 0}
        odds_groups[k]["total"]   += 1
        odds_groups[k]["correct"] += r["tip_correct"]

    odds_bands = [
        {
            "name":         k,
            "total":        v["total"],
            "correct":      v["correct"],
            "accuracy_pct": round(v["correct"] / v["total"] * 100, 1),
        }
        for k, v in odds_groups.items() if v["total"] >= min_samples
    ]

    return {
        "weak_markets":   _rank(stats["by_market"], ascending=True)[:5],
        "strong_markets": _rank(stats["by_market"], ascending=False)[:5],
        "weak_leagues":   _rank(stats["by_league"], ascending=True)[:5],
        "strong_leagues": _rank(stats["by_league"], ascending=False)[:5],
        "odds_bands":     sorted(odds_bands, key=lambda x: x["name"]),
        "days_analyzed":  days,
    }


# ── 6. pobierz_kalibracje_backtest ───────────────────────────────────────

def pobierz_kalibracje_backtest(dni: int = 90, min_n: int = 5) -> str:
    """
    Zwraca sformatowany string kalibracji do wstrzyknięcia w prompt Groq.
    Przykład: "Over acc=73%(n=150) | 1 acc=58%(n=80) | BTTS acc=65%(n=40) | ROI=+4.2%"
    Zwraca pusty string jeśli brak danych lub za mało próbek.
    """
    try:
        stats = get_stats(days=dni)
    except Exception:
        return ""

    by_market = stats.get("by_market", {})
    ORDER = ["1", "X", "2", "1X", "X2", "12",
             "Over", "OVER 2.5", "Over 2.5", "Under", "UNDER 2.5", "Under 2.5",
             "BTTS", "BTTS NO"]

    rynki = sorted(
        [(k, v) for k, v in by_market.items() if v["total"] >= min_n],
        key=lambda x: ORDER.index(x[0]) if x[0] in ORDER else len(ORDER),
    )
    if not rynki:
        return ""

    czesci = [
        f"{rynek} acc={v['accuracy_pct']:.0f}%(n={v['total']})"
        for rynek, v in rynki
        if v["accuracy_pct"] is not None
    ]
    roi = stats.get("roi_pct")
    if roi is not None:
        czesci.append(f"ROI={roi:+.1f}%")

    return " | ".join(czesci)


# ── CLI ───────────────────────────────────────────────────────────────────

def _cli_stats(days: int = 30):
    s = get_stats(days)
    print(f"\n{'=' * 58}")
    print(f"  STATYSTYKI AI – ostatnie {days} dni  ({s['date_from']} → {s['date_to']})")
    print(f"{'=' * 58}")

    if s["total_tips"] == 0:
        print("  Brak danych w tym okresie.")
        return

    acc  = f"{s['accuracy_pct']}%" if s["accuracy_pct"] is not None else "—"
    roi  = f"{s['roi_pct']}%"      if s["roi_pct"]      is not None else "—"
    print(f"  Typy łącznie:  {s['total_tips']}")
    print(f"  Ocenione:      {s['evaluated']}  |  Trafione: {s.get('correct', 0)}")
    print(f"  Accuracy:      {acc}")
    print(f"  ROI:           {roi}")
    if s["best_market"]:
        print(f"  Najlepszy rynek:  {s['best_market']} ({s['by_market'][s['best_market']]['accuracy_pct']}%)")
    if s["worst_market"]:
        print(f"  Najsłabszy rynek: {s['worst_market']} ({s['by_market'][s['worst_market']]['accuracy_pct']}%)")
    if s["best_league"]:
        print(f"  Najlepsza liga:   {s['best_league']} ({s['by_league'][s['best_league']]['accuracy_pct']}%)")

    if s["by_market"]:
        print(f"\n  --- Rynki ---")
        rows = [
            (k, v["total"], v["correct"],
             f"{v['accuracy_pct']}%" if v["accuracy_pct"] is not None else "—",
             f"{v['avg_odds']}" if v["avg_odds"] else "—")
            for k, v in sorted(s["by_market"].items(),
                                key=lambda x: x[1]["accuracy_pct"] or 0,
                                reverse=True)
        ]
        print(tabulate(rows,
                       headers=["Rynek", "Łącznie", "Trafione", "Accuracy", "Avg odds"],
                       tablefmt="simple"))

    if s["by_confidence_band"]:
        print(f"\n  --- Pewność AI ---")
        rows = [
            (k, v["total"], v["correct"],
             f"{v['accuracy_pct']}%" if v["accuracy_pct"] is not None else "—")
            for k, v in sorted(s["by_confidence_band"].items())
        ]
        print(tabulate(rows,
                       headers=["Pasmo", "Łącznie", "Trafione", "Accuracy"],
                       tablefmt="simple"))

    if s["by_kupon"]:
        print(f"\n  --- Kupony ---")
        rows = [
            (k, v["total"], v["correct"],
             f"{v['accuracy_pct']}%" if v["accuracy_pct"] is not None else "—")
            for k, v in s["by_kupon"].items()
        ]
        print(tabulate(rows,
                       headers=["Kupon", "Łącznie", "Trafione", "Accuracy"],
                       tablefmt="simple"))
    print()


def _cli_pending():
    mecze = get_pending_results()
    print(f"\n{'=' * 68}")
    print(f"  MECZE BEZ WYNIKU ({len(mecze)} szt.)")
    print(f"{'=' * 68}")
    if not mecze:
        print("  Wszystko uzupełnione!")
    else:
        rows = [
            (m["id"], m["match_date"],
             f"{m['team_home']} vs {m['team_away']}",
             m["league"] or "—",
             m["ai_tip"],
             f"{m['ai_confidence']}%",
             m["odds"] or "—",
             m["kupon_type"] or "—")
            for m in mecze
        ]
        print(tabulate(rows,
                       headers=["ID", "Data", "Mecz", "Liga", "Typ", "Pew.", "Kurs", "Kupon"],
                       tablefmt="simple"))
        print(f"\n  Użyj: python -m footstats.core.backtest update <ID> <WYNIK>")
    print()


def _cli_update(match_id_str: str, actual_result: str):
    try:
        match_id = int(match_id_str)
    except ValueError:
        print(f"[Błąd] ID musi być liczbą całkowitą, otrzymano: {match_id_str!r}")
        sys.exit(1)
    try:
        info = update_result(match_id, actual_result)
    except ValueError as e:
        print(f"[Błąd] {e}")
        sys.exit(1)
    print(f"\n  Zaktualizowano ID={info['id']}")
    print(f"  Typ AI:         {info['ai_tip']}")
    print(f"  Wynik meczu:    {info['actual_result']}")
    print(f"  Status:         {info['status']}\n")


def _cli_weakness():
    r = get_weakness_report()
    print(f"\n{'=' * 58}")
    print(f"  RAPORT SŁABOŚCI – ostatnie {r['days_analyzed']} dni")
    print(f"{'=' * 58}")

    if r["weak_markets"]:
        print("\n  -- Najsłabsze rynki (min 3 typy) --")
        rows = [(x["name"], x["total"], x["correct"], f"{x['accuracy_pct']}%")
                for x in r["weak_markets"]]
        print(tabulate(rows, headers=["Rynek", "Łącznie", "Trafione", "Accuracy"],
                       tablefmt="simple"))

    if r["strong_markets"]:
        print("\n  -- Najmocniejsze rynki --")
        rows = [(x["name"], x["total"], x["correct"], f"{x['accuracy_pct']}%")
                for x in r["strong_markets"]]
        print(tabulate(rows, headers=["Rynek", "Łącznie", "Trafione", "Accuracy"],
                       tablefmt="simple"))

    if r["weak_leagues"]:
        print("\n  -- Najsłabsze ligi (min 3 typy) --")
        rows = [(x["name"], x["total"], x["correct"], f"{x['accuracy_pct']}%")
                for x in r["weak_leagues"]]
        print(tabulate(rows, headers=["Liga", "Łącznie", "Trafione", "Accuracy"],
                       tablefmt="simple"))

    if r["odds_bands"]:
        print("\n  -- Skuteczność wg pasma kursów --")
        rows = [(x["name"], x["total"], x["correct"], f"{x['accuracy_pct']}%")
                for x in r["odds_bands"]]
        print(tabulate(rows, headers=["Kurs", "Łącznie", "Trafione", "Accuracy"],
                       tablefmt="simple"))
    print()


def _cli_help():
    print("""
Użycie:
  python -m footstats.core.backtest stats [dni]          — statystyki (domyślnie 30 dni)
  python -m footstats.core.backtest pending              — mecze bez wpisanego wyniku
  python -m footstats.core.backtest update <ID> <wynik>  — wpisz wynik (np. "2-1", "X", "1")
  python -m footstats.core.backtest weakness [dni]       — raport słabości (domyślnie 90 dni)
""")


if __name__ == "__main__":
    args = sys.argv[1:]

    if not args or args[0] in ("-h", "--help", "help"):
        _cli_help()
    elif args[0] == "stats":
        _cli_stats(int(args[1]) if len(args) > 1 else 30)
    elif args[0] == "pending":
        _cli_pending()
    elif args[0] == "update":
        if len(args) < 3:
            print("[Błąd] Podaj ID i wynik: python -m footstats.core.backtest update 42 \"2-1\"")
            sys.exit(1)
        _cli_update(args[1], args[2])
    elif args[0] == "weakness":
        _cli_weakness()
    else:
        print(f"[Błąd] Nieznana komenda: {args[0]!r}")
        _cli_help()
        sys.exit(1)
