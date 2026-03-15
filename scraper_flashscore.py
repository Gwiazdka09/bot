"""
scraper_flashscore.py – Scraper kursów 1X2 z Flashscore.pl
Ścieżka: liga → zakładka Mecze → każdy mecz → zakładka Kursy → kursy 1X2

Użycie:
    python scraper_flashscore.py bundesliga
    python scraper_flashscore.py champions-league
    python scraper_flashscore.py ekstraklasa
"""

import json
import sys
import time
import statistics
from pathlib import Path
from datetime import datetime

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
except ImportError:
    print("BŁĄD: pip install playwright  następnie  python -m playwright install chromium")
    sys.exit(1)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "pl-PL,pl;q=0.9",
}

LIGI_FLASHSCORE = {
    "bundesliga":       "https://www.flashscore.pl/pilka-nozna/niemcy/bundesliga/",
    "premier-league":   "https://www.flashscore.pl/pilka-nozna/anglia/premier-league/",
    "ekstraklasa":      "https://www.flashscore.pl/pilka-nozna/polska/ekstraklasa/",
    "la-liga":          "https://www.flashscore.pl/pilka-nozna/hiszpania/primera-division/",
    "serie-a":          "https://www.flashscore.pl/pilka-nozna/wlochy/serie-a/",
    "ligue-1":          "https://www.flashscore.pl/pilka-nozna/francja/ligue-1/",
    "champions-league": "https://www.flashscore.pl/pilka-nozna/europa/liga-mistrzow/",
    "eredivisie":       "https://www.flashscore.pl/pilka-nozna/holandia/eredivisie/",
}

LIGI_BETEXPLORER = LIGI_FLASHSCORE
CACHE_DIR = Path("kursy_cache")
BASE_URL   = "https://www.flashscore.pl"


def _zapisz_cache(liga: str, dane: list) -> Path:
    CACHE_DIR.mkdir(exist_ok=True)
    sciezka = CACHE_DIR / f"{liga}_{datetime.now().strftime('%Y%m%d')}.json"
    sciezka.write_text(json.dumps(dane, ensure_ascii=False, indent=2), encoding="utf-8")
    return sciezka


def _wczytaj_cache(liga: str) -> list | None:
    sciezka = CACHE_DIR / f"{liga}_{datetime.now().strftime('%Y%m%d')}.json"
    if sciezka.exists():
        try:
            dane = json.loads(sciezka.read_text(encoding="utf-8"))
            print(f"[Cache] {len(dane)} meczów z {sciezka.name}")
            return dane
        except Exception:
            pass
    return None


def _parsuj_kurs(tekst: str) -> float | None:
    try:
        k = float(str(tekst).strip().replace(",", "."))
        return k if 1.01 <= k <= 100.0 else None
    except (ValueError, AttributeError):
        return None


def _zamknij_cookies(page) -> None:
    for sel in [
        "button#onetrust-accept-btn-handler",
        "#onetrust-accept-btn-handler",
        "button.fc-cta-consent",
    ]:
        try:
            page.click(sel, timeout=2000)
            time.sleep(0.5)
            return
        except Exception:
            pass


