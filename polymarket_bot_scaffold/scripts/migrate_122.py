"""
scripts/migrate_122.py
Phase 12.2 — Adds exec_tradability_score column to signals table.

Usage:
    python scripts/migrate_122.py            # apply
    python scripts/migrate_122.py --dry-run  # preview only
"""
from __future__ import annotations
import argparse
import sys
import pathlib

root = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root))

from sqlalchemy import create_engine, text, inspect
from bot.core.config import get_settings

NEW_COLUMNS = [
    ("exec_tradability_score", "REAL", "0.0–1.0 execution quality score from ExecutionAssessor"),
]

TABLE = "signals"


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 12.2 migration: exec_tradability_score column")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    settings = get_settings()
    engine = create_engine(settings.database_url)

    inspector = inspect(engine)
    existing_cols = {col["name"] for col in inspector.get_columns(TABLE)}

    stmts: list[str] = []
    for col_name, col_type, comment in NEW_COLUMNS:
        if col_name in existing_cols:
            print(f"  [skip]   {TABLE}.{col_name} already exists")
        else:
            stmt = f"ALTER TABLE {TABLE} ADD COLUMN {col_name} {col_type};"
            stmts.append(stmt)
            print(f"  [add]    {stmt}  -- {comment}")

    if not stmts:
        print("\nNothing to migrate — all columns already present.")
        return

    if args.dry_run:
        print("\n[dry-run] No changes written.")
        return

    with engine.begin() as conn:
        for stmt in stmts:
            conn.execute(text(stmt))

    print(f"\n✅  Migration complete — {len(stmts)} column(s) added to `{TABLE}`.")


if __name__ == "__main__":
    main()
