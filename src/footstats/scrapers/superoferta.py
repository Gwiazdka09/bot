"""
superoferta.py – Scraper SuperOferta (boosted odds) z STS
==========================================================
Pobiera mecze z podwyższonymi kursami (SuperOferta + Daily Boost) ze STS.
Porównuje z kursami Bzzoiro do obliczenia EV.

Struktura strony STS /superoferta:
  [class*="odds-button__container"]:has([class*="boost-icon"])  ← boosted odds
    ^5  market-grid  → "Mecz - SuperOferta  1  K1  X  KX  2  K2"
    ^8  one-ticket-match-tile__content → team1, czas, team2
    ^9  one-ticket-match-tile → liga, mecze

Użycie:
    python -m footstats.scrapers.superoferta           # standardowo
    python -m footstats.scrapers.superoferta --debug   # z przeglądarką
    python -m footstats.scrapers.superoferta --brak-ev # bez EV Bzzoiro
"""

import json
import sys
import time
import os
import re
from pathlib import Path
from datetime import datetime

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
except ImportError:
    print("BŁĄD: pip install playwright  następnie  python -m playwright install chromium")
    sys.exit(1)

from dotenv import load_dotenv
load_dotenv()

STS_URL   = "https://www.sts.pl"
CACHE_DIR = Path("cache/superoferta")


# ── Helpers ───────────────────────────────────────────────────────────

def _zamknij_popup(page) -> None:
    for sel in [
        "button#onetrust-accept-btn-handler",
        "[aria-label='Zamknij']",
        "button:has-text('Akceptuję')",
    ]:
        try:
            page.click(sel, timeout=1500)
            time.sleep(0.3)
            return
        except Exception:
            pass


def _zaloguj(page) -> bool:
    login = os.getenv("STS_LOGIN", "").strip()
    haslo = os.getenv("STS_HASLO", "").strip()
    if not login or not haslo:
        return False
    try:
        try:
            page.click(
                "button:has-text('Zaloguj się'), a:has-text('Zaloguj się')",
                timeout=3000,
            )
            time.sleep(1.5)
        except Exception:
            pass
        try:
            page.wait_for_selector(
                "input[type='email'], input[placeholder*='e-mail']", timeout=5000
            )
        except PWTimeout:
            return False

        page.fill(
            "input[type='email'], input[placeholder*='e-mail'], "
            "input[placeholder*='E-mail']",
            login,
        )
        time.sleep(0.3)
        page.fill("input[type='password'], input[placeholder*='Hasło']", haslo)
        time.sleep(0.3)
        page.click("button:has-text('Zaloguj się')", timeout=5000)
        time.sleep(3)
        print("[STS] Zalogowano")
        return True
    except Exception as e:
        print(f"[STS] Logowanie nieudane: {e}")
        return False


def _parsuj_kurs(tekst: str) -> float | None:
    try:
        k = float(str(tekst).strip().replace(",", "."))
        return k if 1.01 <= k <= 1000 else None
    except (ValueError, AttributeError, TypeError):
        return None


def _parent(el, poziom: int):
    return el.evaluate_handle(
        f"el => {{let p=el; for(let i=0;i<{poziom};i++) p=p.parentElement; return p;}}"
    ).as_element()


# ── Parsowanie SuperOferty 1X2 ─────────────────────────────────────────

