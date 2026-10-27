"""Shared importer for the `REWORK` sheet of '2023-2026 Rework Data.xlsx' --
used by both the one-off historical backfill (`import_rework_log.py`) and the
Admin -> Import from Excel page, so re-uploading the same workbook (or a
newer export of it) is always safe: already-imported rows are skipped, never
duplicated (see migrations/0002_import_support.sql's `source_row_hash`).

Historical rows keep the cost figures the spreadsheet itself computed at the
time (columns L/M/N, read with data_only=True so formulas resolve to their
last-saved cached value) rather than recomputing from today's item costs --
recomputing would silently rewrite history every time an item's standard
cost changes going forward. Compare services.rework.create_event, which
*does* recompute, for new entries made through the web form.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

import openpyxl

import db

# 0-based column indices in the `Rework` table, confirmed against the real
# header row (note the literal trailing space in "ENTERED DATE ").
COL = dict(
    entered_date=0, rework_date=1, due_date=2, type=3, so_number=4, product_code=5,
    quantity=6, height=7, width=8, cut_length=9, qty_to_remove=11, material_cost=12,
    labour_cost=13, reason=14, colour=15, name=16, work_centre=17, door_type=18, notes=20,
)

VALID_TYPES = ("Rework / Recoat", "Replace Part", "Scrap Entire Door")
REQUIRED = ("rework_date", "so_number", "product_code", "quantity", "reason", "colour", "door_type", "work_centre")


@dataclass
class ImportResult:
    inserted: int = 0
    skipped_duplicate: int = 0
    skipped_invalid: int = 0
    invalid_examples: list[str] = field(default_factory=list)


def _row_hash(raw: tuple) -> str:
    text = "|".join("" if v is None else str(v) for v in raw)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _clean(row: tuple) -> dict | None:
    get = lambda key: row[COL[key]]  # noqa: E731
    values = {
        "entered_date": get("entered_date"),
        "rework_date": get("rework_date"),
        "due_date": get("due_date"),
        "type": get("type"),
        "so_number": str(get("so_number")).strip() if get("so_number") else None,
        "product_code": str(get("product_code")).strip().upper() if get("product_code") else None,
        "quantity": get("quantity"),
        "height_mm": get("height"),
        "width_mm": get("width"),
        "cut_length_mm": get("cut_length"),
        "qty_to_remove": get("qty_to_remove") if isinstance(get("qty_to_remove"), (int, float)) else None,
        "material_cost": get("material_cost") if isinstance(get("material_cost"), (int, float)) else None,
        "labour_cost": get("labour_cost") if isinstance(get("labour_cost"), (int, float)) else None,
        "reason": str(get("reason")).strip() if get("reason") else None,
        "colour": str(get("colour")).strip() if get("colour") else None,
        "entered_by_name": str(get("name")).strip() if get("name") else None,
        "work_centre": str(get("work_centre")).strip() if get("work_centre") else None,
        "door_type": str(get("door_type")).strip() if get("door_type") else None,
        "notes": str(get("notes")).strip() if get("notes") else None,
    }
    if values["type"] not in VALID_TYPES:
        return None
    if any(values[f] in (None, "") for f in REQUIRED):
        return None
    if not isinstance(values["quantity"], (int, float)) or values["quantity"] <= 0:
        return None
    return values


def parse_workbook(xlsx_path: str, sheet_name: str = "REWORK"):
    """Yields (raw_row_tuple, cleaned_dict_or_None) for every data row.

    `read_only=True` keeps the underlying zip file open for lazy streaming,
    which blocks deleting the file afterward on Windows (POSIX allows
    unlinking an open file; Windows doesn't) -- explicitly closed in
    `finally` so the caller can always clean up a temp upload right after."""
    wb = openpyxl.load_workbook(xlsx_path, data_only=True, read_only=True)
    try:
        ws = wb[sheet_name]
        for row in ws.iter_rows(min_row=2, values_only=True):
            if row[COL["entered_date"]] is None and row[COL["so_number"]] is None:
                continue  # trailing blank row past the real data
            yield row, _clean(row)
    finally:
        wb.close()


def import_workbook(xlsx_path: str, sheet_name: str = "REWORK") -> ImportResult:
    result = ImportResult()
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT reason, source FROM rework_reasons")
        reason_source = {r["reason"]: r["source"] for r in cur.fetchall()}

        for raw, cleaned in parse_workbook(xlsx_path, sheet_name):
            if cleaned is None:
                result.skipped_invalid += 1
                if len(result.invalid_examples) < 10:
                    result.invalid_examples.append(str(raw[:6]))
                continue
            row_hash = _row_hash(raw)
            cur.execute("SAVEPOINT row_sp")
            try:
                cur.execute(
                    """
                    INSERT INTO rework_events (
                        entered_date, rework_date, due_date, type, so_number, product_code, quantity,
                        height_mm, width_mm, cut_length_mm, qty_to_remove, material_cost, labour_cost,
                        reason, source, colour, door_type, work_centre, notes, entered_by_name, source_row_hash
                    ) VALUES (
                        %(entered_date)s, %(rework_date)s, %(due_date)s, %(type)s, %(so_number)s, %(product_code)s, %(quantity)s,
                        %(height_mm)s, %(width_mm)s, %(cut_length_mm)s, %(qty_to_remove)s, %(material_cost)s, %(labour_cost)s,
                        %(reason)s, %(source)s, %(colour)s, %(door_type)s, %(work_centre)s, %(notes)s, %(entered_by_name)s, %(row_hash)s
                    )
                    ON CONFLICT (source_row_hash) DO NOTHING
                    RETURNING id
                    """,
                    {**cleaned, "source": reason_source.get(cleaned["reason"]), "row_hash": row_hash},
                )
            except Exception:
                cur.execute("ROLLBACK TO SAVEPOINT row_sp")
                result.skipped_invalid += 1
                if len(result.invalid_examples) < 10:
                    result.invalid_examples.append(str(raw[:6]))
                continue
            # RETURNING only yields a row for the insert ON CONFLICT DO NOTHING
            # actually performed -- unlike cur.rowcount, confirmed unreliable
            # here (reports an insert even on a no-op conflict against PGlite).
            inserted_row = cur.fetchone()
            cur.execute("RELEASE SAVEPOINT row_sp")
            if inserted_row:
                result.inserted += 1
            else:
                result.skipped_duplicate += 1
    return result
