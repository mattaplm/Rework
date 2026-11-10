"""Turret log: reads for the list/write-off/daily-usage pages, plus the entry
form's create/reopen-to-edit flow (2026-10-21).

Historically-imported rows (services/turret_import.py) are scrap-only --
the importer only ever inserts a row that already had scrap recorded (see
that module's docstring), and that scrap lives on turret_events' own
scrap_* columns. New web-form rows don't have that constraint:
`create_event` saves a job's material usage, usually with no rework at all,
and `update_event` reopens that same row later to add it, same two-stage
workflow as the real paper/spreadsheet process this replaces.

The form works from the job number (2026-11-11): job number is required,
the SO number is optional and auto-filled from the cached order. Material 1
is optional too -- a job run entirely on an off-BOM sheet goes in "Other".
A job run across several days is one entry per day, all sharing the job
number (`list_entries_for_job`); each day's usage then lands on its own
date in Daily Usage.

A job can have any number of reworks (2026-11-04), each with its own type,
reason and up to 3 scrapped materials -- stored one row per rework in
`turret_reworks` (migration 0017). turret_events.scrap_cost stays the job's
total across all its reworks.
"""

from __future__ import annotations

import datetime

import db
from services import erp_lookup, erp_reconciliation, reference_data, test_data
from services.costing import compute_sheet_scrap_cost

SHEET_SLOTS = ("a", "b", "c")
REWORK_TYPES = ("Replacement Parts", "Rework Entire Door")

REQUIRED_FIELDS = ("job_number", "door_type", "colour")

# Daily Usage tab periods, in dropdown order.
USAGE_PERIODS = (
    ("today", "Today"), ("yesterday", "Yesterday"),
    ("this_week", "This week"), ("last_week", "Last week"),
    ("this_month", "This month"), ("last_month", "Last month"),
    ("custom", "Custom range"),
)


class ValidationError(Exception):
    def __init__(self, errors: dict[str, str]):
        self.errors = errors
        super().__init__(", ".join(f"{k}: {v}" for k, v in errors.items()))


def _today() -> datetime.date:
    """NZ wall-clock date (the host runs UTC)."""
    return db.nz_now().date()


def _event_date(payload: dict, default: datetime.date) -> datetime.date:
    """The entry's date -- operator-editable since 2026-11-11 (back-dating a
    missed entry, or logging each day of a multi-day job). Blank falls back
    to `default`; a future date is refused."""
    raw = str(payload.get("event_date") or "").strip()
    if not raw:
        return default
    try:
        value = datetime.date.fromisoformat(raw[:10])
    except ValueError:
        raise ValidationError({"event_date": "Not a valid date."})
    if value > _today():
        raise ValidationError({"event_date": "Can't be in the future."})
    return value


def _clean_reworks(payload: dict) -> list[dict]:
    """Normalises payload["reworks"] -- a list of {id, rework_type, reason,
    materials: [{sheet, qty}, ...up to 3]} -- dropping any rework the operator
    left completely blank."""
    cleaned, errors = [], {}
    for index, raw in enumerate(payload.get("reworks") or []):
        if not isinstance(raw, dict):
            continue
        rework_type = str(raw.get("rework_type") or "").strip() or None
        reason = str(raw.get("reason") or "").strip() or None
        materials = []
        for m in (raw.get("materials") or [])[: len(SHEET_SLOTS)]:
            m = m if isinstance(m, dict) else {}
            sheet = str(m.get("sheet") or "").strip() or None
            qty = m.get("qty")
            materials.append({"sheet": sheet, "qty": None if qty in (None, "") else qty})
        if not (rework_type or reason or any(m["sheet"] or m["qty"] is not None for m in materials)):
            continue
        if rework_type and rework_type not in REWORK_TYPES:
            errors[f"reworks.{index}.rework_type"] = f"Must be one of {', '.join(REWORK_TYPES)}."
        cleaned.append({"id": raw.get("id"), "rework_type": rework_type, "reason": reason, "materials": materials})
    if errors:
        raise ValidationError(errors)
    return cleaned


