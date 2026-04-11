import asyncio
import time
from playwright.async_api import async_playwright

async def run(home):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36')
        page = await context.new_page()
        
        print(f"-- Test wyszukiwania: {home} --")
        try:
            await page.goto('https://www.flashscore.pl/')
            print("Wszedłem na stronę główną.")
            
            # Czekaj na ikonę wyszukiwania
            search_icon = page.locator('#search-window')
            await search_icon.wait_for(timeout=10000)
            await search_icon.click()
            print("Kliknąłem ikonę szukaj.")
            
            # Wpisz nazwę
            search_input = page.locator('.search__input')
            await search_input.wait_for(timeout=5000)
            await search_input.fill(home)
            print(f"Wpisałem: {home}")
            
            # Czekaj na wyniki
            await page.wait_for_selector('.search__result', timeout=10000)
            print("Wyniki się pojawiły.")
            
            # Pobierz linki do drużyn
            teams = await page.query_selector_all('a[href*="/druzyna/"]')
            for t in teams[:5]:
                txt = await t.inner_text()
                hrf = await t.get_attribute("href")
                print(f"Drużyna: {txt.strip().replace('\n', ' ')} | URL: {hrf}")
                
        except Exception as e:
            print(f"BŁĄD: {e}")
            
        await browser.close()

if __name__ == "__main__":
    import sys
    query = sys.argv[1] if len(sys.argv) > 1 else "Barcelona"
    asyncio.run(run(query))
