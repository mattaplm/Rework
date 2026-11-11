"""Hardware department's PC (powder-coat) rework/scrap log -- replaces the
"Master Data Sheet" of 'Scrap Rework - Use this one V2.xlsx' (2026-11-11).

One row per part line of a remake request: a hardware part rejected at
powder coat (PC) or assembly (AH) gets a remake requested (Request date),
a CO created (Co-create date), picked (Pick date) and completed (Complete
date). The reason decides whether the rejected parts are scrapped or
reworked -- the sheet's DATA VALIDATION tab carries a Scrap Y/N per reason,
now `hw_reasons.is_scrap`.

The sheet's formulas, ported:
  Status      = "Log Job" with no Pick date, "Open" once picked, "Closed" once
                completed. A literal "SCRAP" typed over the formula marked a
                straight scrap with no remake -- kept here as status "Scrap".
  Scrap Y/N   = VLOOKUP(Reason, DATA VALIDATION D:E)
  Unit Cost / Product / Material / Supplier / Material Cost
              = VLOOKUP(Part, Data Sheet) -- `hw_parts`, snapshotted onto the
                row when it's saved so a later cost change never rewrites it.
  Total Cost Scrap      = Unit Cost x QTY if scrapped, else 0
  Total ZINC Scrap Cost = Material Cost x QTY if scrapped, else 0
  Scrap QTY / Rework QTY = QTY on one side or the other, by Scrap Y/N.

Same never-trust-the-client rule as Doors: the form's cost figures are a
preview; the server recomputes everything on save.
"""

from __future__ import annotations

import datetime

import db
import queries
from services import erp_lookup, erp_reconciliation

STATUSES = ("Log Job", "Open", "Closed", "Scrap")
LOCATIONS = ("PC", "AH")
NAME_TABLES = {"powdercoater": "hw_powdercoaters", "assembler": "hw_assemblers"}
LOG_LIMIT = 500


class ValidationError(Exception):
    def __init__(self, errors: dict[str, str]):
        self.errors = errors
        super().__init__(", ".join(f"{k}: {v}" for k, v in errors.items()))


def _today() -> datetime.date:
    return db.nz_now().date()


def derive_status(pick_date, complete_date, scrap_only: bool) -> str:
    if scrap_only:
        return "Scrap"
    if complete_date:
        return "Closed"
    if pick_date:
        return "Open"
    return "Log Job"


def compute_costs(unit_cost, material_cost, quantity: int, is_scrap: bool) -> dict:
    def total(per_unit):
        if per_unit is None:
            return None
        return round(float(per_unit) * quantity, 2) if is_scrap else 0.0
    return {"scrap_cost": total(unit_cost), "material_scrap_cost": total(material_cost)}


# ── Reference data (the entry form's dropdowns) ─────────────────────────────

def list_reasons(active_only: bool = True) -> list[dict]:
    sql = "SELECT id, reason, is_scrap, active, sort_order FROM hw_reasons"
    if active_only:
        sql += " WHERE active"
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute(sql + " ORDER BY sort_order, reason")
        return cur.fetchall()


def get_reason(reason: str) -> dict | None:
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT reason, is_scrap, active FROM hw_reasons WHERE reason = %s", (reason,))
        return cur.fetchone()


def list_parts(active_only: bool = True) -> list[dict]:
    sql = "SELECT * FROM hw_parts"
    if active_only:
        sql += " WHERE active"
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute(sql + " ORDER BY part_number")
        return [_part_json(r) for r in cur.fetchall()]


def get_part(part_number: str) -> dict | None:
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT * FROM hw_parts WHERE part_number = %s", (part_number.strip().upper(),))
        row = cur.fetchone()
        return _part_json(row) if row else None


def _part_json(row: dict) -> dict:
    row = dict(row)
    for key in ("unit_cost", "material_cost"):
        if row.get(key) is not None:
            row[key] = float(row[key])
    return row


def list_names(field: str) -> list[str]:
    table = NAME_TABLES[field]
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute(f"SELECT name FROM {table} WHERE active ORDER BY sort_order, name")
        return [r["name"] for r in cur.fetchall()]


def list_colours() -> list[dict]:
    """ERP colours in the sheet's shape: the colour name without its Dulux
    code suffix ("APPLIANCE WHITE MATT 20S1364M" -> "APPLIANCE WHITE MATT")
    plus that code separately, the way the sheet's Colour / Colour Code
    columns always held them."""
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT name, dulux_code FROM colours WHERE active ORDER BY name")
        rows = cur.fetchall()
    seen, result = set(), []
    for r in rows:
        colour = _split_colour(r["name"], r["dulux_code"])
        key = (colour["colour"].upper(), (colour["code"] or "").upper())
        if key not in seen:
            seen.add(key)
            result.append(colour)
    return result


