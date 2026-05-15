"""Testy scripts/backup_db.py — lokalne backupy SQLite."""

import shutil
import sqlite3
import tempfile
from pathlib import Path

import pytest

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import backup_db as bak


@pytest.fixture
def tmp_db(tmp_path: Path) -> Path:
    db = tmp_path / "test.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY)")
    conn.commit()
    conn.close()
    return db


@pytest.fixture
def backup_dir(tmp_path: Path) -> Path:
    d = tmp_path / "backups"
    d.mkdir()
    return d


class TestBackupPlik:
    def test_tworzy_kopie(self, tmp_db: Path, backup_dir: Path) -> None:
        cel = bak._backup_plik(tmp_db, backup_dir)
        assert cel.exists()
        assert cel.stat().st_size > 0

    def test_nazwa_zawiera_timestamp(self, tmp_db: Path, backup_dir: Path) -> None:
        cel = bak._backup_plik(tmp_db, backup_dir)
        # format: stem_YYYYMMDD_HHMMSS.db
        assert cel.name.startswith(tmp_db.stem)
        assert cel.suffix == ".db"

    def test_kopia_jest_poprawna_sqlite(self, tmp_db: Path, backup_dir: Path) -> None:
        cel = bak._backup_plik(tmp_db, backup_dir)
        conn = sqlite3.connect(cel)
        tabele = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        conn.close()
        assert ("t",) in tabele


class TestWyczyscStare:
    def test_usuwa_ponad_limit(self, backup_dir: Path) -> None:
        for i in range(5):
            (backup_dir / f"test_{i:02d}.db").write_bytes(b"x")
        bak._wyczysc_stare(backup_dir, "test_*.db", max_kopii=3)
        pozostale = list(backup_dir.glob("test_*.db"))
        assert len(pozostale) == 3

    def test_nie_usuwa_gdy_w_limicie(self, backup_dir: Path) -> None:
        for i in range(3):
            (backup_dir / f"test_{i:02d}.db").write_bytes(b"x")
        bak._wyczysc_stare(backup_dir, "test_*.db", max_kopii=5)
        assert len(list(backup_dir.glob("test_*.db"))) == 3


class TestWykonajBackup:
    def test_sukces_gdy_db_istnieje(self, tmp_db: Path, backup_dir: Path) -> None:
        ok = bak.wykonaj_backup([tmp_db], backup_dir, max_backups=30)
        assert ok is True
        assert len(list(backup_dir.glob("*.db"))) == 1

    def test_false_gdy_brak_db(self, backup_dir: Path) -> None:
        brak = Path("/nie/istnieje.db")
        ok = bak.wykonaj_backup([brak], backup_dir)
        assert ok is False

    def test_backup_wiele_db(self, tmp_path: Path, backup_dir: Path) -> None:
        db1 = tmp_path / "a.db"
        db2 = tmp_path / "b.db"
        for db in (db1, db2):
            conn = sqlite3.connect(db)
            conn.close()
        ok = bak.wykonaj_backup([db1, db2], backup_dir)
        assert ok is True
        assert len(list(backup_dir.glob("*.db"))) == 2

    def test_retencja_30_backupow(self, tmp_db: Path, backup_dir: Path) -> None:
        for i in range(35):
            bak._backup_plik(tmp_db, backup_dir)
        bak._wyczysc_stare(backup_dir, f"{tmp_db.stem}_*.db", max_kopii=30)
        assert len(list(backup_dir.glob(f"{tmp_db.stem}_*.db"))) == 30