def _validate(payload: dict) -> list[dict]:
    errors: dict[str, str] = {}
    for field in REQUIRED_FIELDS:
        if not str(payload.get(field) or "").strip():
            errors[field] = "Required."
    if errors:
        raise ValidationError(errors)
    return _clean_reworks(payload)


def list_events(limit: int = 200, offset: int = 0, filters: dict | None = None) -> list[dict]:
    filters = filters or {}
    clauses, params = [], {}

    if filters.get("year"):
        clauses.append(f"{db.date_part('year', 'e.event_date')} = %(year)s")
        params["year"] = int(filters["year"])
    if filters.get("month"):
        clauses.append(f"{db.date_part('month', 'e.event_date')} = %(month)s")
        params["month"] = int(filters["month"])
    if filters.get("door_type"):
        clauses.append("e.door_type = %(door_type)s")
        params["door_type"] = filters["door_type"]
    if filters.get("job_number"):
        clauses.append("LOWER(e.job_number) LIKE LOWER(%(job_number)s)")
        params["job_number"] = f"%{filters['job_number'].strip()}%"
    if filters.get("sales_number"):
        clauses.append("LOWER(e.sales_number) LIKE LOWER(%(sales_number)s)")
        params["sales_number"] = f"%{filters['sales_number'].strip()}%"

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params["limit"] = limit
    params["offset"] = offset

    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT e.*, r.rework_qty, r.rework_count
            FROM turret_events e
            LEFT JOIN (
                SELECT turret_event_id,
                       SUM(COALESCE(scrap_qty_a, 0) + COALESCE(scrap_qty_b, 0) + COALESCE(scrap_qty_c, 0)) AS rework_qty,
                       COUNT(*) AS rework_count
                FROM turret_reworks GROUP BY turret_event_id
            ) r ON r.turret_event_id = e.id
            {where}
            ORDER BY e.event_date DESC, e.id DESC LIMIT %(limit)s OFFSET %(offset)s
            """,
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


def list_options(table: str) -> list[str]:
    """Active Open / Variation picklist values (Admin -> Turret Open /
    Turret Variations)."""
    if table not in ("turret_open_options", "turret_variations"):
        raise ValueError(table)
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute(f"SELECT name FROM {table} WHERE active ORDER BY sort_order, name")
        return [r["name"] for r in cur.fetchall()]


# Every scrap recording, one row per (row or rework, slot): historical imported
# rows keep theirs on turret_events itself; web-form reworks (any number per
# job) live in turret_reworks.
_UNPIVOT_SCRAP = " UNION ALL ".join(
    [
        f"SELECT week_num, scrap_sheet_{s} AS item, scrap_qty_{s} AS qty, scrap_date_{s} AS scrap_date, sales_number "
        f"FROM turret_events WHERE scrap_qty_{s} IS NOT NULL AND scrap_date_{s} IS NOT NULL"
        for s in SHEET_SLOTS
    ]
    + [
        f"SELECT e.week_num, r.scrap_sheet_{s} AS item, r.scrap_qty_{s} AS qty, r.scrap_date_{s} AS scrap_date, e.sales_number "
        f"FROM turret_reworks r JOIN turret_events e ON e.id = r.turret_event_id "
        f"WHERE r.scrap_qty_{s} IS NOT NULL AND r.scrap_date_{s} IS NOT NULL"
        for s in SHEET_SLOTS
    ]
)


def _writeoff_date_expr() -> str:
    return db.date_shift(db.week_start("scrap_date"), 7)


def scrap_summary_by_week(write_off_week: int | None = None, write_off_year: int | None = None) -> list[dict]:
    """Scrap logged in turret_events, grouped by the week it's due for
    write-off in ERP and item. Un-pivots every scrap slot (historical row
    slots and every web-form rework's slots) into one (item, qty, scrap_date)
    series before summing, so nothing gets silently dropped to one line.

    The write-off week is *derived* from each slot's own `scrap_date` (one
    ISO week later, always a Monday) -- **not** the sheet's own pre-typed
    `scrap_week` column, despite that column existing for exactly this
    purpose. Confirmed live 2026-10-21: trusting `scrap_week` directly gave
    an 9.8% exact-match rate against real ERP data; deriving from
    `scrap_date` the same way services.rework does from `entered_date` gave
    93.5%.

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

