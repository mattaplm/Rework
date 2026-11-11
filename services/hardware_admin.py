"""Writes behind Hardware Admin's Reasons and Parts tabs (services.hardware
stays the read side the entry form uses). The Powdercoat / Assembly people
lists reuse services.admin_data's named-table helpers (hw_powdercoaters /
hw_assemblers), same as Doors' Work Centres and People."""

from __future__ import annotations

import db


# ── Reasons ─────────────────────────────────────────────────────────────────

def create_reason(reason: str, is_scrap: bool) -> None:
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT COALESCE(MAX(sort_order), 0) + 1 AS n FROM hw_reasons")
        sort_order = cur.fetchone()["n"]
        cur.execute("INSERT INTO hw_reasons (reason, is_scrap, sort_order) VALUES (%s, %s, %s)",
                    (reason.strip(), is_scrap, sort_order))


def save_reason(reason_id: int, reason: str, is_scrap: bool, sort_order: int) -> int:
    """Edits a reason in place. A renamed reason cascades into every
    hw_events row that used the old wording (plain text, no FK -- same rule as
    Doors' reasons). Changing Scrap Y/N only affects entries saved from now
    on; past entries keep the scrap/rework split and costs they were logged
    with. Returns how many past entries the rename touched."""
    reason = reason.strip()
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT reason FROM hw_reasons WHERE id = %s", (reason_id,))
        existing = cur.fetchone()
        if existing is None:
            raise ValueError(f"Reason id {reason_id} not found")
        cur.execute("UPDATE hw_reasons SET reason = %s, is_scrap = %s, sort_order = %s WHERE id = %s",
                    (reason, is_scrap, sort_order, reason_id))
        if reason == existing["reason"]:
            return 0
        cur.execute("UPDATE hw_events SET reason = %s WHERE reason = %s", (reason, existing["reason"]))
        return cur.rowcount


def set_reason_active(reason_id: int, active: bool) -> None:
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute("UPDATE hw_reasons SET active = %s WHERE id = %s", (active, reason_id))


# ── Parts ───────────────────────────────────────────────────────────────────

def _cost(value) -> float | None:
    if value in (None, ""):
        return None
    number = float(value)
    if number < 0:
        raise ValueError("Costs can't be negative")
    return number


def save_part(old_part_number: str | None, part: dict) -> None:
    """Upserts one part. Editing the part number acts as a rename of the
    parts-list row only -- past entries keep the part number they were logged
    against (they also keep their own cost snapshot, so nothing about them
    depends on this row)."""
    part_number = str(part.get("part_number") or "").strip().upper()
    if not part_number:
        raise ValueError("Part number is required")
    values = {
        "part_number": part_number,
        "unit_cost": _cost(part.get("unit_cost")),
        "material_cost": _cost(part.get("material_cost")),
        "supplier": str(part.get("supplier") or "").strip() or None,
        "product_code": str(part.get("product_code") or "").strip().upper() or None,
        "material": str(part.get("material") or "").strip() or None,
    }
    with db.get_conn() as conn, conn.cursor() as cur:
        old = (old_part_number or "").strip().upper()
        if old and old != part_number:
            cur.execute("SELECT 1 FROM hw_parts WHERE part_number = %s", (part_number,))
            if cur.fetchone():
                raise ValueError(f"{part_number} is already in the parts list")
            cur.execute(
                "UPDATE hw_parts SET part_number = %(part_number)s, unit_cost = %(unit_cost)s, "
                "material_cost = %(material_cost)s, supplier = %(supplier)s, "
                "product_code = %(product_code)s, material = %(material)s WHERE part_number = %(old)s",
                {**values, "old": old},
            )
            return
        cur.execute(
            "INSERT INTO hw_parts (part_number, unit_cost, material_cost, supplier, product_code, material) "
            "VALUES (%(part_number)s, %(unit_cost)s, %(material_cost)s, %(supplier)s, %(product_code)s, %(material)s) "
            "ON CONFLICT (part_number) DO UPDATE SET unit_cost = EXCLUDED.unit_cost, "
            "material_cost = EXCLUDED.material_cost, supplier = EXCLUDED.supplier, "
            "product_code = EXCLUDED.product_code, material = EXCLUDED.material",
            values,
        )


def set_part_active(part_number: str, active: bool) -> None:
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute("UPDATE hw_parts SET active = %s WHERE part_number = %s", (active, part_number.strip().upper()))
