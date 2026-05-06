"""
superbet_bb.py — Superbet BetBuilder market odds scraper.

Given a match (home, away), finds it on Superbet, navigates to the BetBuilder
tab, and captures available market odds via XHR interception.

Usage:
    from footstats.scrapers.superbet_bb import pobierz_bb_dla_meczow
    from footstats.betbuilder import generuj_kombinacje

    wyniki = pobierz_bb_dla_meczow([{"dom": "Legia", "gost": "Wisla"}])
    typy   = wyniki.get("Legia vs Wisla", [])
    combos = generuj_kombinacje(typy, kurs_rynkowy=3.50)

Requires: SUPERBET_LOGIN + SUPERBET_PASSWORD in .env
"""

import logging
import re
import time

from playwright.sync_api import Page, TimeoutError as PWTimeout, sync_playwright

from footstats.betbuilder import Typ
from footstats.scrapers.base_playwright import SUPERBET_CONFIG as _CFG, zamknij_popup

logger = logging.getLogger(__name__)

SUPERBET_URL    = "https://superbet.pl"
FOOTBALL_URL    = f"{SUPERBET_URL}/zaklady-bukmacherskie/pilka-nozna"
FOOTBALL_TODAY  = f"{FOOTBALL_URL}?day=dzisiaj"
FOOTBALL_TMRW   = f"{FOOTBALL_URL}?day=jutro"
KURSY_BASE      = f"{SUPERBET_URL}/kursy/pilka-nozna"
BB_BASE         = f"{SUPERBET_URL}/multi-bet-builder/pilka-nozna"

# URL substrings that suggest a BetBuilder API response
_BB_URL_HINTS = [
    "bet-builder", "betbuilder", "builder-market",
    "same-game", "sgm", "combinator", "multi-bet",
    "event-markets", "markets/event",
]

# Keys where market arrays can live in API JSON
_MARKET_KEYS = [
    "markets", "selections", "outcomes", "bets",
    "data", "items", "results", "legs",
]


# ── XHR interception ─────────────────────────────────────────────────────────

def _intercept_bb(page: Page, action_fn, wait: float = 6.0) -> list[dict]:
    """
    Runs action_fn(page), then collects JSON responses whose URL matches
    BetBuilder hints. Returns list of {'url': ..., 'data': ...}.
    """
    captured: list[dict] = []

    def _on_response(response):
        if not any(h in response.url.lower() for h in _BB_URL_HINTS):
            return
        try:
            if "json" not in response.headers.get("content-type", ""):
                return
            captured.append({"url": response.url, "data": response.json()})
        except Exception:
            pass

    page.on("response", _on_response)
    try:
        action_fn(page)
        time.sleep(wait)
    finally:
        page.remove_listener("response", _on_response)

    return captured


# ── Odds parsing ──────────────────────────────────────────────────────────────

def _parsuj_kursy(data) -> list[Typ]:
    """Recursively extract Typ objects from an API response payload."""
    typy: list[Typ] = []

    items: list = []
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        for key in _MARKET_KEYS:
            if key in data and isinstance(data[key], list):
                items = data[key]
                break
        if not items:
            for v in data.values():
                if isinstance(v, (list, dict)):
                    typy.extend(_parsuj_kursy(v))
            return typy

    for item in items:
        if not isinstance(item, dict):
            continue

        nazwa = (
            item.get("name") or item.get("marketName") or
            item.get("selectionName") or item.get("label") or
            item.get("betName") or ""
        )
        kurs = None
        for k in ["odds", "price", "coefficient", "rate", "value", "odd"]:
            v = item.get(k)
            if v is not None:
                try:
                    f = float(v)
                    if f > 1.0:
                        kurs = round(f, 3)
                        break
                except (ValueError, TypeError):
                    pass

        if nazwa and kurs:
            typy.append(Typ(nazwa=str(nazwa)[:80], kurs=kurs))

        for sub_key in ["outcomes", "selections", "options", "children", "markets"]:
            sub = item.get(sub_key)
            if isinstance(sub, list):
                typy.extend(_parsuj_kursy(sub))

    return typy


