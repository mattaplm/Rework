"""Reference-data reads: reasons, door types, work centres, colours, items.

All of these back the dropdowns on the entry form. `items` and `colours` are
also written to by `services.erp_sync`; everything else is admin-maintained
only (see blueprints/admin.py).
"""

from __future__ import annotations

import db


def list_reasons(active_only: bool = True) -> list[dict]:
    sql = "SELECT reason, code, source, fault_category FROM rework_reasons"
    if active_only:
        sql += " WHERE active"
    sql += " ORDER BY sort_order, reason"
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute(sql)
        return cur.fetchall()


def list_door_types() -> list[str]:
    """Door Types and Door Codes were merged (2026-10-20): this now reads
    DISTINCT family_name off cpq_door_codes instead of the old standalone
    door_types table (left in the schema, unused -- nothing references it by
    foreign key, so there's no integrity reason to drop it). Managed from
    Admin -> Door Codes, not its own tab.

    Only active codes contribute a family_name here (2026-10-22, when Door
    Codes' Delete button was replaced with the same deactivate/reactivate
    pattern as Reasons/Colours/Work Centres) -- a family_name backed only by
    deactivated codes drops out of the entry form's dropdown, same as a
    deactivated reason/colour/work centre would, while historical
    rework_events rows that already used it are untouched (plain text, no
    FK, same convention as everywhere else)."""
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT family_name FROM cpq_door_codes "
            "WHERE family_name IS NOT NULL AND family_name <> '' AND active ORDER BY family_name"
        )
        return [r["family_name"] for r in cur.fetchall()]


def list_work_centres(active_only: bool = True) -> list[str]:
    sql = "SELECT name FROM work_centres"
    if active_only:
        sql += " WHERE active"
    sql += " ORDER BY sort_order, name"
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute(sql)
        return [r["name"] for r in cur.fetchall()]


def list_colours(active_only: bool = True) -> list[str]:
    sql = "SELECT name FROM colours"
    if active_only:
        sql += " WHERE active"
    sql += " ORDER BY name"
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute(sql)
        return [r["name"] for r in cur.fetchall()]


def get_reason(reason: str) -> dict | None:
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT reason, code, source, fault_category FROM rework_reasons WHERE reason = %s", (reason,))
        return cur.fetchone()




def list_sheet_items() -> list[dict]:
    """Raw sheet-stock items Turret deals with -- `items.plan_code = 'SHT'`,
    a genuine ERP classification (confirmed live 2026-10-22, see queries.py's
    module docstring), not a hand-curated list. Every material slot on the
    Turret entry form (except "Other", which gets the same list anyway) is
    constrained to this. `std_cost` is included so the entry form can show a
    live scrap-cost estimate as the operator picks a material/qty -- the
    server-side recompute on save (services.turret.update_event) is still the
    only value ever stored, same never-trust-the-client rule as everywhere
    else (see services/costing.py)."""
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT part_number, description, std_cost FROM items WHERE plan_code = 'SHT' ORDER BY part_number")
        return cur.fetchall()


def get_item(part_number: str) -> dict | None:
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT * FROM items WHERE part_number = %s", (part_number.strip().upper(),))
        return cur.fetchone()


def search_items(query: str, limit: int = 15) -> list[dict]:
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT part_number, description, std_cost FROM items "
            "WHERE LOWER(part_number) LIKE LOWER(%s) OR LOWER(description) LIKE LOWER(%s) "
            "ORDER BY part_number LIMIT %s",
            (f"%{query}%", f"%{query}%", limit),
        )
        return cur.fetchall()


def get_colour_by_code(code: str | None) -> str | None:
    if not code:
        return None
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT name FROM colours WHERE code = %s LIMIT 1", (code.strip(),))
        row = cur.fetchone()
        return row["name"] if row else None


def get_door_type_for_cpq_code(cpq_code: str | None) -> str | None:
    """A deactivated code is treated the same as an unmapped one -- the SO
    lookup just leaves Door Type for the operator to set manually, never a
    hard error either way (see CLAUDE.md, "Sales Order lookup")."""
    if not cpq_code:
        return None
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT family_name FROM cpq_door_codes WHERE cpq_code = %s AND active", (cpq_code.strip().upper(),))
        row = cur.fetchone()
        return row["family_name"] if row else None


def get_door_pieces(cpq_code: str | None) -> dict | None:
    """{"Stile": n|None, "Rail": n|None} for a CPQ door code (None = not set
    yet, 0 = the door has none), or None if the code isn't mapped."""
    if not cpq_code:
        return None
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT stile_pieces, rail_pieces FROM cpq_door_codes WHERE cpq_code = %s", (cpq_code.strip().upper(),))
        row = cur.fetchone()
    return {"Stile": row["stile_pieces"], "Rail": row["rail_pieces"]} if row else None
