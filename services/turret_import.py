"""Importer for the turret scrap tracker -- 'Turret Sheet Audit 2024/2025/
2026.xlsx' -> Sheet1, all three imported (2026-10-22; 2024 uses the older
COL_2024/_clean_2024 layout below, 2025/2026 share the current one). The
*other* old workbook's own equivalent 'Turret' tab (2023-2026 Rework
Data.xlsx, a different source entirely) is still not imported -- see
CLAUDE.md. Same dedup convention as services/rework_import.py
(source_row_hash, safe to re-run against a newer export of the same sheet).

Scrap-only, by design (2026-10-21): Sheet1 is really a job-sheet-usage
tracker that *also* has scrap recorded against some rows, not a scrap log
on its own -- most rows have no scrap at all (just which sheets a job used).
This app only cares about the scrap side, so `_clean` drops any row with no
scrap recorded (no scrap qty on any of the 3 slots and no scrap code) --
~5,300 of the real sheet's ~5,900 rows. A blank Scrap Date slot on an
imported row just means that particular slot had nothing scrapped, not
missing data -- a row can have scrap on slot A only, with B/C genuinely
unused.

Column layout confirmed live against the real workbook 2026-10-21: one row
per turret job, up to 3 raw sheet slots (A/B/C) each with an ordered qty vs.
a picked qty, and a separate scrap sub-log -- up to 3 independent scrap
events per row (one per sheet slot), each with its own date/sheet/qty, plus
one shared scrap code/comments/week/year for the row.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

import openpyxl

import db

# 0-based column indices in Sheet1, confirmed against the real header row
# (Excel auto-renamed repeated "Qty A"/"Qty P" headers to "Qty A2"/"Qty P3"/
# "Qty A4"/"Qty P5" -- those are just sheet B's and sheet C's ordered/picked
# qty, not a distinct concept).
COL = dict(
    date=0, week=1, type=2, sales_number=3, job_number=4,
    sheet_a=5, qty_a_ordered=6, qty_a_picked=7,
    sheet_b=8, qty_b_ordered=9, qty_b_picked=10,
    sheet_c=11, qty_c_ordered=12, qty_c_picked=13,
    open_status=14, variation=15, comments=16, scrap_code=17,
    scrap_date_a=18, scrap_sheet_a=19, scrap_qty_a=20,
    scrap_date_b=21, scrap_sheet_b=22, scrap_qty_b=23,
    scrap_date_c=24, scrap_sheet_c=25, scrap_qty_c=26,
    scrap_comments=27, scrap_week=28, scrap_year=29,
)

# Only a date is truly required. job_number is legitimately blank on ~330
# real rows (confirmed live 2026-10-21): "Sales #" = the literal placeholder
# "REWORKS" with a Sheet A value but no job number -- turret sheet stock
# consumed for door reworks, which don't carry a production job number the
# way a normal order does. Dropping those would lose real data for no good
# reason, the same lesson as rework_import.py's REQUIRED tuple.
REQUIRED = ("event_date",)


@dataclass
class ImportResult:
    inserted: int = 0
    skipped_duplicate: int = 0
    skipped_invalid: int = 0
    skipped_not_scrap: int = 0
    invalid_examples: list[str] = field(default_factory=list)


def _row_hash(raw: tuple) -> str:
    text = "|".join("" if v is None else str(v) for v in raw)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _str(v) -> str | None:
    return str(v).strip() if v not in (None, "") else None


def _num(v) -> float | None:
    return v if isinstance(v, (int, float)) else None


def _int(v) -> int | None:
    return int(v) if isinstance(v, (int, float)) else None


def _clean(row: tuple) -> dict | None:
    get = lambda key: row[COL[key]]  # noqa: E731
    values = {
        "event_date": get("date"),
        "week_num": _int(get("week")),
        "door_type": _str(get("type")),
        "sales_number": _str(get("sales_number")),
        "job_number": _str(get("job_number")),
        "sheet_a": _str(get("sheet_a")), "qty_a_ordered": _num(get("qty_a_ordered")), "qty_a_picked": _num(get("qty_a_picked")),
        "sheet_b": _str(get("sheet_b")), "qty_b_ordered": _num(get("qty_b_ordered")), "qty_b_picked": _num(get("qty_b_picked")),
        "sheet_c": _str(get("sheet_c")), "qty_c_ordered": _num(get("qty_c_ordered")), "qty_c_picked": _num(get("qty_c_picked")),
        "open_status": _str(get("open_status")),
        "variation": _str(get("variation")),
        "comments": _str(get("comments")),
        "scrap_code": _str(get("scrap_code")),
        "scrap_date_a": get("scrap_date_a"), "scrap_sheet_a": _str(get("scrap_sheet_a")), "scrap_qty_a": _num(get("scrap_qty_a")),
        "scrap_date_b": get("scrap_date_b"), "scrap_sheet_b": _str(get("scrap_sheet_b")), "scrap_qty_b": _num(get("scrap_qty_b")),
        "scrap_date_c": get("scrap_date_c"), "scrap_sheet_c": _str(get("scrap_sheet_c")), "scrap_qty_c": _num(get("scrap_qty_c")),
        "scrap_comments": _str(get("scrap_comments")),
        "scrap_week": _int(get("scrap_week")),
        "scrap_year": _int(get("scrap_year")),
    }
    if any(values[f] in (None, "") for f in REQUIRED):
        return None
    return values


def _has_scrap(values: dict) -> bool:
    """This app only cares about the scrap side of the tracker -- see
    module docstring. A row counts as scrap if any slot has a scrap qty, or
    the shared scrap code is set (covers the rare row with a code but no
    parsed qty)."""
    return any(values[f] is not None for f in ("scrap_qty_a", "scrap_qty_b", "scrap_qty_c", "scrap_code"))


# 2024's workbook ("Turret Sheet Audit 2024.xlsx") predates the 2025/2026
# layout above -- confirmed live 2026-10-22 against the real file: no Week
# column at all, and only one shared "Scrap Date" for the whole row instead
# of an independent date per sheet slot (A/B/C weren't tracked separately
# yet). Column positions confirmed against real scrap rows, not just the
# header -- e.g. a guillotine-cut-wrong row with scrap on both slot A and
# slot B lines up exactly against this mapping.
COL_2024 = dict(
    date=0, type=1, sales_number=2, job_number=3,
    sheet_a=4, qty_a_ordered=5, qty_a_picked=6,
    sheet_b=7, qty_b_ordered=8, qty_b_picked=9,
    sheet_c=10, qty_c_ordered=11, qty_c_picked=12,
    open_status=13, variation=14, comments=15, scrap_code=16,
    scrap_date=17, scrap_sheet_a=18, scrap_qty_a=19,
    scrap_sheet_b=20, scrap_qty_b=21, scrap_sheet_c=22, scrap_qty_c=23,
    scrap_comments=24,
)


def _clean_2024(row: tuple) -> dict | None:
    """2024 has no Week column -- `week_num` is derived from event_date's
    own ISO week instead (same definition services.turret.create_event uses
    for new web-form rows, and the migration-0012 backfill used for
    existing ones), rather than left NULL, so this data doesn't reintroduce
    the "None" display bug that fix solved on the Scrap write-off tab. The
    single shared Scrap Date is applied to every sheet slot that actually
    has scrap recorded on that row -- the source never recorded a more
    specific date than that, so there's nothing more precise to assign."""
    get = lambda key: row[COL_2024[key]]  # noqa: E731
    event_date = get("date")
    shared_scrap_date = get("scrap_date")
    values = {
        "event_date": event_date,
        "week_num": event_date.isocalendar()[1] if hasattr(event_date, "isocalendar") else None,
        "door_type": _str(get("type")),
        "sales_number": _str(get("sales_number")),
        "job_number": _str(get("job_number")),
        "sheet_a": _str(get("sheet_a")), "qty_a_ordered": _num(get("qty_a_ordered")), "qty_a_picked": _num(get("qty_a_picked")),
        "sheet_b": _str(get("sheet_b")), "qty_b_ordered": _num(get("qty_b_ordered")), "qty_b_picked": _num(get("qty_b_picked")),
        "sheet_c": _str(get("sheet_c")), "qty_c_ordered": _num(get("qty_c_ordered")), "qty_c_picked": _num(get("qty_c_picked")),
        "open_status": _str(get("open_status")),
        "variation": _str(get("variation")),
        "comments": _str(get("comments")),
        "scrap_code": _str(get("scrap_code")),
        "scrap_sheet_a": _str(get("scrap_sheet_a")), "scrap_qty_a": _num(get("scrap_qty_a")),
        "scrap_sheet_b": _str(get("scrap_sheet_b")), "scrap_qty_b": _num(get("scrap_qty_b")),
        "scrap_sheet_c": _str(get("scrap_sheet_c")), "scrap_qty_c": _num(get("scrap_qty_c")),
        "scrap_comments": _str(get("scrap_comments")),
        "scrap_week": None, "scrap_year": None,
    }
    for slot in ("a", "b", "c"):
        values[f"scrap_date_{slot}"] = shared_scrap_date if values[f"scrap_qty_{slot}"] is not None else None
    if any(values[f] in (None, "") for f in REQUIRED):
        return None
    return values