def _split_colour(name: str, dulux: str | None) -> dict:
    name, code = " ".join((name or "").split()), (dulux or "").strip()
    if code and name.upper().endswith(" " + code.upper()):
        name = name[: -len(code)].strip()
    return {"colour": name, "code": code or None}


def _colour_for_code(cur, code: str | None) -> dict | None:
    if not code:
        return None
    cur.execute("SELECT name, dulux_code FROM colours WHERE code = %s", (code,))
    row = cur.fetchone()
    return _split_colour(row["name"], row["dulux_code"]) if row else None


# ── SyteLine order lookups (local cache, refreshed by erp_sync.sync_orders) ──

def _line_json(cur, line: dict) -> dict:
    colour = _colour_for_code(cur, line["colour_out_code"] or line["colour_in_code"])
    cur.execute("SELECT part_number FROM synced_order_materials WHERE job_number = %s ORDER BY part_number",
                (line["job_number"],))
    materials = [r["part_number"].upper() for r in cur.fetchall()]
    return {
        "so_number": line["so_number"], "co_line": line["co_line"], "job_number": line["job_number"],
        "item": line["item"], "description": line["description"],
        "qty_ordered": float(line["qty_ordered"]) if line["qty_ordered"] is not None else None,
        "colour": colour["colour"] if colour else None, "colour_code": colour["code"] if colour else None,
        "materials": materials,
    }


def lookup_job(job_number: str) -> dict | None:
    """The cached SyteLine order line for a Hardware job: its SO, the finished
    item, colour (split the same way as list_colours) and the job's material
    part numbers, which the entry form uses to narrow the Part list."""
    job = erp_lookup.normalize_job_number(job_number)
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT * FROM hw_synced_order_lines WHERE LOWER(job_number) = LOWER(%s) "
                    "ORDER BY synced_at DESC LIMIT 1", (job,))
        line = cur.fetchone()
        return _line_json(cur, line) if line else None


def lookup_so(so_number: str) -> list[dict]:
    """Every cached line (= job) on a Hardware SO, in line order."""
    so = erp_lookup.normalize_so_number(so_number)
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT * FROM hw_synced_order_lines WHERE LOWER(so_number) = LOWER(%s) ORDER BY co_line", (so,))
        return [_line_json(cur, line) for line in cur.fetchall()]


# ── Scrap write-off vs. SyteLine ────────────────────────────────────────────
# Hardware's scrap is written off in SyteLine weekly, on the Monday after the
# week it was requested -- the same "following week" rule as Doors, keyed on
# Request date. Confirmed against the real data 2026-11-11 by testing every
# candidate (request / co-create / pick / complete date, same week or the next):
# request date + 1 week matched SyteLine's qty exactly for 44% of item-weeks
# across all of history (next best: pick date + 1 week, 32%), and ~90% every
# month since February 2026. 75% of the SCR transactions are dated a Monday.

def _writeoff_date_expr() -> str:
    return db.date_shift(db.week_start("request_date"), 7)


