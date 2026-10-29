"""Writes behind the Admin page's Reasons/Door Codes/Work Centres/Items tabs.
`services.reference_data` stays read-only (it's what the entry form uses);
this module is the admin-only mutation side of the same tables.
"""

from __future__ import annotations

import db

# ── Reasons ─────────────────────────────────────────────────────────────────

def list_reasons_all() -> list[dict]:
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT * FROM rework_reasons ORDER BY sort_order, reason")
        return cur.fetchall()


def create_reason(reason: str, code: str | None, source: str, fault_category: str | None) -> None:
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO rework_reasons (reason, code, source, fault_category) VALUES (%s, %s, %s, %s)",
            (reason.strip(), (code or "").strip() or None, source.strip(), (fault_category or "").strip() or None),
        )


def set_reason_active(reason: str, active: bool) -> None:
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute("UPDATE rework_reasons SET active = %s WHERE reason = %s", (active, reason))


def save_reason(reason_id: int, reason: str, code: str | None, source: str, fault_category: str | None) -> int:
    """Edits an existing reason in place, identified by `id` (stable across
    a rename, unlike Work Centres' save_named below, which has to match by
    the old name since that table has no id exposed to the admin UI). If the
    reason *text* itself changed, cascades into every rework_events/
    turret_events row that referenced the old wording -- reason is plain
    text in both, no FK (same convention as Work Centres' name), so an
    uncascaded rename would otherwise leave historical rows pointing at
    wording that no longer appears anywhere in the dropdown. Returns how
    many historical rows were updated, so the caller can tell the admin what
    just changed."""
    reason = reason.strip()
    code = (code or "").strip() or None
    source = source.strip()
    fault_category = (fault_category or "").strip() or None
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT reason FROM rework_reasons WHERE id = %s", (reason_id,))
        existing = cur.fetchone()
        if existing is None:
            raise ValueError(f"Reason id {reason_id} not found")
        old_reason = existing["reason"]

        cur.execute(
            "UPDATE rework_reasons SET reason = %s, code = %s, source = %s, fault_category = %s WHERE id = %s",
            (reason, code, source, fault_category, reason_id),
        )
        updated = 0
        if reason != old_reason:
            cur.execute("UPDATE rework_events SET reason = %s WHERE reason = %s", (reason, old_reason))
            updated += cur.rowcount
            cur.execute("UPDATE turret_events SET reason = %s WHERE reason = %s", (reason, old_reason))
            updated += cur.rowcount
        return updated


# ── Work centres (door_types merged into cpq_door_codes.family_name below) ──

_NAMED_TABLES = {"work_centres"}


def _check_table(table: str) -> str:
    if table not in _NAMED_TABLES:
        raise ValueError(f"not a recognised reference table: {table!r}")
    return table


def list_named_all(table: str) -> list[dict]:
    table = _check_table(table)
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute(f"SELECT * FROM {table} ORDER BY sort_order, name")
        return cur.fetchall()


def create_named(table: str, name: str, sort_order: int | None = None) -> None:
    """`sort_order` defaults to one past the current highest, so a new row
    lands at the end of the list instead of tying at 0."""
    table = _check_table(table)
    with db.get_conn() as conn, conn.cursor() as cur:
        if sort_order is None:
            cur.execute(f"SELECT COALESCE(MAX(sort_order), 0) + 1 AS n FROM {table}")
            sort_order = cur.fetchone()["n"]
        cur.execute(f"INSERT INTO {table} (name, sort_order) VALUES (%s, %s)",
                    (name.strip(), sort_order))


def set_named_active(table: str, name: str, active: bool) -> None:
    table = _check_table(table)
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute(f"UPDATE {table} SET active = %s WHERE name = %s", (active, name))


_NAMED_EVENT_COLUMN = {"work_centres": "work_centre"}


def save_named(table: str, old_name: str, new_name: str, sort_order: int) -> int:
    """Edits an existing named-reference row in place -- one Edit button
    reveals both Name and Sort order together, one Save persists both (same
    single-row-edit pattern as Reasons' save_reason, 2026-10-22: replaces
    the old separate Rename-button/prompt() flow and the separate
    sort-order-only save). If the name itself changed, cascades into every
    rework_events row that referenced the old name -- door_type/work_centre
    are plain text there, not a foreign key (see CLAUDE.md), so an
    uncascaded rename would otherwise leave historical rows pointing at a
    name that no longer exists anywhere in the dropdown. Returns how many
    historical rows were updated, so the caller can tell the admin what
    just changed."""
    table = _check_table(table)
    new_name = new_name.strip()
    event_column = _NAMED_EVENT_COLUMN[table]
    with db.get_conn() as conn, conn.cursor() as cur:
        updated = 0
        if new_name != old_name:
            cur.execute(f"UPDATE {table} SET name = %s WHERE name = %s", (new_name, old_name))
            cur.execute(
                f"UPDATE rework_events SET {event_column} = %s WHERE {event_column} = %s",
                (new_name, old_name),
            )
            updated = cur.rowcount
        cur.execute(f"UPDATE {table} SET sort_order = %s WHERE name = %s", (sort_order, new_name))
        return updated


# ── Colours (ERP-owned; admin can only reactivate/deactivate locally) ───────