def parse_workbook(xlsx_path: str, sheet_name: str = "Sheet1", layout: str = "current"):
    """Yields (raw_row_tuple, cleaned_dict_or_None) for every data row.
    `layout="2024"` selects the older pre-2025 column mapping (see
    COL_2024/_clean_2024 above) -- everything else (2025, 2026, and any
    future export in that same shape) uses the current one. See
    services/rework_import.py's parse_workbook for why wb.close() is in a
    finally (Windows file-lock on a read_only workbook)."""
    clean = _clean_2024 if layout == "2024" else _clean
    date_col = COL_2024["date"] if layout == "2024" else COL["date"]
    job_col = COL_2024["job_number"] if layout == "2024" else COL["job_number"]
    wb = openpyxl.load_workbook(xlsx_path, data_only=True, read_only=True)
    try:
        ws = wb[sheet_name]
        for row in ws.iter_rows(min_row=2, values_only=True):
            if row[date_col] is None and row[job_col] is None:
                continue  # trailing blank row past the real data
            yield row, clean(row)
    finally:
        wb.close()


def import_workbook(xlsx_path: str, sheet_name: str = "Sheet1", layout: str = "current") -> ImportResult:
    result = ImportResult()
    with db.get_conn() as conn, conn.cursor() as cur:
        for raw, cleaned in parse_workbook(xlsx_path, sheet_name, layout):
            if cleaned is None:
                result.skipped_invalid += 1
                if len(result.invalid_examples) < 10:
                    result.invalid_examples.append(str(raw[:5]))
                continue
            if not _has_scrap(cleaned):
                result.skipped_not_scrap += 1
                continue
            row_hash = _row_hash(raw)
            cur.execute("SAVEPOINT row_sp")
            try:
                cur.execute(
                    """
                    INSERT INTO turret_events (
                        event_date, week_num, door_type, sales_number, job_number,
                        sheet_a, qty_a_ordered, qty_a_picked,
                        sheet_b, qty_b_ordered, qty_b_picked,
                        sheet_c, qty_c_ordered, qty_c_picked,
                        open_status, variation, comments, scrap_code,
                        scrap_date_a, scrap_sheet_a, scrap_qty_a,
                        scrap_date_b, scrap_sheet_b, scrap_qty_b,
                        scrap_date_c, scrap_sheet_c, scrap_qty_c,
                        scrap_comments, scrap_week, scrap_year, source_row_hash
                    ) VALUES (
                        %(event_date)s, %(week_num)s, %(door_type)s, %(sales_number)s, %(job_number)s,
                        %(sheet_a)s, %(qty_a_ordered)s, %(qty_a_picked)s,
                        %(sheet_b)s, %(qty_b_ordered)s, %(qty_b_picked)s,
                        %(sheet_c)s, %(qty_c_ordered)s, %(qty_c_picked)s,
                        %(open_status)s, %(variation)s, %(comments)s, %(scrap_code)s,
                        %(scrap_date_a)s, %(scrap_sheet_a)s, %(scrap_qty_a)s,
                        %(scrap_date_b)s, %(scrap_sheet_b)s, %(scrap_qty_b)s,
                        %(scrap_date_c)s, %(scrap_sheet_c)s, %(scrap_qty_c)s,
                        %(scrap_comments)s, %(scrap_week)s, %(scrap_year)s, %(row_hash)s
                    )
                    ON CONFLICT (source_row_hash) DO NOTHING
                    RETURNING id
                    """,
                    {**cleaned, "row_hash": row_hash},
                )
            except Exception:
                cur.execute("ROLLBACK TO SAVEPOINT row_sp")
                result.skipped_invalid += 1
                if len(result.invalid_examples) < 10:
                    result.invalid_examples.append(str(raw[:5]))
                continue
            # RETURNING + fetchone(), not cur.rowcount -- see
            # services/rework_import.py's comment on the same pattern.
            inserted_row = cur.fetchone()
            cur.execute("RELEASE SAVEPOINT row_sp")
            if inserted_row:
                result.inserted += 1
            else:
                result.skipped_duplicate += 1
    return result