def _pobierz_kursy_meczu(page, mecz_url: str) -> tuple[float|None, float|None, float|None]:
    """
    Wchodzi na stronę konkretnego meczu, klika zakładkę 'Kursy',
    pobiera kursy 1X2 (średnia z wszystkich bukmacherów).
    Zwraca (k1, kX, k2).
    """
    try:
        page.goto(mecz_url, wait_until="domcontentloaded", timeout=20000)
        time.sleep(1.5)

        # Kliknij zakładkę "Kursy"
        for sel in [
            "button[data-testid='wcl-tab']:has-text('Kursy')",
            "button:has-text('Kursy')",
            "[role='tab']:has-text('Kursy')",
            "a:has-text('Kursy')",
        ]:
            try:
                page.click(sel, timeout=3000)
                time.sleep(1.5)
                break
            except Exception:
                continue

        # Poczekaj na kursy
        try:
            page.wait_for_selector("a.oddsCell__odd", timeout=5000)
        except PWTimeout:
            return None, None, None

        # Zbierz wszystkie kursy — każdy rząd to jeden bukmacher: k1 kX k2
        # Selektor: a.oddsCell__odd span (wewnątrz jest wartość kursu)
        wiersze = page.query_selector_all(".ui-table__row")

        k1_lista = []
        kx_lista = []
        k2_lista = []

        for wiersz in wiersze:
            komorki = wiersz.query_selector_all("a.oddsCell__odd")
            if len(komorki) >= 3:
                span1 = komorki[0].query_selector("span")
                spanx = komorki[1].query_selector("span")
                span2 = komorki[2].query_selector("span")
                v1 = _parsuj_kurs(span1.inner_text() if span1 else "")
                vx = _parsuj_kurs(spanx.inner_text() if spanx else "")
                v2 = _parsuj_kurs(span2.inner_text() if span2 else "")
                if v1: k1_lista.append(v1)
                if vx: kx_lista.append(vx)
                if v2: k2_lista.append(v2)

        if not k1_lista:
            return None, None, None

        # Użyj średniej kursów z wszystkich bukmacherów
        k1 = round(statistics.mean(k1_lista), 2)
        kx = round(statistics.mean(kx_lista), 2) if kx_lista else None
        k2 = round(statistics.mean(k2_lista), 2) if k2_lista else None

        return k1, kx, k2

    except Exception as e:
        return None, None, None


def scrape_nadchodzace(liga_slug: str = "bundesliga", headless: bool = True) -> list:
    """
    1. Otwiera stronę ligi
    2. Klika zakładkę 'Mecze'
    3. Zbiera linki do nadchodzących meczów
    4. Dla każdego meczu wchodzi i pobiera kursy 1X2
    """
    cache = _wczytaj_cache(liga_slug)
    if cache:
        return cache

    liga_url = LIGI_FLASHSCORE.get(liga_slug)
    if not liga_url:
        print(f"[Scraper] Nieznana liga: {liga_slug}")
        return []

    print(f"[Scraper] Liga: {liga_url}")
    mecze = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        ctx     = browser.new_context(extra_http_headers=HEADERS)
        page    = ctx.new_page()

        try:
            # ── Krok 1: otwórz stronę ligi ───────────────────────────────────
            page.goto(liga_url, wait_until="domcontentloaded", timeout=30000)
            time.sleep(2)
            _zamknij_cookies(page)

            # ── Krok 2: kliknij zakładkę "Mecze" ────────────────────────────
            mecze_klikniete = False
            for sel in [
                "a.tabs__tab[href*='mecze']",
                "a#li4",
                "a:has-text('Mecze')",
                "[href*='/mecze/']",
            ]:
                try:
                    page.click(sel, timeout=3000)
                    time.sleep(2)
                    mecze_klikniete = True
                    print(f"[Scraper] Kliknięto 'Mecze'")
                    break
                except Exception:
                    continue

            if not mecze_klikniete:
                print("[Scraper] Zakładka 'Mecze' nie znaleziona — próbuję bezpośrednio")
                page.goto(liga_url + "mecze/", wait_until="domcontentloaded", timeout=15000)
                time.sleep(2)

            # ── Krok 3: zbierz linki do nadchodzących meczów ─────────────────
            try:
                page.wait_for_selector(".event__match", timeout=10000)
            except PWTimeout:
                print("[Scraper] Brak meczów na stronie")
                browser.close()
                return []

            # Przewiń żeby załadować wszystkie
            for _ in range(2):
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                time.sleep(0.8)

            linki_meczow = []
            wiersze = page.query_selector_all(".event__match")
            print(f"[Scraper] Wiersze meczów: {len(wiersze)}")

            for w in wiersze:
                try:
                    klasy = w.get_attribute("class") or ""
                    if "--static" in klasy:
                        continue  # zakończony

                    # Link do meczu
                    link_el = w.query_selector("a.eventRowLink")
                    if not link_el:
                        link_el = w.query_selector("a[href*='/mecz/']")
                    if not link_el:
                        continue

                    href = link_el.get_attribute("href") or ""
                    if not href:
                        continue
                    if not href.startswith("http"):
                        href = BASE_URL + href

                    # Czas i drużyny
                    czas_el = w.query_selector(".event__time")
                    gosp_el = w.query_selector(".event__homeParticipant")
                    gosc_el = w.query_selector(".event__awayParticipant")

                    if not gosp_el or not gosc_el:
                        continue

                    czas_txt = czas_el.inner_text().strip() if czas_el else ""
                    gosp_txt = gosp_el.inner_text().strip()
                    gosc_txt = gosc_el.inner_text().strip()

                    if not gosp_txt or not gosc_txt:
                        continue

                    czesci   = czas_txt.split()
                    data_txt = czesci[0] if len(czesci) >= 2 else ""
                    godz_txt = czesci[1] if len(czesci) >= 2 else czas_txt

                    linki_meczow.append({
                        "url":       href,
                        "gospodarz": gosp_txt,
                        "goscie":    gosc_txt,
                        "data":      data_txt,
                        "godzina":   godz_txt,
                    })
                except Exception:
                    continue

            print(f"[Scraper] Nadchodzące mecze: {len(linki_meczow)}")

            # ── Krok 4: dla każdego meczu pobierz kursy ───────────────────────
            for i, m in enumerate(linki_meczow, 1):
                g = m["gospodarz"]
                a = m["goscie"]
                print(f"  [{i}/{len(linki_meczow)}] {g} vs {a} → {m['url'][:60]}...")

                k1, kx, k2 = _pobierz_kursy_meczu(page, m["url"])

                mecze.append({
                    "gospodarz": g,
                    "goscie":    a,
                    "data":      m["data"],
                    "godzina":   m["godzina"],
                    "k1":        k1,
                    "kX":        kx,
                    "k2":        k2,
                    "liga":      liga_slug,
                    "zrodlo":    "flashscore",
                    "url":       m["url"],
                })

                time.sleep(0.5)  # żeby nie być zablokowanym

        except Exception as e:
            print(f"[Scraper] Błąd główny: {e}")
        finally:
            browser.close()

    z_kursami = sum(1 for m in mecze if m["k1"])
    print(f"\n[Scraper] {len(mecze)} meczów, {z_kursami} z kursami 1X2")

    if mecze:
        sciezka = _zapisz_cache(liga_slug, mecze)
        print(f"[Scraper] Zapisano: {sciezka}")

    return mecze


