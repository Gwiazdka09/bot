"""
decision_score.py – Score 0-100 dla kandydatów na nogi kuponu.

Kryteria i punkty:
  EV_netto > 0 (model)              +15
  Ensemble confidence > 70%         +20
  Brak ROTACJA / ZMECZENIE          +15
  PATENT lub TWIERDZA               +10
  Historical accuracy > 65%         +10
  Brak ROZBIEŻNOŚĆ (<20% diff)      +10
  [tylko faza final]:
    Kluczowi zawodnicy w składzie   +10
    Sędzia neutralny                +10

Progi: draft >= 40 | final >= 60
"""

PROG_DRAFT = 40
PROG_FINAL = 60


def score_kandydat(
    w: dict,
    context: dict | None = None,
    phase: str = "draft",
) -> tuple[int, list[str]]:
    """
    Oblicza Decision Score dla kandydata.

    w: dict z polami kandydata:
        ev_netto (float)          — EV po podatku 12%, np. 0.05 = 5%
        pewnosc (float)           — 0–1 lub 0–100 (auto-normalizacja)
        czynniki (list[str])      — ["ROTACJA", "PATENT", "TWIERDZA", ...]
        roznica_modeli (float)    — różnica Poisson vs ML w pkt procentowych
        accuracy (float | None)   — historyczna accuracy na tym rynku (0–1)

    context: dict z polami Fazy 2 (opcjonalne):
        lineup_ok (bool)          — kluczowi zawodnicy w składzie
        referee_neutral (bool)    — sędzia bez wyraźnego biasu

    phase: 'draft' | 'final'

    Zwraca: (score: int, powody: list[str])
    """
    context = context or {}
    score = 0
    powody: list[str] = []

    # 1. EV_netto > 0 (+15)
    ev = w.get("ev_netto", w.get("ev"))
    if ev is not None and ev > 0:
        score += 15
        powody.append(f"EV_netto={ev:+.1%} > 0 (+15)")
    else:
        powody.append(f"EV_netto={ev} <= 0 (0)")

    # 2. Ensemble confidence > 70% (+20)
    pewnosc = w.get("pewnosc", w.get("pw", 0)) or 0
    if pewnosc > 1:  # podana jako procenty → znormalizuj
        pewnosc = pewnosc / 100
    if pewnosc > 0.70:
        score += 20
        powody.append(f"Pewność={pewnosc:.0%} > 70% (+20)")
    else:
        powody.append(f"Pewność={pewnosc:.0%} <= 70% (0)")

    # 3. Brak ROTACJA/ZMECZENIE (+15)
    czynniki = [str(c).upper() for c in (w.get("czynniki") or w.get("factors") or [])]
    ostrzegawcze = [c for c in czynniki if c in ("ROTACJA", "ZMECZENIE")]
    if not ostrzegawcze:
        score += 15
        powody.append("Brak ROTACJA/ZMECZENIE (+15)")
    else:
        powody.append(f"UWAGA: {', '.join(ostrzegawcze)} — minus 15 pkt (0)")

    # 4. PATENT lub TWIERDZA (+10)
    wzmacniajace = [c for c in czynniki if c in ("PATENT", "TWIERDZA")]
    if wzmacniajace:
        score += 10
        powody.append(f"{', '.join(wzmacniajace)} (+10)")

    # 5. Historical accuracy > 65% (+10)
    accuracy = w.get("accuracy") or w.get("historical_accuracy")
    if accuracy is not None and accuracy > 0.65:
        score += 10
        powody.append(f"Historical acc={accuracy:.0%} > 65% (+10)")

    # 6. Brak ROZBIEŻNOŚĆ Poisson vs ML < 20 pkt (+10)
    rozn = w.get("roznica_modeli") or w.get("rozbieznosc")
    if rozn is None or abs(rozn) < 20:
        score += 10
        powody.append("Brak ROZBIEŻNOŚĆ Poisson/ML (+10)")
    else:
        powody.append(f"ROZBIEŻNOŚĆ={abs(rozn):.0f}% >= 20% (0)")

    # 7 & 8. Kontekst zewnętrzny — tylko faza final
    if phase == "final":
        if context.get("lineup_ok", False):
            score += 10
            powody.append("Skład kompletny (+10)")
        else:
            powody.append("Skład: brak danych lub kluczowy gracz absent (0)")

        if context.get("referee_neutral", False):
            score += 10
            powody.append("Sędzia neutralny (+10)")
        else:
            powody.append("Sędzia: brak danych lub kartkowy (0)")

    return score, powody


def is_go(score: int, phase: str = "draft") -> bool:
    """True jeśli score >= progu dla fazy. draft=40, final=60."""
    return score >= (PROG_FINAL if phase == "final" else PROG_DRAFT)