def _parsuj_superoferta_1x2(btn, debug: bool = False) -> dict | None:
    """
    Parsuje jeden boosted odds button (poziomy 5 i 8/9).
    Zwraca słownik z danymi meczu lub None.
    """
    try:
        # Poziom 5: market-grid → "Mecz - SuperOferta  1  K1  X  KX  2  K2"
        tile5 = _parent(btn, 5)
        t5txt = tile5.inner_text().strip()
        if "SuperOferta" not in t5txt:
            return None

        lines5 = [l.strip() for l in t5txt.split("\n") if l.strip()]
        # Wyciągnij kursy 1/X/2 z market-grid
        k1 = kx = k2 = None
        i = 0
        while i < len(lines5):
            if lines5[i] == "1" and i + 1 < len(lines5):
                k1 = _parsuj_kurs(lines5[i + 1])
            elif lines5[i] == "X" and i + 1 < len(lines5):
                kx = _parsuj_kurs(lines5[i + 1])
            elif lines5[i] == "2" and i + 1 < len(lines5):
                k2 = _parsuj_kurs(lines5[i + 1])
            i += 1

        # Poziom 8: one-ticket-match-tile__content → team1, czas, team2
        tile8   = _parent(btn, 8)
        t8txt   = tile8.inner_text().strip()
        lines8  = [l.strip() for l in t8txt.split("\n") if l.strip()]

        # Drużyny: pierwsza i czwarta linia (linie 2-3 to data/czas)
        team1 = lines8[0] if len(lines8) > 0 else "?"
        team2 = lines8[3] if len(lines8) > 3 else "?"
        czas  = " ".join(lines8[1:3]) if len(lines8) > 2 else "?"

        # Poziom 9: one-ticket-match-tile → liga
        tile9  = _parent(btn, 9)
        t9txt  = tile9.inner_text().strip()
        lines9 = [l.strip() for l in t9txt.split("\n") if l.strip()]
        liga   = lines9[0] if lines9 else "?"

        if debug:
            print(f"  DBG t5: {lines5[:8]}")
            print(f"  DBG t8: {lines8[:6]}")
            print(f"  DBG liga: {liga}")

        return {
            "mecz":    f"{team1} - {team2}",
            "team1":   team1,
            "team2":   team2,
            "liga":    liga,
            "czas":    czas,
            "typ":     "Mecz - SuperOferta",
            "k1":      k1,
            "kx":      kx,
            "k2":      k2,
            "rodzaj":  "superoferta_1x2",
            "scraped": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }
    except Exception as e:
        if debug:
            print(f"  DBG ERR 1x2: {e}")
        return None


# ── Parsowanie Daily Boost (combo bet) ────────────────────────────────

def _parsuj_daily_boost(tile) -> dict | None:
    """
    Parsuje one-ticket-match-tile__daily-boost (combo specjalny).
    Tekst: "liga  +N  team1  dzisiaj  HH:MM  team2  opis_zakładu  kurs"
    """
    try:
        txt   = tile.inner_text().strip()
        lines = [l.strip() for l in txt.split("\n") if l.strip()]
        if len(lines) < 5:
            return None

        # Filtruj "+N" (liczba linii) i puste
        linie = [l for l in lines if not re.match(r"^\+\d+$", l)]

        liga   = linie[0] if linie else "?"
        team1  = linie[1] if len(linie) > 1 else "?"
        czas   = " ".join(linie[2:4]) if len(linie) > 3 else "?"
        team2  = linie[4] if len(linie) > 4 else "?"
        opis   = linie[5] if len(linie) > 5 else "?"

        # Kurs = ostatnia linia będąca liczbą
        kurs = None
        for l in reversed(linie):
            k = _parsuj_kurs(l)
            if k:
                kurs = k
                break

        return {
            "mecz":    f"{team1} - {team2}",
            "team1":   team1,
            "team2":   team2,
            "liga":    liga,
            "czas":    czas,
            "typ":     opis[:120],
            "k1":      None,
            "kx":      None,
            "k2":      None,
            "kurs_boost": kurs,
            "rodzaj":  "daily_boost",
            "scraped": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }
    except Exception:
        return None


# ── Główny scraper ─────────────────────────────────────────────────────