def writeoff_summary(write_off_year: int | None = None, write_off_week: int | None = None) -> list[dict]:
    clauses, params = ["is_scrap"], []
    if write_off_year is not None:
        clauses.append(f"{db.date_part('isoyear', _writeoff_date_expr())} = %s")
        params.append(write_off_year)
    if write_off_week is not None:
        clauses.append(f"{db.date_part('week', _writeoff_date_expr())} = %s")
        params.append(write_off_week)
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT s.write_off_date,
                   {db.date_part('isoyear', 's.write_off_date')} AS write_off_year,
                   {db.date_part('week', 's.write_off_date')} AS write_off_week,
                   s.part_number, p.product_code, p.material,
                   SUM(s.quantity) AS total_qty, SUM(s.scrap_cost) AS total_cost, COUNT(*) AS line_count
            FROM (
                SELECT part_number, quantity, scrap_cost, {_writeoff_date_expr()} AS write_off_date
                FROM hw_events WHERE {" AND ".join(clauses)}
            ) s
            LEFT JOIN hw_parts p ON p.part_number = s.part_number
            GROUP BY s.write_off_date, s.part_number, p.product_code, p.material
            ORDER BY s.write_off_date DESC, s.part_number
            """,
            params,
        )
        rows = cur.fetchall()
    actuals = erp_reconciliation.erp_actuals_by_item_week(queries.HARDWARE_SCRAP_GROUPS)
    for row in rows:
        match = actuals.get((row["part_number"], row["write_off_year"], row["write_off_week"]))
        row["erp_qty"] = float(match["qty"]) if match else None
        row["erp_cost"] = float(match["cost"]) if match and match["cost"] is not None else None
    return rows


def list_writeoff_weeks() -> list[dict]:
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"""SELECT DISTINCT {db.date_part('isoyear', 'w')} AS write_off_year, {db.date_part('week', 'w')} AS write_off_week
                FROM (SELECT {_writeoff_date_expr()} AS w FROM hw_events WHERE is_scrap) s
                ORDER BY write_off_year DESC, write_off_week DESC"""
        )
        return [r for r in cur.fetchall() if r["write_off_year"]]


# ── Entries ─────────────────────────────────────────────────────────────────

def _str(payload: dict, key: str) -> str | None:
    value = str(payload.get(key) or "").strip()
    return value or None


def _date(payload: dict, key: str, errors: dict) -> datetime.date | None:
    raw = str(payload.get(key) or "").strip()
    if not raw:
        return None
    try:
        value = datetime.date.fromisoformat(raw[:10])
    except ValueError:
        errors[key] = "Not a valid date."
        return None
    if value > _today():
        errors[key] = "Can't be in the future."
    return value


def _clean(payload: dict, existing: dict | None) -> dict:
    errors: dict[str, str] = {}
    values = {
        # Saved the way SyteLine writes them (1117852 -> J001117852), so the
        # order lookup and the PC log's SO/job filter line up.
        "so_number": erp_lookup.normalize_so_number(_str(payload, "so_number") or "") or None,
        "job_number": erp_lookup.normalize_job_number(_str(payload, "job_number") or "") or None,
        "colour": _str(payload, "colour"),
        "colour_code": _str(payload, "colour_code"),
        "location": _str(payload, "location"),
        "powdercoater": _str(payload, "powdercoater"),
        "assembler": _str(payload, "assembler"),
        "comments": _str(payload, "comments"),
        "request_date": _date(payload, "request_date", errors),
        "cocreate_date": _date(payload, "cocreate_date", errors),
        "pick_date": _date(payload, "pick_date", errors),
        "complete_date": _date(payload, "complete_date", errors),
    }
    if values["request_date"] is None and "request_date" not in errors:
        errors["request_date"] = "Required."
    if values["complete_date"] and values["pick_date"] and values["complete_date"] < values["pick_date"]:
        errors["complete_date"] = "Can't be before the pick date."
    if not values["colour"]:
        errors["colour"] = "Required."
    if values["location"] not in LOCATIONS:
        errors["location"] = "Pick PC or AH."

    part_number = (_str(payload, "part_number") or "").upper()
    part = get_part(part_number) if part_number else None
    unchanged_part = existing is not None and existing["part_number"] == part_number
    if not part_number:
        errors["part_number"] = "Required."
    elif part is None and not unchanged_part:
        errors["part_number"] = "Not in the parts list -- an admin can add it under Hardware Admin -> Parts."
    values["part_number"] = part_number

    try:
        quantity = int(str(payload.get("quantity") or "").strip())
        if quantity < 1:
            raise ValueError
    except ValueError:
        errors["quantity"] = "Must be a whole number of 1 or more."
        quantity = 0
    values["quantity"] = quantity

    reason_text = _str(payload, "reason")
    reason = get_reason(reason_text) if reason_text else None
    if not reason_text:
        errors["reason"] = "Required."
    elif reason is None and not (existing and existing["reason"] == reason_text):
        errors["reason"] = "Pick a reason from the list."
    values["reason"] = reason_text

    if errors:
        raise ValidationError(errors)

    # Scrap Y/N follows the reason (the sheet's VLOOKUP). A historical row
    # whose reason isn't in the list keeps whatever it already had.
    values["is_scrap"] = bool(reason["is_scrap"]) if reason else bool(existing and existing["is_scrap"])

    # Part fields are a snapshot: kept as-is when the part didn't change,
    # filled in from the parts list otherwise (or where the snapshot is blank,
    # e.g. an imported row whose part the sheet couldn't find).
    snapshot_keys = ("unit_cost", "material_cost", "product_code", "material", "supplier")
    for key in snapshot_keys:
        current = existing.get(key) if unchanged_part else None
        values[key] = current if current is not None else (part or {}).get(key)
    values.update(compute_costs(values["unit_cost"], values["material_cost"], quantity, values["is_scrap"]))

    scrap_only = payload.get("scrap_only") in (True, "true", "on", "1", 1)
    values["status"] = derive_status(values["pick_date"], values["complete_date"], scrap_only)
    return values


_COLUMNS = ("status", "so_number", "job_number", "part_number", "quantity", "colour", "colour_code",
            "location", "request_date", "cocreate_date", "pick_date", "complete_date", "reason",
            "is_scrap", "powdercoater", "assembler", "comments", "product_code", "material",
            "supplier", "unit_cost", "material_cost", "scrap_cost", "material_scrap_cost")


def create_event(payload: dict, user_id: int | None) -> dict:
    values = _clean(payload, None)
    columns = ", ".join(_COLUMNS)
    placeholders = ", ".join(f"%({c})s" for c in _COLUMNS)
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO hw_events ({columns}, entered_by_user_id) "
            f"VALUES ({placeholders}, %(user_id)s) RETURNING id",
            {**values, "user_id": user_id},
        )
        event_id = cur.fetchone()["id"]
    return get_event(event_id)


def update_event(event_id: int, payload: dict) -> dict:
    existing = get_event(event_id)
    if existing is None:
        raise LookupError(event_id)
    values = _clean(payload, existing)
    assignments = ", ".join(f"{c} = %({c})s" for c in _COLUMNS)
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"UPDATE hw_events SET {assignments}, updated_at = now() WHERE id = %(id)s",
            {**values, "id": event_id},
        )
    return get_event(event_id)


def get_event(event_id: int) -> dict | None:
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT * FROM hw_events WHERE id = %s", (event_id,))
        return cur.fetchone()


def event_json(event: dict) -> dict:
    out = {}
    for key, value in event.items():
        if isinstance(value, (datetime.date, datetime.datetime)):
            value = value.isoformat()
        elif value is not None and key in ("unit_cost", "material_cost", "scrap_cost", "material_scrap_cost"):
            value = float(value)
        out[key] = value
    return out


# ── PC log ──────────────────────────────────────────────────────────────────

FILTER_KEYS = ("year", "month", "status", "reason", "location", "scrap", "part", "q")


def _where(filters: dict) -> tuple[str, list]:
    clauses, params = [], []
    if filters.get("year"):
        clauses.append(f"{db.date_part('year', 'request_date')} = %s")
        params.append(int(filters["year"]))
    if filters.get("month"):
        clauses.append(f"{db.date_part('month', 'request_date')} = %s")
        params.append(int(filters["month"]))
    for key in ("status", "reason", "location"):
        if filters.get(key):
            clauses.append(f"{key} = %s")
            params.append(filters[key])
    if filters.get("scrap") in ("yes", "no"):
        clauses.append("is_scrap = %s")
        params.append(filters["scrap"] == "yes")
    if filters.get("part"):
        clauses.append("LOWER(part_number) LIKE LOWER(%s)")
        params.append(f"%{filters['part'].strip()}%")
    if filters.get("q"):
        clauses.append("(LOWER(COALESCE(so_number, '')) LIKE LOWER(%s) OR LOWER(COALESCE(job_number, '')) LIKE LOWER(%s))")
        params += [f"%{filters['q'].strip()}%"] * 2
    return (" WHERE " + " AND ".join(clauses)) if clauses else "", params


def list_events(filters: dict, limit: int = LOG_LIMIT) -> list[dict]:
    where, params = _where(filters)
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute(f"SELECT * FROM hw_events{where} ORDER BY request_date DESC, id DESC LIMIT %s",
                    params + [limit])
        return cur.fetchall()


def summary(filters: dict) -> dict:
    where, params = _where(filters)
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"""SELECT COUNT(*) AS entries,
                       COALESCE(SUM(CASE WHEN is_scrap THEN quantity ELSE 0 END), 0) AS scrap_qty,
                       COALESCE(SUM(CASE WHEN is_scrap THEN 0 ELSE quantity END), 0) AS rework_qty,
                       COALESCE(SUM(scrap_cost), 0) AS scrap_cost,
                       COALESCE(SUM(material_scrap_cost), 0) AS material_scrap_cost,
                       COALESCE(SUM(CASE WHEN status IN ('Log Job', 'Open') THEN 1 ELSE 0 END), 0) AS outstanding
                FROM hw_events{where}""",
            params,
        )
        row = cur.fetchone()
    return {k: (float(v) if k.endswith("cost") else int(v)) for k, v in row.items()}


def list_years() -> list[int]:
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute(f"SELECT DISTINCT {db.date_part('year', 'request_date')} AS y FROM hw_events ORDER BY y DESC")
        return [r["y"] for r in cur.fetchall() if r["y"]]


def list_used_reasons() -> list[str]:
    """Every reason the log actually holds -- includes historical wording that
    isn't (or is no longer) in the admin list, so the filter can still find it."""
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT DISTINCT reason FROM hw_events WHERE reason IS NOT NULL ORDER BY reason")
        return [r["reason"] for r in cur.fetchall()]
