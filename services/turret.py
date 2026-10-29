"""Turret log: reads for the list/write-off pages, plus the entry form's
create/reopen-to-edit flow (2026-10-21).

Historically-imported rows (services/turret_import.py) are scrap-only --
the importer only ever inserts a row that already had scrap recorded (see
that module's docstring). New web-form rows don't have that constraint:
`create_event` saves a job's material usage with no rework/scrap at all
(most turret jobs never need any), and `update_event` reopens that same row
later to add it, same two-stage workflow as the real paper/spreadsheet
process this replaces.
"""

from __future__ import annotations

import datetime

import db
from services import erp_reconciliation, reference_data, test_data
from services.costing import compute_sheet_scrap_cost

SHEET_SLOTS = ("a", "b", "c")
REWORK_TYPES = ("Replacement Parts", "Rework Entire Door")

REQUIRED_FIELDS = ("event_date", "sales_number", "door_type", "colour", "sheet_a")


class ValidationError(Exception):
    def __init__(self, errors: dict[str, str]):
        self.errors = errors
        super().__init__(", ".join(f"{k}: {v}" for k, v in errors.items()))


def _validate(payload: dict) -> None:
    errors: dict[str, str] = {}
    for field in REQUIRED_FIELDS:
        if not str(payload.get(field) or "").strip():
            errors[field] = "Required."
    if payload.get("rework_type") and payload["rework_type"] not in REWORK_TYPES:
        errors["rework_type"] = f"Must be one of {', '.join(REWORK_TYPES)}."
    if errors:
        raise ValidationError(errors)


def list_events(limit: int = 200, offset: int = 0, filters: dict | None = None) -> list[dict]:
    filters = filters or {}
    clauses, params = [], {}

    if filters.get("year"):
        clauses.append(f"{db.date_part('year', 'event_date')} = %(year)s")
        params["year"] = int(filters["year"])
    if filters.get("month"):
        clauses.append(f"{db.date_part('month', 'event_date')} = %(month)s")
        params["month"] = int(filters["month"])
    if filters.get("door_type"):
        clauses.append("door_type = %(door_type)s")
        params["door_type"] = filters["door_type"]
    if filters.get("job_number"):
        clauses.append("LOWER(job_number) LIKE LOWER(%(job_number)s)")
        params["job_number"] = f"%{filters['job_number']}%"

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params["limit"] = limit
    params["offset"] = offset

    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"SELECT * FROM turret_events {where} "
            f"ORDER BY event_date DESC, id DESC LIMIT %(limit)s OFFSET %(offset)s",
            params,
        )
        return cur.fetchall()


def list_available_years() -> list[int]:
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute(f"SELECT DISTINCT {db.date_part('year', 'event_date')} AS y FROM turret_events ORDER BY y DESC")
        return [r["y"] for r in cur.fetchall()]


def list_door_types() -> list[str]:
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT DISTINCT door_type FROM turret_events WHERE door_type IS NOT NULL ORDER BY door_type")
        return [r["door_type"] for r in cur.fetchall()]


_UNPIVOT_SCRAP = """
    SELECT week_num, scrap_sheet_a AS item, scrap_qty_a AS qty, scrap_date_a AS scrap_date, sales_number FROM turret_events WHERE scrap_qty_a IS NOT NULL AND scrap_date_a IS NOT NULL
    UNION ALL
    SELECT week_num, scrap_sheet_b AS item, scrap_qty_b AS qty, scrap_date_b AS scrap_date, sales_number FROM turret_events WHERE scrap_qty_b IS NOT NULL AND scrap_date_b IS NOT NULL
    UNION ALL
    SELECT week_num, scrap_sheet_c AS item, scrap_qty_c AS qty, scrap_date_c AS scrap_date, sales_number FROM turret_events WHERE scrap_qty_c IS NOT NULL AND scrap_date_c IS NOT NULL
"""

def _writeoff_date_expr() -> str:
    return db.date_shift(db.week_start("scrap_date"), 7)


