"""One-off: load reference data out of the existing '2023-2026 Rework Data.xlsx'
workbook into Postgres, so the dropdowns are real from day one instead of
empty. Safe to re-run -- everything is upserted.

Run once, locally, against the workbook's current location:
    python seed_reference_data.py "2023-2026 Rework Data.xlsx"

Deliberately NOT imported here: Material masters' standard/oversize lengths.
Its 'PRODUCT CODE' column is a family code (e.g. 00231) grouping several real
part numbers, not a part number itself, and nothing in the workbook maps one
to the other reliably -- that needs its own investigation against SyteLine's
length-charting tables (emdaLengthCharts/emdaLengths), not guessing from this
sheet.

Also NOT imported here: colours. `services/erp_sync.py` (run via
`sync_erp.py`) now pulls the authoritative list straight from SyteLine's
`emdaColour` -- same source and query Scheduler's Colour Library uses -- so
seeding a second, differently-formatted list from this sheet would just
produce confusing near-duplicates (e.g. "Black Matt" next to ERP's own
"BLACK MATT 20S9041M"). Run `sync_erp.py` after this script if you need
colours and haven't already.

Also NOT imported: the 'Cost of Rework' sheet's per-part labour rates and
hourly rate. Labour-cost tracking is on hold for now (see services/costing.py);
`rework_rates`/`settings.hourly_rate` stay in the schema but unused.
"""

from __future__ import annotations

import sys

import openpyxl

import db


def _column_values(ws, col_idx: int, start_row: int = 2) -> list[str]:
    values = []
    for row in ws.iter_rows(min_row=start_row, max_col=col_idx + 1, values_only=True):
        val = row[col_idx]
        if val is None or str(val).strip() == "":
            continue
        values.append(str(val).strip())
    return values


def seed_reasons(ws) -> None:
    rows = []
    for i, row in enumerate(ws.iter_rows(min_row=2, max_col=3, values_only=True)):
        reason, code, source = row
        if not reason:
            continue
        rows.append((str(reason).strip(), str(code).strip() if code else None, str(source).strip(), i))

    with db.get_conn() as conn, conn.cursor() as cur:
        for reason, code, source, order in rows:
            cur.execute(
                "INSERT INTO rework_reasons (reason, code, source, sort_order) VALUES (%s, %s, %s, %s) "
                "ON CONFLICT (reason) DO UPDATE SET code = EXCLUDED.code, source = EXCLUDED.source",
                (reason, code, source, order),
            )
    print(f"Seeded {len(rows)} rework reasons.")


def seed_simple_list(ws, col_idx: int, table: str) -> None:
    values = _column_values(ws, col_idx)
    with db.get_conn() as conn, conn.cursor() as cur:
        for i, name in enumerate(values):
            cur.execute(
                f"INSERT INTO {table} (name, sort_order) VALUES (%s, %s) "
                f"ON CONFLICT (name) DO NOTHING",
                (name, i),
            )
    print(f"Seeded {len(values)} rows into {table}.")


def seed_items(ws) -> None:
    headers = [c.value for c in next(ws.iter_rows(min_row=1, max_row=1))]
    idx = {h: i for i, h in enumerate(headers)}
    count = 0
    with db.get_conn() as conn, conn.cursor() as cur:
        for row in ws.iter_rows(min_row=2, values_only=True):
            part_number = row[idx["Part Number"]]
            if not part_number:
                continue
            rule = row[idx["Rule"]]
            cur.execute(
                """
                INSERT INTO items (part_number, description, product_code, product_group, std_cost, rule)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (part_number) DO UPDATE SET
                    description = EXCLUDED.description,
                    product_code = EXCLUDED.product_code,
                    product_group = EXCLUDED.product_group,
                    std_cost = EXCLUDED.std_cost,
                    rule = EXCLUDED.rule
                """,
                (
                    str(part_number).strip(),
                    row[idx.get("Description")],
                    row[idx.get("Product Code")],
                    row[idx.get("Product Group")],
                    row[idx.get("Std Cost")],
                    rule if rule is not None else 1,
                ),
            )
            count += 1
    print(f"Seeded {count} items.")


def main(xlsx_path: str) -> None:
    db.init_db()
    wb = openpyxl.load_workbook(xlsx_path, data_only=True, read_only=True)

    seed_reasons(wb["Data Validations"])
    # door_types table is no longer used (2026-10-20: merged into
    # cpq_door_codes.family_name, managed from Admin -> Door Codes instead).
    seed_simple_list(wb["Data Validations"], 12, "work_centres")
    seed_items(wb["SL-Items"])


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python seed_reference_data.py <path to xlsx>")
        sys.exit(1)
    main(sys.argv[1])
