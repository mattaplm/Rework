"""One-off (but safe to re-run) backfill: loads a 'Turret Sheet Audit
YYYY.xlsx' workbook's Sheet1 into turret_events. See
services/turret_import.py's docstring for column layout and deduplication.

2025/2026 share one column layout ("current", the default). 2024 predates
the Week column and the per-slot Scrap Date split -- pass "2024" as a second
argument to use that older mapping (COL_2024/_clean_2024).

    python import_turret_log.py "Turret Sheet Audit 2026.xlsx"
    python import_turret_log.py "Turret Sheet Audit 2024.xlsx" 2024
"""

from __future__ import annotations

import sys

import db
from services import turret_import

if __name__ == "__main__":
    if len(sys.argv) not in (2, 3):
        print("Usage: python import_turret_log.py <path to xlsx> [2024]")
        sys.exit(1)
    layout = sys.argv[2] if len(sys.argv) == 3 else "current"

    db.init_db()
    result = turret_import.import_workbook(sys.argv[1], layout=layout)

    print(f"Inserted:           {result.inserted}")
    print(f"Already imported:   {result.skipped_duplicate}")
    print(f"Skipped (no scrap): {result.skipped_not_scrap}")
    print(f"Skipped (invalid):  {result.skipped_invalid}")
    if result.invalid_examples:
        print("Examples of skipped rows (date, week, type, sales_number, job_number):")
        for ex in result.invalid_examples:
            print(" ", ex)
