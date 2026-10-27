"""One-off (but safe to re-run) historical backfill: loads the `REWORK` sheet
of '2023-2026 Rework Data.xlsx' (12,343 rows back to Jan 2023) into
rework_events. See services/rework_import.py's docstring for exactly how
cost figures and deduplication are handled.

    python import_rework_log.py "2023-2026 Rework Data.xlsx"
"""

from __future__ import annotations

import sys

import db
from services import rework_import

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python import_rework_log.py <path to xlsx>")
        sys.exit(1)

    db.init_db()
    result = rework_import.import_workbook(sys.argv[1])

    print(f"Inserted:           {result.inserted}")
    print(f"Already imported:   {result.skipped_duplicate}")
    print(f"Skipped (invalid):  {result.skipped_invalid}")
    if result.invalid_examples:
        print("Examples of skipped rows (entered_date, rework_date, due_date, type, so_number, product_code):")
        for ex in result.invalid_examples:
            print(" ", ex)
