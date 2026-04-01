"""
scraper_kursy.py – Scraper kursów bukmacherskich
Strony: Betexplorer (łatwiejszy) + Oddsportal (zapasowy)

Użycie:
    python -m footstats.scrapers.kursy                  # interaktywnie
    python -m footstats.scrapers.kursy premier-league   # od razu dla konkretnej ligi
"""

import json
import sys
import time
import re
from pathlib import Path
from datetime import datetime

# Playwright musi być zainstalowany: pip install playwright && playwright install chromium
try:
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
except ImportError:
    print("BŁĄD: pip install playwright  następnie  playwright install chromium")
    sys.exit(1)

# ── Konfiguracja ─────────────────────────────────────────────────────
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    )
}

LIGI_BETEXPLORER = {
    "premier-league":  "https://www.betexplorer.com/football/england/premier-league/results/",
    "ekstraklasa":     "https://www.betexplorer.com/football/poland/ekstraklasa/results/",
    "la-liga":         "https://www.betexplorer.com/football/spain/laliga/results/",
    "bundesliga":      "https://www.betexplorer.com/football/germany/bundesliga/results/",
    "serie-a":         "https://www.betexplorer.com/football/italy/serie-a/results/",
    "ligue-1":         "https://www.betexplorer.com/football/france/ligue-1/results/",
    "champions-league":"https://www.betexplorer.com/football/europe/champions-league/results/",
}

CACHE_DIR = Path("kursy_cache")