_SCRAP_COLUMNS = [f"scrap_{k}_{s}" for s in SHEET_SLOTS for k in ("sheet", "qty", "date")]


def _legacy_rework(event: dict) -> dict | None:
    """A historical imported row keeps its scrap on turret_events itself --
    surfaced to the form as one rework with id "legacy", so editing it keeps
    its original scrap dates (it moves into turret_reworks on that save)."""
    has_scrap = any(event.get(f"scrap_sheet_{s}") or event.get(f"scrap_qty_{s}") is not None for s in SHEET_SLOTS)
    if not (has_scrap or event.get("rework_type") or event.get("reason")):
        return None
    return {"id": "legacy", "rework_type": event.get("rework_type"), "reason": event.get("reason"),
            "scrap_cost": event.get("scrap_cost"), **{c: event.get(c) for c in _SCRAP_COLUMNS}}


def get_event(event_id: int) -> dict | None:
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT * FROM turret_events WHERE id = %s", (event_id,))
        event = cur.fetchone()
        if event is None:
            return None
        cur.execute("SELECT * FROM turret_reworks WHERE turret_event_id = %s ORDER BY position, id", (event_id,))
        reworks = cur.fetchall()
    legacy = _legacy_rework(event)
    event["reworks"] = ([legacy] if legacy else []) + list(reworks)
    return event


def _rework_rows(reworks: list[dict], existing: dict | None) -> tuple[list[dict], float | None]:
    """Turns cleaned reworks into turret_reworks column values.

    A material slot's `scrap_date` is stamped to today the first time it gets
    scrap data and preserved on every later save (matched by rework id +
    slot) -- the date it was actually recorded is what the Scrap write-off
    tab's ERP reconciliation keys on (same lesson as Doors' entered_date, see
    CLAUDE.md). Each rework's scrap_cost is qty x std_cost per slot, always
    recomputed server-side; returns the rows plus the job's total."""
    today = _today()
    previous = {str(r["id"]): r for r in (existing or {}).get("reworks") or []}
    rows, total = [], None
    for position, rw in enumerate(reworks):
        before = previous.get(str(rw["id"])) if rw.get("id") is not None else None
        keep_id = before["id"] if before and before["id"] != "legacy" else None
        row = {"id": keep_id, "position": position, "rework_type": rw["rework_type"], "reason": rw["reason"]}
        cost = None
        for i, slot in enumerate(SHEET_SLOTS):
            m = rw["materials"][i] if i < len(rw["materials"]) else {"sheet": None, "qty": None}
            row[f"scrap_sheet_{slot}"] = m["sheet"]
            row[f"scrap_qty_{slot}"] = m["qty"]
            if not (m["sheet"] or m["qty"] is not None):
                row[f"scrap_date_{slot}"] = None
            elif before and before.get(f"scrap_date_{slot}"):
                row[f"scrap_date_{slot}"] = before[f"scrap_date_{slot}"]
            else:
                row[f"scrap_date_{slot}"] = today
            slot_cost = compute_sheet_scrap_cost(m["qty"], reference_data.get_item(m["sheet"]) if m["sheet"] else None)
            if slot_cost is not None:
                cost = (cost or 0) + slot_cost
        row["scrap_cost"] = round(cost, 2) if cost is not None else None
        if cost is not None:
            total = (total or 0) + cost
        rows.append(row)
    return rows, (round(total, 2) if total is not None else None)


_REWORK_COLUMNS = ["position", "rework_type", "reason"] + _SCRAP_COLUMNS + ["scrap_cost"]


