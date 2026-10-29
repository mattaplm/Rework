"""Core rework/scrap log: create and list `rework_events` rows.

`create_event` always recomputes cost server-side from the current item/rate
data -- a client-side preview is for feedback only and is never trusted for
what gets stored. Same principle for "Scrap Entire Door": the client may send
a job's material total it got from /api/orders/<so>, but create_event ignores
it and re-derives the real figure itself from SO number alone (see
_full_door_material_cost below), so a tampered or stale client-side number
can never land in the database.
"""

from __future__ import annotations

import logging

import db
from services import erp_lookup, erp_reconciliation, reference_data, test_data
from services.costing import COMPONENTS, compute_costs

logger = logging.getLogger(__name__)

VALID_TYPES = ("Rework / Recoat", "Replace Part", "Scrap Entire Door")

REQUIRED_FIELDS = (
    "rework_date", "type", "so_number", "product_code", "quantity",
    "reason", "colour", "door_type", "work_centre",
)


class ValidationError(Exception):
    def __init__(self, errors: dict[str, str]):
        self.errors = errors
        super().__init__(", ".join(f"{k}: {v}" for k, v in errors.items()))


def _validate(payload: dict) -> dict:
    errors: dict[str, str] = {}
    for field in REQUIRED_FIELDS:
        if not str(payload.get(field) or "").strip():
            errors[field] = "Required."

    if payload.get("type") and payload["type"] not in VALID_TYPES:
        errors["type"] = f"Must be one of {', '.join(VALID_TYPES)}."

    try:
        qty = float(payload.get("quantity") or 0)
        if qty <= 0:
            errors["quantity"] = "Must be greater than 0."
    except (TypeError, ValueError):
        errors["quantity"] = "Must be a number."

    if payload.get("component") not in (None, "", *COMPONENTS):
        errors["component"] = f"Must be one of {', '.join(COMPONENTS)}."

    if payload.get("reason") and not reference_data.get_reason(payload["reason"]):
        errors["reason"] = "Not a recognised reason."

    if errors:
        raise ValidationError(errors)
    return payload


def _optional_float(payload: dict, key: str):
    val = payload.get(key)
    if val in (None, ""):
        return None
    return float(val)


def _full_door_material_cost(payload: dict) -> float | None:
    if payload.get("type") != "Scrap Entire Door" or not payload.get("so_number"):
        return None
    try:
        order = erp_lookup.lookup_order(payload["so_number"])
    except Exception:
        logger.exception("Order lookup failed for %s", payload.get("so_number"))
        return None
    return order["full_door_material_cost"] if order else None


def resolve_piece_basis(payload: dict) -> dict:
    """What Qty to Remove needs beyond the item itself, re-derived server-side
    (never trusted from the client): the job's own material qty for this part
    and how many of the chosen component (Stile/Rail) one door of this order's
    CPQ code has. Only applies to Replace Part with a component picked; any
    other case returns Nones and costing falls back to the per-item rule.
    `error` is set when the choice can't be right (door has none of that
    component, or more pieces scrapped than the door has)."""
    out = {"component": None, "job_material_qty": None, "pieces_per_door": None, "error": None}
    component = payload.get("component")
    if payload.get("type") != "Replace Part" or component not in COMPONENTS or not payload.get("so_number"):
        return out
    out["component"] = component
    try:
        order = erp_lookup.lookup_order(payload["so_number"])
    except Exception:
        logger.exception("Order lookup failed for %s", payload.get("so_number"))
        return out
    if not order:
        return out
    code = str(payload.get("product_code") or "").strip().upper()
    match = next((m for m in order["materials"] if m["part_number"].upper() == code and m["qty"] is not None), None)
    pieces = (order.get("door_pieces") or {}).get(component)
    if pieces is None or match is None:
        return out  # not configured / not on this job -- costing falls back to the item rule
    if pieces == 0:
        out["error"] = f"This door has no {component.lower()}s."
        return out
    try:
        if float(payload.get("quantity") or 0) > pieces:
            out["error"] = f"This door only has {pieces} {component.lower()}{'s' if pieces != 1 else ''}."
            return out
    except (TypeError, ValueError):
        pass
    out["job_material_qty"] = float(match["qty"])
    out["pieces_per_door"] = pieces
    return out


