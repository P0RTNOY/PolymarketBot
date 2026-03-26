"""
scripts/migrate_123.py
Phase 12.3A — Add persistence and stability columns to signals table.
"""
import sqlite3
import os

DB_PATH = "polymarket_bot.db"

COLUMNS = [
    ("exec_stability_score", "REAL", "0.0–1.0 persistence quality score"),
    ("exec_stability_label", "TEXT", "stable | flicker | unstable"),
    ("exec_stability_reasons", "TEXT", "JSON list of persistence rejection reasons"),
    ("exec_recent_tradable_ratio", "REAL", "ratio of tradable snapshots in window"),
    ("exec_consecutive_tradable_snapshots", "INTEGER", "current tradable streak count"),
    ("exec_stable_duration_seconds", "REAL", "duration of the window in seconds"),
]

def migrate():
    if not os.path.exists(DB_PATH):
        print(f"❌ Error: {DB_PATH} not found.")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Get existing columns
    cursor.execute("PRAGMA table_info(signals)")
    existing = {row[1] for row in cursor.fetchall()}

    added_count = 0
    for col_name, col_type, comment in COLUMNS:
        if col_name not in existing:
            print(f"  [add]    ALTER TABLE signals ADD COLUMN {col_name} {col_type};  -- {comment}")
            cursor.execute(f"ALTER TABLE signals ADD COLUMN {col_name} {col_type}")
            added_count += 1
        else:
            print(f"  [skip]   Column `{col_name}` already exists.")

    conn.commit()
    conn.close()

    if added_count > 0:
        print(f"\n✅  Migration complete — {added_count} column(s) added to `signals`.")
    else:
        print("\n✅  No migration needed — all columns present.")

if __name__ == "__main__":
    migrate()