def pobierz_superoferty(debug: bool = False) -> list:
    """
    Scrapuje SuperOferty i Daily Boost z STS /superoferta.
    Zwraca listę słowników z danymi boosted meczów.
    """
    wyniki = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not debug)
        ctx = browser.new_context(
            extra_http_headers={"Accept-Language": "pl-PL,pl;q=0.9"},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36"
            ),
        )
        page = ctx.new_page()

        try:
            print("[SuperOferta] Otwieram STS /wyzsze-kursy...")
            page.goto(
                f"{STS_URL}/zaklady-bukmacherskie/wyzsze-kursy",
                wait_until="domcontentloaded",
                timeout=30000,
            )
            time.sleep(3)
            _zamknij_popup(page)
            _zaloguj(page)

            # Przewiń żeby załadować lazy content
            for _ in range(5):
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                time.sleep(0.8)
            page.evaluate("window.scrollTo(0, 0)")
            time.sleep(1)

            if debug:
                page.screenshot(path="superoferta_debug.png")

            # ── Typ 1: SuperOferta 1X2 ────────────────────────────────────
            boost_btns = page.query_selector_all(
                '[class*="odds-button__container"]:has([class*="boost-icon"])'
            )
            print(f"[SuperOferta] Boost buttons: {len(boost_btns)}")

            seen_mecze: set[str] = set()
            for btn in boost_btns:
                wynik = _parsuj_superoferta_1x2(btn, debug=debug)
                if wynik:
                    klucz = wynik["mecz"]
                    if klucz not in seen_mecze:
                        seen_mecze.add(klucz)
                        wyniki.append(wynik)

            # ── Typ 2: Daily Boost (combo specjalny) ──────────────────────
            daily_tiles = page.query_selector_all(
                '[class*="one-ticket-match-tile"][class*="daily-boost"]'
            )
            print(f"[SuperOferta] Daily Boost tiles: {len(daily_tiles)}")

            for tile in daily_tiles:
                wynik = _parsuj_daily_boost(tile)
                if wynik:
                    klucz = wynik["mecz"] + str(wynik.get("kurs_boost", ""))
                    if klucz not in seen_mecze:
                        seen_mecze.add(klucz)
                        wyniki.append(wynik)

        except Exception as e:
            print(f"[SuperOferta] Błąd: {e}")
            if debug:
                page.screenshot(path="superoferta_error.png")
        finally:
            browser.close()

    print(f"[SuperOferta] Znaleziono {len(wyniki)} SuperOfert")
    return wyniki


# ── EV Bzzoiro ────────────────────────────────────────────────────────

def dodaj_ev_bzzoiro(oferty: list) -> list:
    """Porównuje boosted kursy z kursami rynkowymi Bzzoiro i liczy EV."""
    try:
        from footstats.scrapers.bzzoiro import BzzoiroClient
        bzz_key = os.getenv("BZZOIRO_KEY", "").strip()
        if not bzz_key:
            return oferty
        klient = BzzoiroClient(bzz_key)
        ok, msg = klient.waliduj()
        if not ok:
            print(f"[EV] Bzzoiro: {msg}")
            return oferty
        mecze_bzz = klient.predykcje_tygodnia()
        print(f"[EV] Bzzoiro: {len(mecze_bzz)} meczów")
    except Exception as e:
        print(f"[EV] Błąd Bzzoiro: {e}")
        return oferty

    def _match_score(oferta_mecz: str, bzz_gosp: str, bzz_gosc: str) -> int:
        om = oferta_mecz.lower()
        bg = str(bzz_gosp).lower()
        ba = str(bzz_gosc).lower()
        score = 0
        for slowo in om.replace("-", " ").split():
            if len(slowo) > 3 and (slowo in bg or slowo in ba):
                score += 2
        return score

    for oferta in oferty:
        mecz_str = oferta.get("mecz", "")
        if not mecz_str:
            continue

        best, best_score = None, 0
        for m in mecze_bzz:
            s = _match_score(mecz_str, m.get("gosp", ""), m.get("gosc", ""))
            if s > best_score:
                best_score, best = s, m

        if not best or best_score < 2:
            continue

        oferta["bzz_mecz"] = f"{best.get('gosp')} vs {best.get('gosc')}"
        odds = best.get("odds") or {}

        # Dla SuperOferta 1X2 – liczymy EV dla każdego kursu
        if isinstance(odds, dict):
            for typ, klucz_bz, klucz_of in [
                ("1", "home",  "k1"),
                ("X", "draw",  "kx"),
                ("2", "away",  "k2"),
            ]:
                kurs_sts = oferta.get(klucz_of)
                kurs_bzz_raw = odds.get(klucz_bz)
                kurs_bzz = _parsuj_kurs(str(kurs_bzz_raw)) if kurs_bzz_raw else None
                if kurs_sts and kurs_bzz and kurs_bzz > 1:
                    ev = round((kurs_sts / kurs_bzz - 1) * 100, 1)
                    oferta[f"ev_{typ}"] = ev
                    oferta[f"ev_{typ}_ocena"] = (
                        "BARDZO DOBRY" if ev >= 30
                        else "DOBRY"   if ev >= 10
                        else "OK"      if ev >= 0
                        else "BRAK"
                    )

        # Dla Daily Boost – porównaj kurs_boost z najniższym kursem
        kurs_boost = oferta.get("kurs_boost")
        if kurs_boost and isinstance(odds, dict):
            kursy_rynek = [
                _parsuj_kurs(str(v)) for v in odds.values() if _parsuj_kurs(str(v))
            ]
            if kursy_rynek:
                kurs_ref = min(kursy_rynek)  # najbardziej prawdopodobny wynik
                ev = round((kurs_boost / kurs_ref - 1) * 100, 1)
                oferta["ev_boost"]       = ev
                oferta["ev_boost_ocena"] = (
                    "BARDZO DOBRY" if ev >= 30
                    else "DOBRY"   if ev >= 10
                    else "OK"      if ev >= 0
                    else "BRAK"
                )

    return oferty