def scrap_summary_by_week(write_off_week: int | None = None, write_off_year: int | None = None) -> list[dict]:
    """Scrap logged in turret_events, grouped by the week it's due for
    write-off in ERP and item. A row can carry scrap against up to 3 sheet
    slots (A/B/C), each with its own `scrap_date`; this un-pivots all three
    into one (item, qty, scrap_date) series before summing, so a job
    scrapping two different sheets doesn't get silently dropped to one line.

    The write-off week is *derived* from each slot's own `scrap_date` (one
    ISO week later, always a Monday) -- **not** the sheet's own pre-typed
    `scrap_week` column, despite that column existing for exactly this
    purpose. Confirmed live 2026-10-21: trusting `scrap_week` directly gave
    an 9.8% exact-match rate against real ERP data; deriving from
    `scrap_date` the same way services.rework does from `entered_date` gave
    93.5%. Same lesson as Doors: a human-typed "intended" week drifts from
    what actually happened in SyteLine; the underlying date it was actually
    recorded on is the more reliable signal. `scrap_week`/`scrap_year`
    aren't read here anymore as a result.

    `from_weeks` is the distinct *production* week(s) (`week_num` -- when
    the job itself ran, not when the scrap was recorded) the grouped scrap
    actually came from -- shown for context, not used in the write-off-week
    calculation.
    """
    clauses, params = [], {"test_so": test_data.SO_NUMBER}
    if write_off_week is not None:
        clauses.append(f"{db.date_part('week', 'u.write_off_date')} = %(week)s")
        params["week"] = write_off_week
    if write_off_year is not None:
        clauses.append(f"{db.date_part('isoyear', 'u.write_off_date')} = %(year)s")
        params["year"] = write_off_year
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            WITH unpivoted AS (
                SELECT week_num, item, qty, sales_number, {_writeoff_date_expr()} AS write_off_date
                FROM ({_UNPIVOT_SCRAP}) base
            )
            SELECT
                {db.date_part('isoyear', 'u.write_off_date')} AS write_off_year,
                {db.date_part('week', 'u.write_off_date')} AS write_off_week,
                u.item, i.description,
                SUM(u.qty) AS total_qty,
                {db.sorted_array('u.week_num')} AS from_weeks,
                COUNT(*) AS line_count,
                MAX(CASE WHEN LOWER(u.sales_number) = LOWER(%(test_so)s) THEN 1 ELSE 0 END) AS includes_test_data
            FROM unpivoted u
            LEFT JOIN items i ON i.part_number = u.item
            {where}
            GROUP BY write_off_year, write_off_week, u.item, i.description
            ORDER BY write_off_year DESC, write_off_week DESC, u.item
            """,
            params,
        )
        rows = cur.fetchall()

    erp_actuals = erp_reconciliation.erp_actuals_by_item_week()
    for row in rows:
        match = erp_actuals.get((row["item"], row["write_off_year"], row["write_off_week"]))
        row["erp_qty"] = match["qty"] if match else None
        row["erp_cost"] = match["cost"] if match else None
    return rows


def list_available_scrap_weeks() -> list[dict]:
    """Distinct (write_off_year, write_off_week) pairs with real data, most
    recent first -- for the write-off week filter dropdown."""
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT DISTINCT
                {db.date_part('isoyear', 'write_off_date')} AS write_off_year,
                {db.date_part('week', 'write_off_date')} AS write_off_week
            FROM (
                SELECT {_writeoff_date_expr()} AS write_off_date
                FROM ({_UNPIVOT_SCRAP}) base
            ) w
            ORDER BY write_off_year DESC, write_off_week DESC
            """
        )
        return cur.fetchall()


# ── Entry form: create + reopen-to-edit ─────────────────────────────────────

def get_event(event_id: int) -> dict | None:
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT * FROM turret_events WHERE id = %s", (event_id,))
        return cur.fetchone()