def list_colours_all() -> list[dict]:
    """All colours, unfiltered -- the Admin page renders every row and does
    search/sort/hide-no-swatch client-side (500 rows is nothing to filter in
    the browser), so there's no server-side limit or query param here."""
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT * FROM colours ORDER BY name")
        return cur.fetchall()


def set_colour_active(name: str, active: bool) -> None:
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute("UPDATE colours SET active = %s WHERE name = %s", (active, name))


# ── Items (ERP-owned except `rule`) ──────────────────────────────────────────

def search_items_all(query: str, limit: int = 50) -> list[dict]:
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM items WHERE LOWER(part_number) LIKE LOWER(%s) OR LOWER(description) LIKE LOWER(%s) "
            "ORDER BY part_number LIMIT %s",
            (f"%{query}%", f"%{query}%", limit),
        )
        return cur.fetchall()


def set_item_rule(part_number: str, rule: float) -> None:
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute("UPDATE items SET rule = %s WHERE part_number = %s", (rule, part_number.strip().upper()))


# ── CPQ door codes (SO-lookup autofill, see erp_lookup.py) --------------------
# This is also the single home for Door Types now (2026-10-20 merge): a code's
# `family_name` IS this app's Door Type list -- the entry form's Door Type
# dropdown is DISTINCT family_name across this table (reference_data.
# list_door_types), not a separate admin-maintained list. `description` is a
# second, optional free-text field for any extra detail beyond the family
# name. Neither is validated against anything -- plain text, admin-entered.

def list_cpq_door_codes() -> list[dict]:
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT * FROM cpq_door_codes ORDER BY family_name, cpq_code")
        return cur.fetchall()


def save_cpq_door_code(old_code: str | None, new_code: str, family_name: str, description: str) -> None:
    """Upserts (new_code, family_name, description). If `old_code` is given
    and differs from `new_code`, the old row is deleted first -- editing a
    row's code acts like renaming it, rather than leaving both the old and
    new code behind (cpq_code is the primary key, so it can't just be
    UPDATEd if that would collide with -- or needs to replace -- an existing
    row). Carries the old row's `active` state across a rename (read before
    the delete) so renaming a deactivated code doesn't silently reactivate
    it via the INSERT's column default."""
    new_code = new_code.strip().upper()
    family_name = family_name.strip()
    description = description.strip()
    with db.get_conn() as conn, conn.cursor() as cur:
        active = True
        if old_code and old_code.strip().upper() != new_code:
            old_code = old_code.strip().upper()
            cur.execute("SELECT active FROM cpq_door_codes WHERE cpq_code = %s", (old_code,))
            existing = cur.fetchone()
            if existing is not None:
                active = existing["active"]
            cur.execute("DELETE FROM cpq_door_codes WHERE cpq_code = %s", (old_code,))
        cur.execute(
            "INSERT INTO cpq_door_codes (cpq_code, family_name, description, active) VALUES (%s, %s, %s, %s) "
            "ON CONFLICT (cpq_code) DO UPDATE SET family_name = EXCLUDED.family_name, description = EXCLUDED.description",
            (new_code, family_name, description, active),
        )


def set_cpq_door_code_active(cpq_code: str, active: bool) -> None:
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute("UPDATE cpq_door_codes SET active = %s WHERE cpq_code = %s", (active, cpq_code.strip().upper()))



# ── Snapshot for the SQL/ERP Connection tab ─────────────────────────────────

def _fmt_synced_at(value) -> str | None:
    """`synced_at` columns are TIMESTAMPTZ; psycopg2 hands back an
    aware datetime whose default str() includes microseconds and a numeric
    UTC offset (e.g. "2026-10-21 08:18:15.378000+12:00") -- fine for a log,
    not for an admin glancing at a stat. Shown in the server's local time
    since that's what the scheduled-task times on this same page are in."""
    if value is None:
        return None
    return value.astimezone().strftime("%Y-%m-%d %H:%M")


def erp_sync_status() -> dict:
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS n, MAX(synced_at) AS last_synced FROM items WHERE synced_at IS NOT NULL")
        items = cur.fetchone()
        cur.execute("SELECT COUNT(*) AS n, MAX(synced_at) AS last_synced FROM colours WHERE synced_at IS NOT NULL")
        colours = cur.fetchone()
        cur.execute("SELECT COUNT(*) AS n FROM items")
        total_items = cur.fetchone()["n"]
        cur.execute("SELECT COUNT(*) AS n, MAX(synced_at) AS last_synced FROM synced_orders")
        orders = cur.fetchone()
        cur.execute("SELECT COUNT(DISTINCT job_number) AS n FROM synced_order_materials")
        order_jobs = cur.fetchone()["n"]
        cur.execute("SELECT COUNT(*) AS n, MAX(synced_at) AS last_synced FROM erp_scrap_transactions")
        scrap_txns = cur.fetchone()
    return {
        "items_synced": items["n"], "items_last_synced": _fmt_synced_at(items["last_synced"]), "items_total": total_items,
        "colours_synced": colours["n"], "colours_last_synced": _fmt_synced_at(colours["last_synced"]),
        "orders_synced": orders["n"], "orders_last_synced": _fmt_synced_at(orders["last_synced"]), "order_jobs_synced": order_jobs,
        "scrap_txns_synced": scrap_txns["n"], "scrap_txns_last_synced": _fmt_synced_at(scrap_txns["last_synced"]),
    }