# ── Zapis ─────────────────────────────────────────────────────────────

def zapisz(oferty: list) -> Path:
    CACHE_DIR.mkdir(exist_ok=True)
    sciezka = CACHE_DIR / f"superoferta_{datetime.now().strftime('%Y%m%d_%H%M')}.json"
    sciezka.write_text(
        json.dumps(oferty, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return sciezka


# ── main ──────────────────────────────────────────────────────────────

def main():
    debug   = "--debug"   in sys.argv
    brak_ev = "--brak-ev" in sys.argv

    print("=" * 60)
    print("  SUPEROFERTA STS — BOOSTED KURSY")
    print("=" * 60)

    oferty = pobierz_superoferty(debug=debug)

    if not oferty:
        print("\n[!] Brak SuperOfert dziś. Sprawdź --debug po zrzut ekranu.")
        sys.exit(0)

    if not brak_ev:
        print("\n[EV] Porównuję z Bzzoiro...")
        oferty = dodaj_ev_bzzoiro(oferty)

    plik = zapisz(oferty)
    print(f"\n[OK] Zapisano: {plik}")

    # ── Wyświetlenie ────────────────────────────────────────────────────
    print()
    print("=" * 60)
    print("  ZNALEZIONE SUPEROFERTY")
    print("=" * 60)

    for i, o in enumerate(oferty, 1):
        rodzaj = o.get("rodzaj", "?")
        mecz   = o.get("mecz", "?")
        liga   = o.get("liga", "")
        czas   = o.get("czas", "")
        typ    = o.get("typ", "")

        print(f"\n{i}. [{rodzaj.upper()}] {mecz}")
        if liga:
            print(f"   Liga:  {liga}")
        if czas:
            print(f"   Czas:  {czas}")
        if typ and typ != "Mecz - SuperOferta":
            print(f"   Typ:   {typ}")

        if rodzaj == "superoferta_1x2":
            k1 = o.get("k1")
            kx = o.get("kx")
            k2 = o.get("k2")
            ev1 = o.get("ev_1", "")
            evx = o.get("ev_X", "")
            ev2 = o.get("ev_2", "")
            kursy_str = f"   Kursy: 1={k1}  X={kx}  2={k2}"
            if ev1 or evx or ev2:
                kursy_str += f"  | EV: 1={ev1:+.0f}% X={evx:+.0f}% 2={ev2:+.0f}%" if all(
                    isinstance(e, float) for e in [ev1, evx, ev2]
                ) else ""
            print(kursy_str)
            # Podkreśl najlepsze EV
            for ev_val, ev_label, kurs in [
                (o.get("ev_1"), "1", k1),
                (o.get("ev_X"), "X", kx),
                (o.get("ev_2"), "2", k2),
            ]:
                if isinstance(ev_val, float) and ev_val >= 10:
                    ocena = o.get(f"ev_{ev_label}_ocena", "")
                    print(f"   >>> TYP {ev_label} @ {kurs}  EV={ev_val:+.1f}%  [{ocena}]")

        else:  # daily_boost
            kurs = o.get("kurs_boost")
            ev   = o.get("ev_boost", "")
            ocena = o.get("ev_boost_ocena", "")
            print(f"   Kurs: {kurs}", end="")
            if isinstance(ev, float):
                print(f"  EV={ev:+.1f}%  [{ocena}]", end="")
            print()

        if o.get("bzz_mecz"):
            print(f"   Bzz:  {o['bzz_mecz']}")

    print()
    print("=" * 60)
    print(f"Razem: {len(oferty)} SuperOfert")
    print("=" * 60)


if __name__ == "__main__":
    main()
