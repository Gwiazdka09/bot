from __future__ import annotations
import requests

_BASE = "https://v3.football.api-sports.io"


def get_lineup(fixture_id: int, api_key: str) -> dict | None:
    """Pobiera sklady z API-Football /fixtures/lineups."""
    try:
        resp = requests.get(
            f"{_BASE}/fixtures/lineups",
            params={"fixture": fixture_id},
            headers={"x-apisports-key": api_key},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json().get("response", [])
    except requests.RequestException:
        return None

    if len(data) < 2:
        return None

    result = {}
    sides = ("home", "away")
    for i, side in enumerate(sides):
        if i >= len(data):
            break
        entry = data[i]
        players = [p["player"]["name"] for p in entry.get("startXI", [])]
        missing = len(players) < 11
        result[side] = {
            "team": entry.get("team", {}).get("name", ""),
            "formation": entry.get("formation", ""),
            "startXI": players,
            "missing_key_players": missing,
        }

    return result if result else None


def lineup_confidence_penalty(lineup: dict | None) -> int:
    """Kara do decision_score: -15 za kazda druzyne z brakujacymi kluczowymi graczami."""
    if lineup is None:
        return 0
    penalty = 0
    for side in ("home", "away"):
        if lineup.get(side, {}).get("missing_key_players", False):
            penalty -= 15
    return penalty