def _parsuj_kursy_z_dom(page: Page) -> list[Typ]:
    """DOM fallback when XHR yields nothing — scrape odds from rendered elements."""
    typy: list[Typ] = []
    try:
        els = page.query_selector_all(
            "[class*='market'] [class*='item'], "
            "[class*='selection'], [class*='outcome'], "
            "[class*='bet-builder'] [class*='option']"
        )
        for el in els[:300]:
            try:
                tekst = el.inner_text().strip()
                if not tekst or len(tekst) > 150:
                    continue
                linie = [l.strip() for l in tekst.split("\n") if l.strip()]
                for i, linia in enumerate(linie):
                    m = re.search(r'\b(\d+[.,]\d{2})\b', linia)
                    if m:
                        k = float(m.group(1).replace(",", "."))
                        if 1.01 < k < 50:
                            nazwa = linie[i - 1] if i > 0 else linia
                            typy.append(Typ(nazwa=nazwa[:80], kurs=round(k, 3)))
            except Exception:
                continue
    except Exception as e:
        logger.warning("[BB DOM] %s", e)
    return typy


# ── Match search ──────────────────────────────────────────────────────────────

def _slugify(name: str) -> str:
    """Converts team name to Superbet slug fragment (lowercase, spaces→hyphens)."""
    return name.lower().strip().replace(" ", "-").replace("_", "-")


def znajdz_url_meczu(page: Page, dom: str, gost: str) -> str | None:
    """
    Szuka meczu na listingu piłki nożnej Superbet (dzisiaj + jutro).
    Mecze są pod /kursy/pilka-nozna/{dom-slug}-vs-{gost-slug}-{id}.
    Zwraca pełny URL meczu lub None.
    """
    dom_s  = _slugify(dom)[:6]
    gost_s = _slugify(gost)[:6]

    for listing_url in (FOOTBALL_TODAY, FOOTBALL_TMRW):
        try:
            page.goto(listing_url, wait_until="domcontentloaded", timeout=20000)
            time.sleep(3)
            zamknij_popup(page, _CFG)

            for _ in range(4):
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                time.sleep(0.8)

            # Match URLs live under /kursy/pilka-nozna/
            hrefs: list[str] = page.evaluate(
                "Array.from(document.querySelectorAll('a[href]'))"
                ".map(a => a.href)"
                ".filter(h => h.includes('/kursy/pilka-nozna/'))"
            )

            for href in hrefs:
                href_l = href.lower()
                if dom_s in href_l or gost_s in href_l:
                    logger.info("[BB] Mecz znaleziony: %s", href)
                    return href

        except Exception as e:
            logger.warning("[BB] Błąd listingu %s: %s", listing_url, e)

    logger.warning("[BB] Nie znaleziono: %s vs %s", dom, gost)
    return None


# ── Core scraper ──────────────────────────────────────────────────────────────

