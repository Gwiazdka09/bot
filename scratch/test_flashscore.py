import requests
from bs4 import BeautifulSoup
import re

url = "https://www.flashscore.mobi/?d=-1"
headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
r = requests.get(url, headers=headers)
soup = BeautifulSoup(r.text, "html.parser")

# Find all match rows
# Usually matches are in divs with IDs like g_1_...
matches = soup.find_all("div", id=re.compile(r"^g_1_"))

print(f"Found {len(matches)} matches")
for m in matches[:5]:
    print("-" * 20)
    print(m.prettify())
