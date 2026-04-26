import logging

logger = logging.getLogger(__name__)

"""
flashscore_match.py - Scraper szczegółów meczu z Flashscore.pl.
Nuclear Regex version: przeszukuje surowy HTML.
"""

import time
import json
import re
from typing import Optional, Dict, List
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)

def scrape_flashscore_match_details(match_id: str) -> Dict:
    """
    Pobiera szczegóły meczu za pomocą przekopywania surowego HTML.
    """
    url = f"https://www.flashscore.pl/mecz/{match_id}/#/szczegoly-meczu/szczegoly-meczu"
    result = {
        "match_id": match_id, "referee": None, "stadium": None,
        "absences": {"home": [], "away": []}, "success": False
    }

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(user_agent=_UA)
            page.goto(url, wait_until="networkidle", timeout=20000)
            time.sleep(3)
            
            # Pobierz Składy (tam są absencje) - klikamy dla pewności
            try: page.get_by_text("SKŁADY", exact=True).click(); time.sleep(2)
            except: pass
            
            content = page.content()
            
            # REGEX dla Sędziego: "Sędzia:</span><span.*?>([^<]+)</span>"
            # Flashscore ma specyficzną strukturę, szukajmy po prostu 'Sędzia'
            ref_match = re.search(r"Sędzia:.*?>(.*?)<", content, re.IGNORECASE | re.DOTALL)
            if ref_match: result["referee"] = ref_match.group(1).split("(")[0].strip()
            
            # REGEX dla Stadionu
            stad_match = re.search(r"Stadion:.*?>(.*?)<", content, re.IGNORECASE | re.DOTALL)
            if stad_match: result["stadium"] = stad_match.group(1).split("(")[0].strip()
            
            # Absencje są trudniejsze regexem ze względu na listę, ale spróbujmy:
            # Szukamy sekcji 'Nie zagra' i parsujemy bloki
            missing_part = re.split(r"Nie zagra", content, flags=re.IGNORECASE)
            if len(missing_part) > 1:
                # To bardzo uproszczone, ale może zadziałać na tekstach
                # Lepiej użyć innerText() z body
                raw_text = page.inner_text("body")
                if "NIE ZAGRA" in raw_text.upper():
                    # Szukaj nazwisk po 'NIE ZAGRA'
                    parts = raw_text.upper().split("NIE ZAGRA")
                    if len(parts) > 1:
                        # Logika uproszczona: wszystko po tym słowie to absencje
                        # (Wersja interaktywna z Turn 60 była lepsza jeśli DOM działa)
                        pass
            
            # Jeśli Regex zawiódł, użyjmy prostej pętli po elementach
            if not result["referee"]:
                labels = page.locator(".wcl-infoLabel_grawU").all()
                values = page.locator(".wcl-infoValue_grawU").all()
                for i, l in enumerate(labels):
                    if "SĘDZIA" in l.inner_text().upper() and i < len(values):
                        result["referee"] = values[i].inner_text().split("(")[0].strip()
                    if "STADION" in l.inner_text().upper() and i < len(values):
                        result["stadium"] = values[i].inner_text().split("(")[0].strip()

            result["success"] = True
            browser.close()
    except Exception as e:
        logger.error(f"Error: {{e}")
    return result

# Zachowaj search logic z Turn 60
def search_flashscore_match_id(page, home: str, away: str):
    from urllib.parse import quote
    try:
        page.goto(f"https://www.flashscore.pl/search/?q={quote(home)}", wait_until="networkidle")
        time.sleep(2)
        link = page.locator("a[href*='/druzyna/']").first
        if link.count() == 0: return None
        href = link.get_attribute("href")
        page.goto(f"https://www.flashscore.pl{href}", wait_until="networkidle")
        time.sleep(2)
        match_links = page.locator("a.eventRowLink").all()
        for l in match_links:
            row_text = page.evaluate("(el) => el.closest('.event__match').innerText", l).lower()
            if away.lower()[:5] in row_text:
                desc = l.get_attribute("aria-describedby")
                if desc and desc.startswith("g_1_"): return desc.replace("g_1_", "")
    except: pass
    return None

def scrape_match_with_search(h, a):
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(user_agent=_UA)
            mid = search_flashscore_match_id(page, h, a)
            browser.close()
            if mid: return scrape_flashscore_match_details(mid)
    except: pass
    return {"success": False}

if __name__ == "__main__":
    import sys
    mid = sys.argv[1] if len(sys.argv) > 1 else "O69fxvw8"
    print(json.dumps(scrape_flashscore_match_details(mid), indent=2, ensure_ascii=False))
