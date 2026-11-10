"""Sales Order lookups for the entry form -- pulls dimensions/colour/job and
the job's real material lines, so Height/Width/Colour/Door Type and the
Product Code choices can be pre-filled instead of typed from memory or
searched across the whole item master.

Reads from the local synced_orders/synced_order_materials cache (refreshed
once a day by services/erp_sync.sync_orders, scheduled the same way as
items/colours -- see services/scheduled_sync.py), NOT live SyteLine. This
used to query SyteLine fresh on every single lookup, which meant every
operator opening the entry form and typing an SO number was its own live ERP
round trip -- slow even when ERP was up, and dead in the water whenever it
wasn't (which happened repeatedly during this app's own development). An SO
that was just created today and hasn't been through a sync yet simply won't
be found until the next sync runs (or someone clicks "Sync Orders Now" in
Admin) -- a deliberate trade-off for never blocking the form on a live ERP
call, not a bug.

`list_unmapped_cpq_codes` is the one exception left querying SyteLine live:
it's an on-demand admin action (Admin -> Door Codes -> "Check SyteLine for
new codes"), not something the entry form calls, so the old live-query
reasoning still applies to it unchanged.
"""

from __future__ import annotations

import re

import erp
import queries
import db
from services import reference_data


def normalize_so_number(so_number: str) -> str:
    """What an operator types -> the SO number as SyteLine writes it. Digits
    alone (with or without the S) are padded out: 566179 / s566179 ->
    S000566179. Anything else (e.g. the fake `test` order) is just trimmed."""
    text = (so_number or "").strip()
    match = re.fullmatch(r"[sS]?(\d{1,9})", text)
    return "S" + match.group(1).zfill(9) if match else text


def normalize_job_number(job_number: str) -> str:
    """Same idea as normalize_so_number for jobs: 1117852 / j1117852 ->
    J001117852. Anything else (e.g. free text like "REWORKS") is just trimmed."""
    text = (job_number or "").strip()
    match = re.fullmatch(r"[jJ]?(\d{1,9})", text)
    return "J" + match.group(1).zfill(9) if match else text


def _find_order_row(so_number: str) -> dict | None:
    """Case-insensitive, and the S000 prefix is optional (see normalize_so_number)."""
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT * FROM synced_orders WHERE LOWER(so_number) = LOWER(%s)",
                    (normalize_so_number(so_number),))
        return cur.fetchone()


def canonical_so_number(so_number: str) -> str:
    """The cached order's own spelling of this SO number if there is one, so
    entries are always saved as e.g. S000566179 however it was typed."""
    row = _find_order_row(so_number)
    return row["so_number"] if row else (so_number or "").strip()


def lookup_order(so_number: str) -> dict | None:
    row = _find_order_row(so_number)
    return _order_from_row(row) if row else None


def lookup_order_by_job(job_number: str) -> dict | None:
    """The Turret entry form works from the job number (2026-11-11) -- same
    cached order, found by its job instead of its SO number."""
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT * FROM synced_orders WHERE LOWER(job_number) = LOWER(%s) ORDER BY so_number LIMIT 1",
                    (normalize_job_number(job_number),))
        row = cur.fetchone()
    return _order_from_row(row) if row else None


def _order_from_row(row: dict) -> dict:
    materials = []
    full_door_material_cost = None
    if row.get("job_number"):
        materials = lookup_job_materials(row["job_number"])
        costed = [m for m in materials if m["qty"] is not None and m["unit_cost"] is not None]
        if costed:
            full_door_material_cost = round(sum(float(m["qty"]) * float(m["unit_cost"]) for m in costed), 2)

    return {
        "so_number": row["so_number"],
        "job_number": row.get("job_number"),
        "height": row.get("height"),
        "width": row.get("width"),
        "colour_in": reference_data.get_colour_by_code(row.get("colour_in_code")),
        "colour_out": reference_data.get_colour_by_code(row.get("colour_out_code")),
        "door_type": reference_data.get_door_type_for_cpq_code(row.get("cpq_door_code")),
        "cpq_door_code": row.get("cpq_door_code"),
        "door_pieces": reference_data.get_door_pieces(row.get("cpq_door_code")),
        "due_date": row.get("due_date"),
        "qty_ordered": row.get("qty_ordered"),
        "materials": materials,
        "full_door_material_cost": full_door_material_cost,
        "synced_at": row.get("synced_at"),
    }


def lookup_job_materials(job_number: str) -> list[dict]:
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT part_number, description, qty, unit, unit_cost "
            "FROM synced_order_materials WHERE job_number = %s ORDER BY part_number",
            (job_number.strip(),),
        )
        return cur.fetchall()


def list_unmapped_cpq_codes() -> list[str]:
    """Every CPQ door code seen on a real order that has no row in
    cpq_door_codes yet -- lets Admin -> Door Codes show exactly what's
    missing instead of an admin having to already know what codes exist.
    Still a live SyteLine query (on-demand admin action, not the entry
    form's hot path) -- see module docstring.
    """
    seen = {r["cpq_code"].strip().upper() for r in erp.fetch_all(queries.DISTINCT_CPQ_DOOR_CODES_QUERY) if r.get("cpq_code")}
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT cpq_code FROM cpq_door_codes")
        mapped = {r["cpq_code"] for r in cur.fetchall()}
    return sorted(seen - mapped)
