"""
scripts/migrate_120.py
Phase 12.0 — Safe additive migration.

Adds nullable columns to the `signals` table to support the layered
decision types introduced in Phase 12.0.  The script is idempotent:
if a column already exists it is skipped silently.

Usage:
    python scripts/migrate_120.py            # apply
    python scripts/migrate_120.py --dry-run  # preview SQL only, no changes
"""
from __future__ import annotations
import argparse
import sys
from sqlalchemy import create_engine, text, inspect

# Import settings to resolve the DB URL from .env
import os, pathlib
# Ensure the project root is on sys.path so bot.* imports work from scripts/
root = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root))

from bot.core.config import get_settings

# New columns: (column_name, DDL type, comment)
NEW_COLUMNS = [
    ("alpha_score",    "REAL",    "abs(edge); strategy alpha score"),
    ("exec_approved",  "BOOLEAN", "execution assessment verdict"),
    ("exec_reasons",   "TEXT",    "JSON list of execution rejection reasons"),
    ("risk_approved",  "BOOLEAN", "risk assessment verdict"),
    ("risk_reasons",   "TEXT",    "JSON list of risk rejection reasons"),
    ("features_json",  "TEXT",    "JSON blob of SignalFeatures"),
]

TABLE = "signals"


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 12.0 migration: add columns to signals table")
    parser.add_argument("--dry-run", action="store_true", help="Print SQL without executing")
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
