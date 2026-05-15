"""
backup_db.py – Lokalny backup SQLite przed uruchomieniem pipeline.

Użycie:
    python -m scripts.backup_db
    python scripts/backup_db.py
"""

import logging
import shutil
import sys
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

DB_PATHS = [
    Path("data/footstats_backtest.db"),
    Path("data/footstats.db"),
]
BACKUP_DIR = Path("data/backups")
MAX_BACKUPS = 30


def _backup_plik(db_path: Path, backup_dir: Path) -> Path:
    """Kopiuje jeden plik DB do backup_dir z timestampem."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    nazwa = f"{db_path.stem}_{ts}.db"
    cel = backup_dir / nazwa
    shutil.copy2(db_path, cel)
    logger.info("Backup: %s → %s (%.1f KB)", db_path, cel, cel.stat().st_size / 1024)
    return cel


def _wyczysc_stare(backup_dir: Path, wzorzec: str, max_kopii: int) -> None:
    """Usuwa najstarsze backupy ponad limit max_kopii."""
    pliki = sorted(backup_dir.glob(wzorzec), key=lambda p: p.stat().st_mtime)
    do_usuniecia = pliki[: max(0, len(pliki) - max_kopii)]
    for p in do_usuniecia:
        p.unlink()
        logger.debug("Usunięto stary backup: %s", p)
    if do_usuniecia:
        logger.info("Usunięto %d starych backupów (%s)", len(do_usuniecia), wzorzec)


def wykonaj_backup(db_paths: list[Path] = DB_PATHS,
                   backup_dir: Path = BACKUP_DIR,
                   max_backups: int = MAX_BACKUPS) -> bool:
    """
    Tworzy timestampowane kopie podanych plików DB.

    Returns:
        True gdy co najmniej jeden backup się powiódł.
    """
    backup_dir.mkdir(parents=True, exist_ok=True)
    sukces = False

    for db_path in db_paths:
        if not db_path.exists():
            logger.warning("Brak pliku DB do backupu: %s — pomijam", db_path)
            continue
        try:
            _backup_plik(db_path, backup_dir)
            _wyczysc_stare(backup_dir, f"{db_path.stem}_*.db", max_backups)
            sukces = True
        except OSError as e:
            logger.error("Backup nieudany dla %s: %s", db_path, e)

    return sukces


def _konfiguruj_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
    )


if __name__ == "__main__":
    _konfiguruj_logging()
    logger.info("=== Backup bazy danych ===")
    ok = wykonaj_backup()
    if ok:
        logger.info("Backup zakończony pomyślnie.")
        sys.exit(0)
    else:
        logger.error("Backup nieudany — żaden plik nie został skopiowany.")
        sys.exit(1)