def _zapisz_cache(liga: str, dane: list) -> Path:
    CACHE_DIR.mkdir(exist_ok=True)
    sciezka = CACHE_DIR / f"{liga}_{datetime.now().strftime('%Y%m%d')}.json"
    sciezka.write_text(
        json.dumps(dane, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return sciezka


def _wczytaj_cache(liga: str) -> list | None:
    """Zwraca dane z cache jeśli z dzisiaj, inaczej None."""
    sciezka = CACHE_DIR / f"{liga}_{datetime.now().strftime('%Y%m%d')}.json"
    if sciezka.exists():
        try:
            dane = json.loads(sciezka.read_text(encoding="utf-8"))
            print(f"[Cache] Załadowano {len(dane)} meczów z pliku {sciezka.name}")
            return dane
        except Exception:
            pass
    return None


def _parsuj_kurs(tekst: str) -> float | None:
    """Zamienia tekst kursu np. '2.10' na float, None jeśli błąd."""
    try:
        k = float(tekst.strip().replace(",", "."))
        return k if 1.01 <= k <= 100 else None
    except (ValueError, AttributeError):
        return None


def scrape_betexplorer(liga_slug: str = "premier-league", headless: bool = True) -> list:
    """
    Scrapuje wyniki i kursy 1X2 z betexplorer.com
    Zwraca listę słowników z danymi meczów.
    """
    # Sprawdź cache najpierw
    cache = _wczytaj_cache(liga_slug)
    if cache:
        return cache

    url = LIGI_BETEXPLORER.get(liga_slug)
    if not url:
        print(f"[Scraper] Nieznana liga: {liga_slug}")
        print(f"[Scraper] Dostępne: {', '.join(LIGI_BETEXPLORER.keys())}")
        return []

    print(f"[Scraper] Scrapuję: {url}")
    mecze = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        ctx = browser.new_context(extra_http_headers=HEADERS)
        page = ctx.new_page()

        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            time.sleep(3)

            # Poczekaj na tabelę wyników
            try:
                page.wait_for_selector("table.table-main", timeout=10000)
            except PWTimeout:
                print("[Scraper] Timeout – strona wolna lub zmienił się układ")
                browser.close()
                return []

            # Scrapuj wiersze tabeli
            wiersze = page.query_selector_all("table.table-main tbody tr")
            print(f"[Scraper] Znaleziono {len(wiersze)} wierszy")

            for wiersz in wiersze:
                try:
                    # Nazwy drużyn
                    uczestnicy = wiersz.query_selector("td.table-participant")
                    if not uczestnicy:
                        continue
                    tekst_uczest = uczestnicy.inner_text().strip()
                    if " - " not in tekst_uczest:
                        continue
                    gospodarz, goscie = [x.strip() for x in tekst_uczest.split(" - ", 1)]

                    # Wynik
                    wynik_el = wiersz.query_selector("td.table-score")
                    wynik_txt = wynik_el.inner_text().strip() if wynik_el else "-"

                    # Kursy (komórki td z danymi numerycznymi)
                    komorki = wiersz.query_selector_all("td[class*='odds'], td.table-odds")
                    if len(komorki) < 3:
                        # Próba alternatywna – weź wszystkie td i filtruj numeryczne
                        wszystkie_td = wiersz.query_selector_all("td")
                        kursy_txt = []
                        for td in wszystkie_td:
                            t = td.inner_text().strip()
                            if re.match(r"^\d+\.\d+$", t):
                                kursy_txt.append(t)
                        k1 = _parsuj_kurs(kursy_txt[0]) if len(kursy_txt) > 0 else None
                        kx = _parsuj_kurs(kursy_txt[1]) if len(kursy_txt) > 1 else None
                        k2 = _parsuj_kurs(kursy_txt[2]) if len(kursy_txt) > 2 else None
                    else:
                        k1 = _parsuj_kurs(komorki[0].inner_text())
                        kx = _parsuj_kurs(komorki[1].inner_text())
                        k2 = _parsuj_kurs(komorki[2].inner_text())

                    # Data
                    data_el = wiersz.query_selector("td.table-time, td[class*='date']")
                    data_txt = data_el.inner_text().strip() if data_el else ""

                    mecze.append({
                        "gospodarz": gospodarz,
                        "goscie":    goscie,
                        "wynik":     wynik_txt,
                        "k1":        k1,
                        "kX":        kx,
                        "k2":        k2,
                        "data":      data_txt,
                        "liga":      liga_slug,
                        "zrodlo":    "betexplorer",
                    })
                except Exception:
                    continue

        except Exception as e:
            print(f"[Scraper] Błąd: {e}")
        finally:
            browser.close()

    # Filtruj wpisy bez kursów
    mecze_z_kursami = [m for m in mecze if m["k1"] and m["kX"] and m["k2"]]
    print(f"[Scraper] Zebrano {len(mecze_z_kursami)} meczów z kursami (z {len(mecze)} łącznie)")

    if mecze_z_kursami:
        sciezka = _zapisz_cache(liga_slug, mecze_z_kursami)
        print(f"[Scraper] Zapisano do: {sciezka}")

    return mecze_z_kursami


def szukaj_kursy_meczu(gospodarz: str, goscie: str, liga: str = "premier-league") -> dict | None:
    """
    Szuka kursów dla konkretnego meczu w danych z Betexplorer.
    Dopasowuje po częściowej nazwie (case-insensitive).
    """
    dane = scrape_betexplorer(liga)
    g_low = gospodarz.lower()
    a_low = goscie.lower()

    for mecz in dane:
        m_g = mecz["gospodarz"].lower()
        m_a = mecz["goscie"].lower()
        # Dopasowanie: pełna nazwa lub pierwsze słowo
        if (g_low in m_g or m_g in g_low) and (a_low in m_a or m_a in a_low):
            return mecz

    print(f"[Scraper] Nie znaleziono kursów dla: {gospodarz} vs {goscie}")
    return None


def pokaz_dostepne_ligi():
    print("\nDostępne ligi dla scrapera:")
    for slug, url in LIGI_BETEXPLORER.items():
        print(f"  {slug:<22} → {url}")
    print()


# ── Uruchomienie bezpośrednie ────────────────────────────────────────
if __name__ == "__main__":
    liga = sys.argv[1] if len(sys.argv) > 1 else None

    if not liga:
        pokaz_dostepne_ligi()
        liga = input("Wybierz ligę (np. premier-league): ").strip() or "premier-league"

    print(f"\nScrapuję kursy dla: {liga}")
    wyniki = scrape_betexplorer(liga, headless=False)  # headless=False = widzisz przeglądarkę

    if wyniki:
        print(f"\nPierwsze 5 meczów:")
        for m in wyniki[:5]:
            print(
                f"  {m['gospodarz']:25} vs {m['goscie']:25} | "
                f"Wynik: {m['wynik']:6} | "
                f"Kursy: 1={m['k1']}  X={m['kX']}  2={m['k2']}"
            )
    else:
        print("Brak wyników.")
