import asyncio
import time
import sys
from playwright.async_api import async_playwright

async def run(home, away):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36')
        page = await context.new_page()
        
        print(f"-- Szukanie meczu: {home} vs {away} --")
        
        try:
            # 1. Szukaj Drużyny
            print(f"Krok 1: Wyszukiwanie '{home}'")
            await page.goto(f"https://www.flashscore.pl/search/?q={home}")
            await asyncio.sleep(4)
            
            # Znajdź pierwszy link do drużyny
            team_link = await page.query_selector('a[href*="/druzyna/"]')
            if not team_link:
                print("BŁĄD: Nie znaleziono linku do drużyny.")
                await browser.close()
                return
            
            href = await team_link.get_attribute("href")
            print(f"Krok 2: Znaleziono drużynę: {href}")
            
            # 2. Wejdź na stronę drużyny
            await page.goto(f"https://www.flashscore.pl{href}")
            await asyncio.sleep(4)
            
            # 3. Szukaj ID meczu
            print(f"Krok 3: Szukanie meczu z '{away}'")
            # Przeszukujemy wszystkie elementy z ID g_1_...
            match_elements = await page.query_selector_all('div[id^="g_1_"]')
            print(f"Zaleziono {len(match_elements)} potencjalnych meczów.")
            
            found_id = None
            for el in match_elements:
                text = await el.inner_text()
                if away.lower()[:5] in text.lower():
                    m_id = await el.get_attribute("id")
                    found_id = m_id.replace("g_1_", "")
                    print(f"SUKCES! Znaleziono mecz ID: {found_id}")
                    # print(f"Podgląd: {text.replace('\n', ' ')}")
                    break
            
            if not found_id:
                print(f"BŁĄD: Nie znaleziono meczu z '{away}' na pierwszej stronie drużyny.")
                
        except Exception as e:
            print(f"WYJĄTEK: {e}")
        
        await browser.close()

if __name__ == "__main__":
    h = sys.argv[1] if len(sys.argv) > 1 else "Barcelona"
    a = sys.argv[2] if len(sys.argv) > 2 else "Espanyol"
    asyncio.run(run(h, a))
