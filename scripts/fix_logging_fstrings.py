#!/usr/bin/env python3
"""Fix f-strings in logger calls"""
import re
from pathlib import Path

files = [
    "enriched.py",
    "flashscore_match.py",
    "form_scraper.py",
    "kursy.py",
    "sts.py",
    "superbet.py",
    "superoferta.py",
    "zawodtyper_referees.py",
]

SCRAPERS_DIR = Path("F:/bot/src/footstats/scrapers")

for fname in files:
    fpath = SCRAPERS_DIR / fname
    if not fpath.exists():
        continue

    content = fpath.read_text(encoding="utf-8")

    # Find logger.X("...{") patterns and add f
    # Pattern: logger.info("...{var}..."
    pattern = r'logger\.(info|debug|warning|error)\("([^"]*\{[^"]*)"'

    def add_f(match):
        level = match.group(1)
        msg = match.group(2)
        # Only add f if not already there
        return f'logger.{level}(f"{msg}"'

    content = re.sub(pattern, add_f, content)

    fpath.write_text(content, encoding="utf-8")
    print(f"Fixed {fname}")