def _write_reworks(cur, event_id: int, rows: list[dict]) -> None:
    """Upserts this job's reworks: updates ones that still exist (keeping
    their ids), inserts new ones, deletes any the operator removed."""
    keep_ids = {r["id"] for r in rows if r["id"] is not None}
    cur.execute("SELECT id FROM turret_reworks WHERE turret_event_id = %s", (event_id,))
    for r in cur.fetchall():
        if r["id"] not in keep_ids:
            cur.execute("DELETE FROM turret_reworks WHERE id = %s", (r["id"],))
    for row in rows:
        values = {c: row[c] for c in _REWORK_COLUMNS}
        if row["id"] is not None:
            sets = ", ".join(f"{c} = %({c})s" for c in _REWORK_COLUMNS)
            cur.execute(f"UPDATE turret_reworks SET {sets} WHERE id = %(id)s AND turret_event_id = %(event_id)s",
                        {**values, "id": row["id"], "event_id": event_id})
        else:
            cols = ", ".join(_REWORK_COLUMNS)
            vals = ", ".join(f"%({c})s" for c in _REWORK_COLUMNS)
            cur.execute(f"INSERT INTO turret_reworks (turret_event_id, {cols}) VALUES (%(event_id)s, {vals})",
                        {**values, "event_id": event_id})


def _job_fields(payload: dict) -> dict:
    fields = {
        "door_type": payload.get("door_type") or None,
        "sales_number": payload.get("sales_number") or None,
        "job_number": erp_lookup.normalize_job_number(payload.get("job_number") or "") or None,
        "colour": payload.get("colour") or None,
        "open_status": payload.get("open_status") or None,
        "variation": payload.get("variation") or None,
        "comments": payload.get("notes") or None,
    }
    for slot in SHEET_SLOTS:
        fields[f"sheet_{slot}"] = payload.get(f"sheet_{slot}") or None
        fields[f"qty_{slot}_ordered"] = payload.get(f"qty_{slot}") or None
    return fields


def create_event(payload: dict, user_id: int | None) -> int:
    """Saves a job's material usage (plus any reworks already known).

    `event_date` is the operator's chosen date (default today, NZ). `week_num`
    (the job's production week, shown as "Production week(s)" on the Scrap
    write-off tab) is always that date's ISO week, kept in step by
    update_event if the date is corrected."""
    reworks = _validate(payload)
    event_date = _event_date(payload, _today())
    rows, total_cost = _rework_rows(reworks, None)
    fields = _job_fields(payload)
    cols = list(fields)
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO turret_events (event_date, week_num, entered_by_user_id, scrap_cost, {', '.join(cols)}) "
            f"VALUES (%(event_date)s, %(week_num)s, %(user_id)s, %(scrap_cost)s, "
            f"{', '.join(f'%({c})s' for c in cols)}) RETURNING id",
            {**fields, "event_date": event_date, "week_num": event_date.isocalendar()[1],
             "user_id": user_id, "scrap_cost": total_cost},
        )
        event_id = cur.fetchone()["id"]
        _write_reworks(cur, event_id, rows)
        return event_id


def update_event(event_id: int, payload: dict) -> None:
    """Reopens an existing entry -- correct the job fields and add, change or
    remove reworks. The entry date only changes if the payload sends a new
    one (week_num follows it). A historical row's own
    scrap columns (the "legacy" rework) move into turret_reworks on its first
    save here, keeping their original scrap dates. turret_events.scrap_cost
    becomes the sum of the row's reworks, recomputed on every save."""
    reworks = _validate(payload)
    existing = get_event(event_id)
    if existing is None:
        raise ValueError(f"turret_events {event_id} not found")
    rows, total_cost = _rework_rows(reworks, existing)
    event_date = _event_date(payload, existing["event_date"])
    fields = {**_job_fields(payload), "event_date": event_date, "week_num": event_date.isocalendar()[1],
              "rework_type": None, "reason": None,
              **{c: None for c in _SCRAP_COLUMNS}, "scrap_cost": total_cost}
    sets = ", ".join(f"{c} = %({c})s" for c in fields)
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute(f"UPDATE turret_events SET {sets}, updated_at = now() WHERE id = %(event_id)s",
                    {**fields, "event_id": event_id})
        _write_reworks(cur, event_id, rows)


def list_entries_for_job(job_number: str, exclude_id: int | None = None) -> list[dict]:
    """Every entry already logged against this job, oldest first -- the entry
    form shows these so a multi-day job is logged as "another day" rather
    than by accident."""
    job = erp_lookup.normalize_job_number(job_number)
    if not job:
        return []
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id, event_date, sheet_a, qty_a_ordered, sheet_b, qty_b_ordered, sheet_c, qty_c_ordered "
            "FROM turret_events WHERE LOWER(job_number) = LOWER(%s) AND id <> %s ORDER BY event_date, id",
            (job, exclude_id or 0),
        )
        return cur.fetchall()


