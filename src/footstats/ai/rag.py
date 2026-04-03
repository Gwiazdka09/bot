"""
rag.py – Pattern-based RAG dla FootStats

Szuka w backtest DB historycznych predykcji z podobnymi czynnikami
i zwraca skuteczność jako kontekst dla Groq.

Eksportuje:
    pobierz_rag_kontekst(w: dict) -> str
        Dla wpisu z wyniki[] zwraca string "PATENT+TWIERDZA->1: 7/8(87%)"
        Zwraca "" gdy brak danych lub za mało próbek.
"""

from datetime import datetime, timedelta


# ── Ekstrakcja czynników z pred dict ─────────────────────────────────────

_STRONG_STATUSES = {"HIGH_STAKES_TOP", "FINAL_TOP", "HIGH_STAKES_BOTTOM", "FINAL_RELEGATION"}
_STATUS_SHORT    = {
    "HIGH_STAKES_TOP":    "TOP",
    "FINAL_TOP":          "FINAL_TOP",
    "HIGH_STAKES_BOTTOM": "RELEGATION",
    "FINAL_RELEGATION":   "FINAL_REL",
}


def wyciagnij_faktory(pred: dict) -> list[str]:
    """
    Wyciąga listę czynników z bloku pred (z predict_match()).
    Przykład: ["PATENT", "TWIERDZA", "TOP"]
    """
    if not pred:
        return []

    h2h_g      = pred.get("h2h_g",      {}) or {}
    heur_g     = pred.get("heur_g",     {}) or {}
    heur_a     = pred.get("heur_a",     {}) or {}
    fortress_g = pred.get("fortress_g", {}) or {}
    imp_g      = pred.get("imp_g",      {}) or {}
    imp_a      = pred.get("imp_a",      {}) or {}

    faktory: list[str] = []

    if h2h_g.get("patent"):
        faktory.append("PATENT")
    if h2h_g.get("zemsta"):
        faktory.append("ZEMSTA")
    if fortress_g.get("fortress"):
        faktory.append("TWIERDZA")
    if heur_g.get("rotacja") or heur_a.get("rotacja"):
        faktory.append("ROTACJA")
    if heur_g.get("zmeczenie") or heur_a.get("zmeczenie"):
        faktory.append("ZMECZENIE")

    for imp in (imp_g, imp_a):
        s = imp.get("status", "NORMAL")
        if s in _STRONG_STATUSES:
            faktory.append(_STATUS_SHORT.get(s, s))

    return faktory


# ── Zapytanie do DB ───────────────────────────────────────────────────────

def pobierz_rag_wzorce(
    factors: list[str],
    ai_tip:  str | None = None,
    min_n:   int = 3,
    dni:     int = 180,
) -> str:
    """
    Dla podanej listy czynników i tipu zwraca historyczną skuteczność z backtestera.
    Zwraca "" gdy brak danych lub za mało próbek.

    Przykład zwrotu: "PATENT+TWIERDZA->1: 7/8(87%) | PATENT->1: 12/16(75%)"
    """
    if not factors:
        return ""

    try:
        from footstats.core.backtest import _connect, init_db
    except ImportError:
        return ""

    try:
        init_db()
        date_from = (datetime.now() - timedelta(days=dni)).strftime("%Y-%m-%d")
        wyniki: list[str] = []

        with _connect() as conn:

            def _query(factor_list: list[str], tip: str | None) -> tuple[int, int]:
                """Zwraca (n_zbadanych, trafienia) dla podanych czynników + tipu."""
                exists_parts = [
                    "EXISTS (SELECT 1 FROM json_each(factors) WHERE value = ?)"
                    for _ in factor_list
                ]
                params: list = [date_from] + factor_list
                tip_clause = ""
                if tip:
                    tip_clause = "AND ai_tip = ?"
                    params.append(tip)
                sql = f"""
                    SELECT COUNT(*) AS n, COALESCE(SUM(tip_correct), 0) AS hits
                    FROM predictions
                    WHERE match_date >= ?
                      AND tip_correct IS NOT NULL
                      AND {" AND ".join(exists_parts)}
                      {tip_clause}
                """
                row = conn.execute(sql, params).fetchone()
                return (row[0] or 0, int(row[1] or 0))

            # 1. Kombinacja wszystkich czynników (max 3) + tip
            combo = factors[:3]
            if len(combo) >= 2 and ai_tip:
                n, hits = _query(combo, ai_tip)
                if n >= min_n:
                    acc = round(hits / n * 100)
                    label = "+".join(combo)
                    wyniki.append(f"{label}->{ai_tip}: {hits}/{n}({acc}%)")

            # 2. Pojedyncze czynniki + tip
            seen: set[str] = set()
            for f in factors[:4]:
                if ai_tip:
                    n, hits = _query([f], ai_tip)
                    key = f"{f}->{ai_tip}"
                    if n >= min_n and key not in seen:
                        seen.add(key)
                        acc = round(hits / n * 100)
                        wyniki.append(f"{key}: {hits}/{n}({acc}%)")

        return " | ".join(wyniki[:3])

    except Exception:
        return ""


# ── Główna funkcja (API dla analyzer.py) ─────────────────────────────────

def pobierz_rag_kontekst(w: dict) -> str:
    """
    Dla wpisu z wyniki[] (quick_picks / weekly_picks) zwraca string RAG.
    Działa tylko dla meczów POISSON (mają pełny pred dict).
    Zwraca "" gdy brak danych, za mało próbek lub inny błąd.
    """
    if w.get("metoda") != "POISSON":
        return ""

    pred = w.get("pred") or {}
    faktory = wyciagnij_faktory(pred)
    if not faktory:
        return ""

    # Dominant tip z prawdopodobieństw
    pw  = pred.get("p_wygrana",   0) or 0
    pr  = pred.get("p_remis",     0) or 0
    pp  = pred.get("p_przegrana", 0) or 0
    if pw >= pr and pw >= pp:
        tip = "1"
    elif pp >= pr:
        tip = "2"
    else:
        tip = "X"

    return pobierz_rag_wzorce(faktory, tip)
