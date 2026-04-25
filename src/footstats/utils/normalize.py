"""
normalize.py — Normalizacja nazw drużyn piłkarskich.

Usuwa popularne prefiksy/sufiksy klubowe (FC, KS, AS, itp.) i znaki specjalne,
a następnie stosuje opcjonalne mappingi z data/team_mappings.json.

Użycie:
    from footstats.utils.normalize import normalize_team_name
    normalize_team_name("KS Lechia Gdańsk")   # -> "lechia gdansk"
    normalize_team_name("FC Augsburg")         # -> "augsburg"
    normalize_team_name("Paris Saint-Germain") # -> "paris saint germain"
"""

from __future__ import annotations

import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

# Ścieżka do pliku mappingów (data/team_mappings.json względem katalogu projektu)
_MAPPINGS_PATH = Path(__file__).parents[3] / "data" / "team_mappings.json"

# Prefiksy usuwane z POCZĄTKU nazwy (case-insensitive, całe słowo)
_PREFIXES = {
    "fc", "fk", "fk", "ac", "as", "rc", "sc", "sk", "sv",
    "ks", "mks", "lks", "rks", "gks", "tps", "jk", "nk",
    "ss", "us", "ud", "cd", "cf", "sd", "rcd", "ced",
    "bsc", "vfb", "vfl", "tsg", "rb", "rsb",
    "pfc", "csk", "fcs", "ssk",
    "al",           # al-taawoun -> taawoun
    "afc", "asc",
    "atletico", "sporting", "deportivo",  # tylko gdy pierwszy token
}

# Sufiksy usuwane z KOŃCA nazwy (case-insensitive, całe słowo)
_SUFFIXES = {
    "fc", "fk", "ac", "sc", "sk", "sv", "if", "bk", "gf",
    "cf", "bc", "ut", "city", "town", "united", "rovers",
    "athletic", "athletics", "wanderers", "hotspur",
}

# Znaki zamieniane przed normalizacją: litery diakrytyczne → ASCII
_DIACRITICS_MAP = str.maketrans({
    "ą": "a", "ć": "c", "ę": "e", "ł": "l", "ń": "n",
    "ó": "o", "ś": "s", "ź": "z", "ż": "z",
    "Ą": "a", "Ć": "c", "Ę": "e", "Ł": "l", "Ń": "n",
    "Ó": "o", "Ś": "s", "Ź": "z", "Ż": "z",
    "-": " ", "_": " ", ".": " ", "'": "", "\u2019": "",
})


def _strip_diacritics(s: str) -> str:
    """Usuwa znaki diakrytyczne przez unicode normalization + zastępowanie polskich liter."""
    # Najpierw podmień polskie i znane litery przez mapę
    s = s.translate(_DIACRITICS_MAP)
    # Następnie normalizacja unicode NFD → stripuj combining marks
    nfkd = unicodedata.normalize("NFKD", s)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def _remove_prefixes_suffixes(tokens: list[str]) -> list[str]:
    """Usuwa znane prefiksy z początku i sufiksy z końca listy tokenów."""
    # Prefiks: usuń wszystkie pasujące tokeny z przodu
    while tokens and tokens[0] in _PREFIXES:
        tokens = tokens[1:]
    # Sufiks: usuń jeden pasujący token z końca (tylko jeden, żeby nie przegiąć)
    if tokens and tokens[-1] in _SUFFIXES and len(tokens) > 1:
        tokens = tokens[:-1]
    return tokens


_DEFAULT_MAPPINGS: dict[str, str] = {
    "barca":               "barcelona",
    "paris saint germain": "psg",
    "paris sg":            "psg",
    "psg":                 "psg",
    "manchester united":   "man utd",
    "man united":          "man utd",
    "manchester city":     "man city",
    "atletico madrid":     "atletico",
    "inter milan":         "inter",
    "internazionale":      "inter",
    "bayer leverkusen":    "leverkusen",
    "rb leipzig":          "leipzig",
    "rasenball leipzig":   "leipzig",
    "wisla plock":         "wisla plock",
    "ks lechia gdansk":    "lechia gdansk",
}


def _seed_mappings_file() -> None:
    """Tworzy team_mappings.json z domyślnymi aliasami, jeśli plik nie istnieje."""
    if _MAPPINGS_PATH.exists():
        return
    _MAPPINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    _MAPPINGS_PATH.write_text(
        json.dumps(_DEFAULT_MAPPINGS, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


@lru_cache(maxsize=1)
def _load_mappings() -> dict[str, str]:
    """Ładuje team_mappings.json (cached). Tworzy plik z defaults jeśli nie istnieje."""
    _seed_mappings_file()
    try:
        data = json.loads(_MAPPINGS_PATH.read_text(encoding="utf-8"))
        # Normalizuj klucze mappingów (lowercase bez diakrytyków)
        return {_strip_diacritics(k).lower(): v.lower() for k, v in data.items()}
    except (json.JSONDecodeError, OSError):
        return {k: v for k, v in _DEFAULT_MAPPINGS.items()}


def normalize_team_name(name: str, use_mappings: bool = True) -> str:
    """
    Normalizuje nazwę drużyny do postaci porównywalnej.

    Kroki:
      1. Zamień diakrytyki i znaki specjalne
      2. Lowercase
      3. Usuń znane prefiksy (FC, KS, al-, TSG, itp.) i sufiksy (United, City, itp.)
      4. Usuń zduplikowane spacje
      5. Zastosuj mappingi z data/team_mappings.json (jeśli istnieją)

    Args:
        name:         Oryginalna nazwa drużyny
        use_mappings: Jeśli True, stosuje mappingi z team_mappings.json

    Returns:
        Znormalizowana nazwa w lowercase, bez prefiksów i znaków specjalnych.

    Examples:
        >>> normalize_team_name("KS Lechia Gdańsk")
        'lechia gdansk'
        >>> normalize_team_name("FC Augsburg")
        'augsburg'
        >>> normalize_team_name("TSG Hoffenheim")
        'hoffenheim'
        >>> normalize_team_name("Al-Taawoun")
        'taawoun'
        >>> normalize_team_name("Paris Saint-Germain")
        'paris saint germain'
    """
    if not name:
        return ""

    # Krok 1-2: Diakrytyki + lowercase
    cleaned = _strip_diacritics(name).lower()

    # Krok 3: Usuń wszystko co nie jest literą/cyfrą/spacją
    cleaned = re.sub(r"[^a-z0-9 ]+", " ", cleaned)

    # Krok 4: Tokenizuj + usuń prefiksy/sufiksy
    tokens = [t for t in cleaned.split() if t]
    tokens = _remove_prefixes_suffixes(tokens)

    result = " ".join(tokens)

    # Krok 5: Mappingi (np. "wisla plock" -> "wisla plock" lub aliasy API)
    if use_mappings:
        mappings = _load_mappings()
        if result in mappings:
            result = mappings[result]

    return result


def reload_mappings() -> None:
    """Wyczyść cache mappingów (przydatne po edycji team_mappings.json)."""
    _load_mappings.cache_clear()
