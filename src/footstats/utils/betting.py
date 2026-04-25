import re

def oblicz_tip_correct(ai_tip: str, actual_result) -> int | None:
    """
    Oblicza czy typ był trafiony na podstawie wyniku meczu.
    Obsługuje formaty: str ("2-1"), tuple (2, 1) oraz list [2, 1].
    """
    if not actual_result:
        return None

    # NOWOŚĆ: Obsługa krotek i list (naprawa błędu AttributeError)
    if isinstance(actual_result, (tuple, list)):
        try:
            actual_result = f"{actual_result[0]}-{actual_result[1]}"
        except (IndexError, TypeError):
            return None

    tip  = (ai_tip or "").strip().upper()
    
    # Upewniamy się, że res jest stringiem przed strip()
    res = str(actual_result).strip()

    # Spróbuj sparsować wynik bramkowy
    home_g = away_g = None
    if "-" in res and res not in ("1", "X", "2"):
        # Usuń informacje o karnych lub dogrywce np. "2-1 (AET)"
        res_clean = re.sub(r"\(.*?\)", "", res).strip()
        parts = res_clean.replace("–", "-").split("-")
        try:
            home_g = int(parts[0].strip())
            away_g = int(parts[1].strip())
        except (ValueError, IndexError):
            pass

    # Wyznacz wynik 1/X/2 z bramek
    if home_g is not None and away_g is not None:
        if home_g > away_g:
            match_result = "1"
        elif home_g == away_g:
            match_result = "X"
        else:
            match_result = "2"
        total_goals = home_g + away_g
        btts        = home_g > 0 and away_g > 0
    elif res in ("1", "X", "2"):
        match_result = res
        total_goals  = None
        btts         = None
    else:
        return None

    # Sprawdź typ
    if tip in ("1", "X", "2"):
        return 1 if match_result == tip else 0

    if tip == "1X":
        return 1 if match_result in ("1", "X") else 0

    if tip == "X2":
        return 1 if match_result in ("X", "2") else 0

    if tip == "12":
        return 1 if match_result in ("1", "2") else 0

    # Over/Under
    if "OVER" in tip or "UNDER" in tip:
        if total_goals is None: return None
        try:
            val_match = re.search(r"(\d+\.\d+|\d+)", tip)
            if not val_match: return None
            val = float(val_match.group(1))
            if "OVER" in tip:
                return 1 if total_goals > val else 0
            else:
                return 1 if total_goals < val else 0
        except (AttributeError, ValueError):
            return None

    # BTTS
    if tip == "BTTS":
        if btts is None: return None
        return 1 if btts else 0
    if tip in ("BTTS NO", "NO BTTS"):
        if btts is None: return None
        return 1 if not btts else 0

    return None

def normalize_team_name(name: str) -> str:
    """Normalizacja nazwy drużyny do porównań."""
    if not name: return ""
    name = name.lower()
    name = re.sub(r"[^a-z0-9\s]", "", name)
    name = re.sub(r"\s+", " ", name).strip()
    
    mappings = {
        "manchester united": "man utd",
        "manchester city": "man city",
        "tottenham hotspur": "tottenham",
        "newcastle united": "newcastle",
        "west ham united": "west ham",
        "legia warszawa": "legia",
        "lech poznan": "lech",
    }
    return mappings.get(name, name)