# ── Daily Usage ─────────────────────────────────────────────────────────────

def usage_period(key: str | None, start: str | None = None, end: str | None = None,
                 today: datetime.date | None = None) -> tuple[str, datetime.date, datetime.date]:
    """(key, start, end), inclusive, for a Daily Usage period. Weeks run
    Monday-Sunday, same as every other week in this app."""
    today = today or _today()
    key = key if key in dict(USAGE_PERIODS) else "today"
    monday = today - datetime.timedelta(days=today.weekday())
    first = today.replace(day=1)
    if key == "yesterday":
        day = today - datetime.timedelta(days=1)
        return key, day, day
    if key == "this_week":
        return key, monday, monday + datetime.timedelta(days=6)
    if key == "last_week":
        return key, monday - datetime.timedelta(days=7), monday - datetime.timedelta(days=1)
    if key == "this_month":
        next_first = (first + datetime.timedelta(days=32)).replace(day=1)
        return key, first, next_first - datetime.timedelta(days=1)
    if key == "last_month":
        last_day = first - datetime.timedelta(days=1)
        return key, last_day.replace(day=1), last_day
    if key == "custom":
        try:
            s = datetime.date.fromisoformat(start) if start else today
            e = datetime.date.fromisoformat(end) if end else s
        except ValueError:
            s = e = today
        return key, min(s, e), max(s, e)
    return key, today, today


def daily_usage(start: datetime.date, end: datetime.date, include_test: bool = False) -> list[dict]:
    """Tally of sheet material per item between start and end (inclusive).

    `used` = Material 1/2/Other quantities on jobs entered in the period (by
    entry date). `scrapped` = rework/scrap recorded in the period (by each
    slot's own scrap date). `jobs` = how many separate entries used it."""
    test_clause = "" if include_test else "AND (sales_number IS NULL OR LOWER(sales_number) <> LOWER(%(test_so)s))"
    used_sql = " UNION ALL ".join(
        f"SELECT id AS event_id, sheet_{s} AS item, qty_{s}_ordered AS qty, sales_number FROM turret_events "
        f"WHERE sheet_{s} IS NOT NULL AND event_date BETWEEN %(start)s AND %(end)s"
        for s in SHEET_SLOTS
    )
    params = {"start": start, "end": end, "test_so": test_data.SO_NUMBER}
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"SELECT item, SUM(COALESCE(qty, 0)) AS used, COUNT(DISTINCT event_id) AS jobs "
            f"FROM ({used_sql}) u WHERE 1 = 1 {test_clause} GROUP BY item",
            params,
        )
        used = cur.fetchall()
        cur.execute(
            f"SELECT item, SUM(qty) AS scrapped FROM ({_UNPIVOT_SCRAP}) s "
            f"WHERE item IS NOT NULL AND scrap_date BETWEEN %(start)s AND %(end)s {test_clause} GROUP BY item",
            params,
        )
        scrapped = cur.fetchall()
        codes = sorted({r["item"] for r in used} | {r["item"] for r in scrapped})
        descriptions = {}
        if codes:
            cur.execute(f"SELECT part_number, description FROM items WHERE {db.in_values('part_number', '%s')}",
                        (codes,))
            descriptions = {r["part_number"]: r["description"] for r in cur.fetchall()}

    tally = {c: {"item": c, "description": descriptions.get(c), "used": 0.0, "scrapped": 0.0, "jobs": 0}
             for c in codes}
    for r in used:
        tally[r["item"]]["used"] = float(r["used"] or 0)
        tally[r["item"]]["jobs"] = int(r["jobs"] or 0)
    for r in scrapped:
        tally[r["item"]]["scrapped"] = float(r["scrapped"] or 0)
    for row in tally.values():
        row["total"] = row["used"] + row["scrapped"]
    return sorted(tally.values(), key=lambda r: (-r["total"], r["item"]))