def create_event(payload: dict, user_id: int | None, charge_flat: bool = True) -> dict:
    _validate(payload)

    item = reference_data.get_item(payload["product_code"])
    reason = reference_data.get_reason(payload["reason"])
    quantity = float(payload["quantity"])
    full_door_cost = _full_door_material_cost(payload)

    basis = resolve_piece_basis(payload)
    if basis["error"]:
        raise ValidationError({"quantity": basis["error"]})
    costs = compute_costs(payload["type"], quantity, item, full_door_cost,
                          basis["job_material_qty"], basis["pieces_per_door"])
    if payload["type"] == "Rework / Recoat" and not charge_flat:
        costs.material_cost = 0.0  # the flat recoat charge is per entry, not per material line

    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO rework_events (
                rework_date, due_date, type, so_number, product_code, quantity,
                height_mm, width_mm, cut_length_mm,
                qty_to_remove, material_cost, component,
                reason, source, colour, door_type, work_centre, notes, entered_by_user_id
            ) VALUES (
                %(rework_date)s, %(due_date)s, %(type)s, %(so_number)s, %(product_code)s, %(quantity)s,
                %(height_mm)s, %(width_mm)s, %(cut_length_mm)s,
                %(qty_to_remove)s, %(material_cost)s, %(component)s,
                %(reason)s, %(source)s, %(colour)s, %(door_type)s, %(work_centre)s, %(notes)s, %(entered_by_user_id)s
            ) RETURNING *
            """,
            {
                "rework_date": payload["rework_date"],
                "due_date": payload.get("due_date") or None,
                "type": payload["type"],
                "so_number": payload["so_number"].strip(),
                "product_code": payload["product_code"].strip().upper(),
                "quantity": quantity,
                "height_mm": _optional_float(payload, "height_mm"),
                "width_mm": _optional_float(payload, "width_mm"),
                "cut_length_mm": _optional_float(payload, "cut_length_mm"),
                "qty_to_remove": costs.qty_to_remove,
                "material_cost": costs.material_cost,
                "component": basis["component"],
                "reason": payload["reason"],
                "source": reason["source"] if reason else None,
                "colour": payload["colour"],
                "door_type": payload["door_type"],
                "work_centre": payload["work_centre"],
                "notes": (payload.get("notes") or "").strip() or None,
                "entered_by_user_id": user_id,
            },
        )
        return cur.fetchone()


LINE_FIELDS = ("product_code", "quantity", "component")


def create_events(payload: dict, user_id: int | None) -> list[dict]:
    """One entry can rework several materials (1, 2, 3 or more). The form
    sends the shared fields once plus `materials: [{product_code, quantity,
    component}, ...]`; each material becomes its own rework_events row (so the
    log, write-off tab and dashboard keep working per part). Every line is
    validated before any is written. A payload with no `materials` key is a
    single line taken from the top-level fields, as before."""
    base = {k: v for k, v in payload.items() if k != "materials"}
    lines = payload.get("materials") or [{k: payload.get(k) for k in LINE_FIELDS}]
    merged = [{**base, **{k: line.get(k) for k in LINE_FIELDS}} for line in lines]

    errors: dict[str, str] = {}
    if len(merged) > 1 and base.get("type") == "Scrap Entire Door":
        errors["materials"] = "Scrap Entire Door is a single line (the whole door)."
    for i, line in enumerate(merged):
        prefix = f"line{i + 1}." if len(merged) > 1 else ""
        try:
            _validate(line)
            basis = resolve_piece_basis(line)
            if basis["error"]:
                errors[prefix + "quantity"] = basis["error"]
        except ValidationError as exc:
            errors.update({prefix + k: v for k, v in exc.errors.items()})
    if errors:
        raise ValidationError(errors)

    return [create_event(line, user_id, charge_flat=(i == 0)) for i, line in enumerate(merged)]


def list_events(limit: int = 100, offset: int = 0, filters: dict | None = None) -> list[dict]:
    filters = filters or {}
    clauses, params = [], {}

    if filters.get("year"):
        clauses.append(f"{db.date_part('year', 'rework_date')} = %(year)s")
        params["year"] = int(filters["year"])
    if filters.get("month"):
        clauses.append(f"{db.date_part('month', 'rework_date')} = %(month)s")
        params["month"] = int(filters["month"])
    if filters.get("door_type"):
        clauses.append("door_type = %(door_type)s")
        params["door_type"] = filters["door_type"]
    if filters.get("reason"):
        clauses.append("reason = %(reason)s")
        params["reason"] = filters["reason"]
    if filters.get("work_centre"):
        clauses.append("work_centre = %(work_centre)s")
        params["work_centre"] = filters["work_centre"]
    if filters.get("so_number"):
        clauses.append("LOWER(so_number) LIKE LOWER(%(so_number)s)")
        params["so_number"] = f"%{filters['so_number']}%"

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params["limit"] = limit
    params["offset"] = offset

    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"SELECT e.*, u.username AS entered_by "
            f"FROM rework_events e LEFT JOIN users u ON u.id = e.entered_by_user_id "
            f"{where} ORDER BY e.rework_date DESC, e.id DESC LIMIT %(limit)s OFFSET %(offset)s",
            params,
        )
        return cur.fetchall()


def list_available_years() -> list[int]:
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"SELECT DISTINCT {db.date_part('year', 'rework_date')} AS y FROM rework_events ORDER BY y DESC"
        )
        return [r["y"] for r in cur.fetchall()]


def get_event(event_id: int) -> dict | None:
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT e.*, u.username AS entered_by "
            "FROM rework_events e LEFT JOIN users u ON u.id = e.entered_by_user_id "
            "WHERE e.id = %s",
            (event_id,),
        )
        return cur.fetchone()


# ── Scrap write-off (Doors) ──────────────────────────────────────────────
#
# Doors equivalent of services.turret.scrap_summary_by_week -- same idea
# (group what's been logged by the week it's due for write-off in ERP),
# different source and a different week rule. The Turret tracker has its
# own pre-entered `scrap_week` per row (a human wrote it down); rework_events
# has no such column -- so the write-off week is *derived* here, one ISO
# week after the week the row was **entered** (`entered_date`), not the week
# the rework/defect itself happened (`rework_date`). Confirmed live
# 2026-10-21 against a real mismatch: three rows all sharing the same
# rework_date (2026-09-30) but different entered_dates (one on 2026-10-02,
# two on 2026-10-13) only had the first one actually written off in week 41
# -- the other two didn't show up until week 43, i.e. one week after *their*
# entered_date, not after the shared rework_date. Matches what the
# department confirmed is the real process: the write-off batch runs off
# whatever's been entered into the tracker that week, not off when the
# defect physically occurred -- a row logged late naturally gets swept up
# whenever it's actually entered, same as their own spreadsheet. Also
# matches the old workbook's own "Scrap Write Off Pivot" tab: write-off
# dates are always a Monday (e.g. week 40 -> 2026-10-05), i.e. the Monday of
# the week after the one being written off -- "scrap every Monday for last
# week", same note as the Turret tab's own Pivot sheet carries.
#
# Only `type = 'Replace Part'` rows appear here (2026-10-21, per the
# department: Rework/Recoat never gets written off in SyteLine at all, so
# including it overstated "ready for write-off"). `qty_to_remove` is only
# non-NULL when the row's product_code matched a real item with a `rule` set
# (services.costing.compute_costs) -- Scrap Entire Door rows use
# product_code "DOOR", which isn't a real item, so they fall out of this
# naturally too, on top of the type filter.
#
# Sheet items (erp_reconciliation.sheet_item_codes()) are excluded -- they're
# Turret's raw sheet-stock, already reconciled on that tab, so they'd
# otherwise double-count across both tabs. Plank items (e.g. 00392.215.01)
# deliberately stay IN this view -- the department confirmed those belong
# here, unlike Sheet (2026-10-21).
#
# ISO week numbers repeat every year, so grouping/filtering must pair a week
# with its ISO year (EXTRACT(ISOYEAR ...), not plain YEAR -- they can differ
# at year boundaries) to avoid merging e.g. week 1 of 2025 with week 1 of
# 2026.

def _writeoff_date_expr() -> str:
    return db.date_shift(db.week_start("entered_date"), 7)


def scrap_writeoff_summary(write_off_week: int | None = None, write_off_year: int | None = None) -> list[dict]:
    clauses, params = [], {
        "sheet_items": list(erp_reconciliation.sheet_item_codes()),
        "test_so": test_data.SO_NUMBER,
    }
    if write_off_week is not None:
        clauses.append(f"{db.date_part('week', 'write_off_date')} = %(week)s")
        params["week"] = write_off_week
    if write_off_year is not None:
        clauses.append(f"{db.date_part('isoyear', 'write_off_date')} = %(year)s")
        params["year"] = write_off_year
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            WITH scoped AS (
                SELECT product_code, qty_to_remove, so_number, {_writeoff_date_expr()} AS write_off_date
                FROM rework_events
                WHERE qty_to_remove IS NOT NULL AND type = 'Replace Part'
                  AND NOT ({db.in_values('product_code', '%(sheet_items)s')})
            )
            SELECT
                s.write_off_date,
                {db.date_part('isoyear', 's.write_off_date')} AS write_off_year,
                {db.date_part('week', 's.write_off_date')} AS write_off_week,
                {db.date_part('week', db.date_shift('s.write_off_date', -7))} AS from_week,
                s.product_code, i.description,
                SUM(s.qty_to_remove) AS total_qty,
                COUNT(*) AS line_count,
                MAX(CASE WHEN LOWER(s.so_number) = LOWER(%(test_so)s) THEN 1 ELSE 0 END) AS includes_test_data
            FROM scoped s
            LEFT JOIN items i ON i.part_number = s.product_code
            {where}
            GROUP BY s.write_off_date, s.product_code, i.description
            ORDER BY s.write_off_date DESC, s.product_code
            """,
            params,
        )
        rows = cur.fetchall()

    erp_actuals = erp_reconciliation.erp_actuals_by_item_week()
    for row in rows:
        match = erp_actuals.get((row["product_code"], row["write_off_year"], row["write_off_week"]))
        row["erp_qty"] = match["qty"] if match else None
        row["erp_cost"] = match["cost"] if match else None
    return rows


def list_available_writeoff_weeks() -> list[dict]:
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
                FROM rework_events WHERE qty_to_remove IS NOT NULL
            ) s
            ORDER BY write_off_year DESC, write_off_week DESC
            """
        )
        return cur.fetchall()
