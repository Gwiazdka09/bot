import sys
from bs4 import BeautifulSoup

sys.stdout.reconfigure(encoding='utf-8')

def analyze():
    try:
        try:
            with open('f:/bot/scratch/flashscore_mobi.html', 'r', encoding='utf-16') as f:
                html = f.read()
        except:
            with open('f:/bot/scratch/flashscore_mobi.html', 'r', encoding='utf-8', errors='ignore') as f:
                html = f.read()
        
        soup = BeautifulSoup(html, "html.parser")
        links = soup.find_all("a", href=lambda x: x and "/match/" in x)
        
        if links:
            l = links[10] # Skip some ads
            print("LINK:", l)
            print("PARENT:", l.parent)
            print("PARENT PARENT:", l.parent.parent)
    except Exception as e:
        print(f"Error: {e}")

analyze()