def create_event(payload: dict, user_id: int | None) -> int:
    """Saves a job's material usage -- stage one of the two-stage workflow
    (see module docstring). No rework/scrap here; that's added later via
    update_event, reopening this same row.

    `week_num` -- the job's own production week, shown as "Production week(s)" on
    the Scrap write-off tab -- is stamped here from `event_date`'s own ISO
    week (same ISO week definition used everywhere else in
    this app). Historical imported rows carry the old spreadsheet's own
    hand-typed week column instead; this is the web-form equivalent, set
    once at creation and never touched again by update_event, same "stamped
    once" convention as scrap_date."""
    _validate(payload)
    event_date = datetime.date.fromisoformat(str(payload["event_date"]))
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO turret_events (
                event_date, week_num, door_type, sales_number, job_number, colour,
                sheet_a, qty_a_ordered, sheet_b, qty_b_ordered, sheet_c, qty_c_ordered,
                comments, entered_by_user_id
            ) VALUES (
                %(event_date)s, %(week_num)s, %(door_type)s, %(sales_number)s, %(job_number)s, %(colour)s,
                %(sheet_a)s, %(qty_a)s, %(sheet_b)s, %(qty_b)s, %(sheet_c)s, %(qty_c)s,
                %(notes)s, %(user_id)s
            )
            RETURNING id
            """,
            {
                "event_date": event_date,
                "week_num": event_date.isocalendar()[1],
                "door_type": payload.get("door_type") or None,
                "sales_number": payload.get("sales_number") or None,
                "job_number": payload.get("job_number") or None,
                "colour": payload.get("colour") or None,
                "sheet_a": payload.get("sheet_a") or None,
                "qty_a": payload.get("qty_a") or None,
                "sheet_b": payload.get("sheet_b") or None,
                "qty_b": payload.get("qty_b") or None,
                "sheet_c": payload.get("sheet_c") or None,
                "qty_c": payload.get("qty_c") or None,
                "notes": payload.get("notes") or None,
                "user_id": user_id,
            },
        )
        return cur.fetchone()["id"]


def update_event(event_id: int, payload: dict) -> None:
    """Reopens an existing entry -- lets the operator correct the original
    job-materials fields and/or add rework/scrap. A rework material slot's
    `scrap_date` is stamped to *today* the first time that slot gets scrap
    data, server-side, and preserved on every later edit after that -- not
    something the operator sets directly, and not re-stamped just because
    the row gets saved again. The date something was actually recorded is
    what the Scrap write-off tab's ERP reconciliation depends on (same
    lesson as Doors' entered_date -- see CLAUDE.md, "Scrap write-off
    (Doors)").

    `scrap_cost` (the same single column historical imported rows already
    carry from the old spreadsheet) is recomputed here on every save for
    web-form rows -- qty x std_cost per scrap slot
    (services.costing.compute_sheet_scrap_cost), summed across however many
    of the 3 slots have scrap recorded. Always recomputed server-side from
    current item costs, never trusted from the client, same rule as every
    other cost figure in this app (see services/costing.py)."""
    _validate(payload)
    existing = get_event(event_id)
    if existing is None:
        raise ValueError(f"turret_events {event_id} not found")
    today = datetime.date.today()

    fields = {
        "event_date": payload["event_date"],
        "door_type": payload.get("door_type") or None,
        "sales_number": payload.get("sales_number") or None,
        "job_number": payload.get("job_number") or None,
        "colour": payload.get("colour") or None,
        "comments": payload.get("notes") or None,
        "rework_type": payload.get("rework_type") or None,
        "reason": payload.get("reason") or None,
    }
    scrap_cost_total = None
    for slot in SHEET_SLOTS:
        fields[f"sheet_{slot}"] = payload.get(f"sheet_{slot}") or None
        fields[f"qty_{slot}_ordered"] = payload.get(f"qty_{slot}") or None

        scrap_sheet = payload.get(f"scrap_sheet_{slot}") or None
        scrap_qty = payload.get(f"scrap_qty_{slot}") or None
        fields[f"scrap_sheet_{slot}"] = scrap_sheet
        fields[f"scrap_qty_{slot}"] = scrap_qty
        if not (scrap_sheet or scrap_qty):
            fields[f"scrap_date_{slot}"] = None
        elif existing.get(f"scrap_date_{slot}"):
            fields[f"scrap_date_{slot}"] = existing[f"scrap_date_{slot}"]
        else:
            fields[f"scrap_date_{slot}"] = today

        slot_cost = compute_sheet_scrap_cost(scrap_qty, reference_data.get_item(scrap_sheet) if scrap_sheet else None)
        if slot_cost is not None:
            scrap_cost_total = (scrap_cost_total or 0) + slot_cost
    fields["scrap_cost"] = round(scrap_cost_total, 2) if scrap_cost_total is not None else None

    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE turret_events SET
                event_date = %(event_date)s, door_type = %(door_type)s,
                sales_number = %(sales_number)s, job_number = %(job_number)s, colour = %(colour)s,
                sheet_a = %(sheet_a)s, qty_a_ordered = %(qty_a_ordered)s,
                sheet_b = %(sheet_b)s, qty_b_ordered = %(qty_b_ordered)s,
                sheet_c = %(sheet_c)s, qty_c_ordered = %(qty_c_ordered)s,
                scrap_sheet_a = %(scrap_sheet_a)s, scrap_qty_a = %(scrap_qty_a)s, scrap_date_a = %(scrap_date_a)s,
                scrap_sheet_b = %(scrap_sheet_b)s, scrap_qty_b = %(scrap_qty_b)s, scrap_date_b = %(scrap_date_b)s,
                scrap_sheet_c = %(scrap_sheet_c)s, scrap_qty_c = %(scrap_qty_c)s, scrap_date_c = %(scrap_date_c)s,
                rework_type = %(rework_type)s, reason = %(reason)s, scrap_cost = %(scrap_cost)s,
                comments = %(comments)s, updated_at = now()
            WHERE id = %(event_id)s
            """,
            {**fields, "event_id": event_id},
        )
