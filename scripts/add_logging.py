#!/usr/bin/env python3
"""Add logging to all scrapers. Replace print() → logger.info/debug/error()"""
import re
from pathlib import Path

SCRAPERS = [
    "enriched.py",
    "flashscore_match.py",
    "flashscore_results.py",
    "form_scraper.py",
    "kursy.py",
    "results_updater.py",
    "sts.py",
    "superbet.py",
    "superoferta.py",
    "zawodtyper_referees.py",
]

SCRAPERS_DIR = Path("F:/bot/src/footstats/scrapers")


def process_file(fpath: Path) -> None:
    """Add logging import, replace print() calls."""
    content = fpath.read_text(encoding="utf-8")

    # Skip if already has logging
    if "import logging" in content or "from logging" in content:
        print(f"[SKIP] {fpath.name} — logging already added")
        return

    # Add logging import after other imports
    lines = content.split("\n")
    insert_idx = 0
    for i, line in enumerate(lines):
        if line.startswith("import ") or line.startswith("from "):
            insert_idx = i + 1
        elif line and not line.startswith("#") and not line.startswith("import "):
            break

    lines.insert(insert_idx, "import logging\n")
    lines.insert(insert_idx + 1, "logger = logging.getLogger(__name__)\n")

    content = "\n".join(lines)

    # Replace print() with logger.info/debug/error
    # Simple heuristic: error/warning → logger.error, info → logger.info
    content = re.sub(
        r'print\(\s*f?"([^"]*(?:error|blad|fail|ERROR)[^"]*)"\s*\)',
        r'logger.error("\1")',
        content,
        flags=re.IGNORECASE,
    )
    content = re.sub(
        r'print\(\s*f?"([^"]*(?:warn|Warn|WARNING)[^"]*)"\s*\)',
        r'logger.warning("\1")',
        content,
        flags=re.IGNORECASE,
    )
    # Default to info
    content = re.sub(r'print\(\s*f?"([^"]*)"\s*\)', r'logger.info("\1")', content)
    # Non-f-string prints
    content = re.sub(r'print\(\s*"([^"]*)"\s*\)', r'logger.info("\1")', content)

    fpath.write_text(content, encoding="utf-8")
    print(f"[OK] {fpath.name}")


if __name__ == "__main__":
    for fname in SCRAPERS:
        fpath = SCRAPERS_DIR / fname
        if fpath.exists():
            process_file(fpath)
        else:
            print(f"[MISSING] {fname}")
