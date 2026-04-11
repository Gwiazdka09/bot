import sqlite3
from pathlib import Path

DB_PATH = Path("f:/bot/data/footstats_backtest.db")

def check():
    if not DB_PATH.exists():
        print(f"Error: DB not found at {DB_PATH}")
        return
    
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = [t[0] for t in cursor.fetchall()]
    print(f"Tables in DB: {tables}")
    conn.close()

if __name__ == "__main__":
    check()