def scrape_betexplorer(liga_slug: str = "bundesliga", headless: bool = True) -> list:
    return scrape_nadchodzace(liga_slug, headless)


def szukaj_kursy_meczu(gospodarz: str, goscie: str, liga: str = "bundesliga") -> dict | None:
    dane  = scrape_nadchodzace(liga)
    g_low = gospodarz.lower().strip()
    a_low = goscie.lower().strip()

    def _pasuje(szukana: str, w_danych: str) -> bool:
        s = szukana.lower()
        d = w_danych.lower()
        return s in d or d in s or s.split()[0] in d or d.split()[0] in s

    for mecz in dane:
        if _pasuje(g_low, mecz.get("gospodarz","")) and \
           _pasuje(a_low, mecz.get("goscie","")):
            return mecz

    print(f"[Scraper] Nie znaleziono: {gospodarz} vs {goscie}")
    return None


def pokaz_dostepne_ligi():
    print("\nDostępne ligi:")
    for slug, url in LIGI_FLASHSCORE.items():
        print(f"  {slug:<22} → {url}")
    print()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        pokaz_dostepne_ligi()
        liga = input("Liga (np. bundesliga): ").strip() or "bundesliga"
    else:
        liga = sys.argv[1].lower()

    # Usuń cache
    stary = CACHE_DIR / f"{liga}_{datetime.now().strftime('%Y%m%d')}.json"
    if stary.exists():
        stary.unlink()
        print(f"[Cache] Usunięto stary cache")

    wyniki = scrape_nadchodzace(liga, headless=False)

    if wyniki:
        print(f"\n{'─'*76}")
        print(f"{'Data':<10} {'Gospodarz':<24} {'Goście':<24} {'1':>6} {'X':>6} {'2':>6}")
        print(f"{'─'*76}")
        for m in wyniki:
            k1 = f"{m['k1']:.2f}" if m["k1"] else "  -  "
            kx = f"{m['kX']:.2f}" if m["kX"] else "  -  "
            k2 = f"{m['k2']:.2f}" if m["k2"] else "  -  "
            print(f"{m.get('data',''):10} {m['gospodarz']:<24} {m['goscie']:<24} "
                  f"{k1:>6} {kx:>6} {k2:>6}")
    else:
        print("\nBrak wyników.")
