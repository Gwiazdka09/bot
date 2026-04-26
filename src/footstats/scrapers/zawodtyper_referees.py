from pathlib import Path
from bs4 import BeautifulSoup

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    pass

from footstats.scrapers.referee_db import upsert_referee

ZAWODTYPER_URL = "https://zawodtyper.pl/statystyki-sedziow/"

COUNTRY_MAP = {
    "Anglia": "England",
    "Francja": "France",
    "Hiszpania": "Spain",
    "Holandia": "Netherlands",
    "Niemcy": "Germany",
    "Polska": "Poland",
    "Włochy": "Italy",
    "Wochy": "Italy",  # Fallback for encoding issues
}

def fetch_referees_zawodtyper() -> None:
    """Fetch referee stats from zawodtyper.pl using Playwright (sync)."""
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()

            print(f"[ZawodTyper] Ładuję stronę: {ZAWODTYPER_URL} ...")
            page.goto(ZAWODTYPER_URL, timeout=30000)
            page.wait_for_timeout(3000) # Czekamy na Vue.js/React hydration

            content = page.content()
            browser.close()
            
            soup = BeautifulSoup(content, "html.parser")
            tables = soup.find_all("table")
            print(f"[ZawodTyper] Znaleziono {len(tables)} tabel. Parsowanie danych...")
            
            ref_count = 0
            for tbl in tables:
                parent = tbl.find_parent("div", class_="overflow-hidden")
                if not parent:
                    continue
                grand_parent = parent.parent
                header = grand_parent.find(["span"])
                country_raw = header.text.strip().split(":")[0] if header else "Unknown"
                country = COUNTRY_MAP.get(country_raw, country_raw)
                
                trs = tbl.find_all("tr")
                # Pomijamy th (trs[0])
                for tr in trs[1:]:
                    tds = tr.find_all(["td", "th"])
                    if len(tds) >= 6:
                        name = tds[1].text.strip()
                        matches_str = tds[2].text.strip()
                        yellows_str = tds[4].text.strip()
                        reds_str = tds[5].text.strip()
                        
                        try:
                            m = int(matches_str)
                            y = int(yellows_str)
                            r = int(reds_str)
                            if m > 0:
                                stats = {
                                    "country": country,
                                    "avg_yellow": round(y / m, 2),
                                    "avg_red": round(r / m, 3),
                                    "avg_goals": 0.0, # Zawodtyper nie podaje
                                    "home_win_pct": 0.0,
                                    "n_matches": m
                                }
                                upsert_referee(name, stats)
                                ref_count += 1
                        except ValueError:
                            pass
            
            print(f"[ZawodTyper] Zaktualizowano pomyślnie {ref_count} sędziów z {len(tables)} lig.")
            
    except Exception as e:
        print(f"[ZawodTyper] Błąd scrape'owania: {e}")

if __name__ == "__main__":
    fetch_referees_zawodtyper()