def pobierz_kursy_bb(page: Page, match_url: str) -> list[Typ]:
    """
    Navigates to match page, clicks BetBuilder tab, captures market odds via XHR.
    Falls back to DOM parsing if XHR yields nothing.
    Returns deduplicated list of Typ for betbuilder.generuj_kombinacje().
    """
    def _do(pg: Page) -> None:
        # match_url is /kursy/pilka-nozna/{slug}-{id}
        # BetBuilder lives at /multi-bet-builder/pilka-nozna/{slug}-{id}
        slug = match_url.split("/kursy/pilka-nozna/")[-1] if "/kursy/" in match_url else ""
        bb_url = f"{BB_BASE}/{slug}" if slug else None

        # Try direct BetBuilder URL first
        if bb_url:
            try:
                pg.goto(bb_url, wait_until="domcontentloaded", timeout=20000)
                time.sleep(3)
                zamknij_popup(pg, _CFG)
                logger.info("[BB] Nawigacja do BB URL: %s", bb_url)
                return
            except Exception:
                pass

        # Fallback: go to kursy page, click BetBuilder tab
        pg.goto(match_url, wait_until="domcontentloaded", timeout=20000)
        time.sleep(2)
        zamknij_popup(pg, _CFG)

        for sel in (
            "a:has-text('Multi BetBuilder')",
            "a:has-text('BetBuilder')",
            "button:has-text('BetBuilder')",
            "[data-cy='bet-builder-tab']",
            "li:has-text('BetBuilder')",
            "span:has-text('BetBuilder')",
            "a[href*='multi-bet-builder']",
        ):
            try:
                pg.wait_for_selector(sel, timeout=4000)
                pg.click(sel)
                logger.info("[BB] Kliknięto tab: %s", sel)
                return
            except Exception:
                continue
        logger.warning("[BB] Tab BetBuilder nie znaleziony — przechwytuje całą stronę")

    captured = _intercept_bb(page, _do, wait=6.0)

    # Scroll to trigger lazy market loading
    try:
        for _ in range(3):
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(0.7)
    except Exception:
        pass

    typy: list[Typ] = []
    for resp in captured:
        logger.debug("[BB] XHR: %s", resp["url"][:100])
        typy.extend(_parsuj_kursy(resp["data"]))

    if not typy:
        logger.info("[BB] XHR puste — próba DOM")
        typy = _parsuj_kursy_z_dom(page)

    # Deduplicate: keep highest odds per name
    best: dict[str, float] = {}
    for t in typy:
        if t.nazwa not in best or t.kurs > best[t.nazwa]:
            best[t.nazwa] = t.kurs

    wynik = [Typ(nazwa=n, kurs=k) for n, k in best.items()]
    logger.info("[BB] %s → %d kursów BB", match_url.split("/")[-1], len(wynik))
    return wynik


# ── Public batch API ──────────────────────────────────────────────────────────

def pobierz_bb_dla_meczow(
    mecze: list[dict],
    headless: bool = True,
) -> dict[str, list[Typ]]:
    """
    Batch: for each match dict {'dom': str, 'gost': str} fetches BetBuilder odds.

    Returns:
        {'Dom vs Gost': [Typ(...), ...], ...}
        Empty list means match not found or no BetBuilder markets captured.

    Requires SUPERBET_LOGIN + SUPERBET_PASSWORD in .env.
    """
    from footstats.scrapers.superbet import zaloguj as _zaloguj

    wyniki: dict[str, list[Typ]] = {}

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=headless)
        ctx = browser.new_context(
            extra_http_headers={"Accept-Language": "pl-PL,pl;q=0.9"},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
        )
        page = ctx.new_page()

        try:
            page.goto(FOOTBALL_TODAY, wait_until="domcontentloaded", timeout=20000)
            time.sleep(2)
            zamknij_popup(page, _CFG)
            _zaloguj(page)
            time.sleep(2)

            for mecz in mecze:
                dom  = mecz.get("dom", "")
                gost = mecz.get("gost", "")
                if not dom or not gost:
                    continue

                klucz = f"{dom} vs {gost}"
                logger.info("[BB] Pobieram kursy: %s", klucz)

                match_url = znajdz_url_meczu(page, dom, gost)
                if not match_url:
                    wyniki[klucz] = []
                    continue

                try:
                    wyniki[klucz] = pobierz_kursy_bb(page, match_url)
                except Exception as e:
                    logger.error("[BB] Błąd %s: %s", klucz, e)
                    wyniki[klucz] = []

        finally:
            browser.close()

    return wyniki


if __name__ == "__main__":
    import sys
    import json
    import logging

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    debug = "--debug" in sys.argv
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    dom  = args[0] if len(args) > 0 else "Legia"
    gost = args[1] if len(args) > 1 else "Cracovia"

    print(f"\n=== BetBuilder odds: {dom} vs {gost} ===\n")
    wyniki = pobierz_bb_dla_meczow([{"dom": dom, "gost": gost}], headless=not debug)

    for klucz, typy in wyniki.items():
        print(f"\n{klucz} — {len(typy)} kursów:")
        for t in sorted(typy, key=lambda x: x.kurs):
            print(f"  {t.nazwa:<50} {t.kurs}")

    print(f"\nRAW JSON:\n{json.dumps({k: [(t.nazwa, t.kurs) for t in v] for k, v in wyniki.items()}, ensure_ascii=False, indent=2)}")
