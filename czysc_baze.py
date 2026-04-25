import sqlite3
import os
import shutil
from pathlib import Path

# Sciezki
MAIN_DB = Path("F:/bot/footstats.db")
OLD_DB = Path("F:/bot/data/footstats_backtest.db")

def migrate_if_needed():
    """Kopiuje dane z podfolderu data/ do glównego folderu, jesli glówna baza jest pusta."""
    if not MAIN_DB.exists() or MAIN_DB.stat().st_size == 0:
        if OLD_DB.exists() and OLD_DB.stat().st_size > 0:
            print(f"Migracja: Kopiowanie {OLD_DB} do {MAIN_DB}...")
            # Upewnij sie, ze folder docelowy istnieje
            MAIN_DB.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(OLD_DB, MAIN_DB)
            print("Kopiowanie zakonczone.")
        else:
            print("Nie znaleziono bazy zródlowej do migracji (data/footstats_backtest.db).")
    else:
        print(f"Glówna baza {MAIN_DB} juz istnieje i nie jest pusta ({MAIN_DB.stat().st_size} bytes).")

def clean_db():
    """Usuwa 'osierocone' rekordy o statusie pending starsze niz 3 dni."""
    if not MAIN_DB.exists() or MAIN_DB.stat().st_size == 0:
        print("Baza danych nie istnieje lub jest pusta. Przerywam czyszczenie.")
        return

    try:
        conn = sqlite3.connect(str(MAIN_DB))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Sprawdzamy czy w tej bazie jest tabela predictions
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='predictions'")
        if not cursor.fetchone():
            print(f"W bazie {MAIN_DB} nie znaleziono tabeli 'predictions'.")
            conn.close()
            return

        print(f"Czyszczenie bazy: {MAIN_DB}")
        
        # Liczymy mecze 'pending' (actual_result IS NULL)
        cursor.execute("SELECT count(*) FROM predictions WHERE actual_result IS NULL")
        count_before = cursor.fetchone()[0]
        print(f"   Meczów 'pending' (bez wyniku) przed czyszczeniem: {count_before}")

        # Czyścimy stare mecze (starsze niz 3 dni), które nie sa powiazane z kuponami (coupon_id IS NULL)
        # i nie maja wyniku
        cursor.execute("""
            DELETE FROM predictions 
            WHERE actual_result IS NULL 
            AND match_date < date('now', '-3 days')
            AND (coupon_id IS NULL OR coupon_id = '')
        """)
        
        deleted = cursor.rowcount
        conn.commit()
        
        cursor.execute("SELECT count(*) FROM predictions WHERE actual_result IS NULL")
        count_after = cursor.fetchone()[0]
        print(f"Gotowe! Usunieto {deleted} 'osieroconych' meczów-widm.")
        print(f"   Meczów 'pending' po czyszczeniu: {count_after}")
        
        # Opcjonalnie: vacuum bazy
        print("Optymalizacja bazy (VACUUM)...")
        conn.execute("VACUUM")
        
        conn.close()
    except Exception as e:
        print(f"Blad podczas czyszczenia: {e}")

if __name__ == "__main__":
    migrate_if_needed()
    clean_db()