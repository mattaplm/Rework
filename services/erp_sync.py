"""Pulls items + colours out of SyteLine into Postgres.

`items.rule` (the units-per-part multiplier for Qty to Remove) is locally
owned and deliberately left out of the UPDATE SET below, so a re-sync never
overwrites it -- see CLAUDE.md, "Reference data vs. the ERP".

`sync_items` deletes any ERP-synced item the query no longer returns (e.g.
narrowing `ITEMS_QUERY`'s filter, see queries.py) -- safe because
`rework_events.product_code` is plain text, not a foreign key, so nothing
already logged breaks. `colours` instead deactivates rather than deletes
(same reasoning, different mechanism) only because `colours.active` already
exists for the admin UI's own local on/off toggle; `items` has no such column
to repurpose, and nothing reads a "did this item used to exist" state, so
there's no reason to keep the row around.

`sync_orders` is different again: unlike items/colours, it never deletes or
deactivates rows that drop out of the ERP query. `ORDERS_SYNC_QUERY` only
returns currently-open order lines (coitem_all), so a row *disappearing*
just means the order shipped -- exactly the kind of order a rework entry
might still need to reference (see services/erp_lookup.py). Each day's sync
only adds/refreshes; nothing already cached is ever removed by it.

`sync_scrap_transactions` is wholesale-replaced every sync (TRUNCATE +
reinsert, per erp_scrap_transactions's own migration-0001 comment) rather
than upserted -- this is a transaction feed, not reference data with a
stable key to upsert against, and the 2-year window it pulls is cheap
enough to just redo in full each time. See queries.py's
SCRAP_TRANSACTIONS_QUERY docstring for what reason_code = 'SCR' means and
why qty comes back signed (mostly negative).
"""

from __future__ import annotations

from datetime import date

import db
import erp
import queries


def sync_items() -> int:
    rows = erp.fetch_all(queries.ITEMS_QUERY)
    part_numbers = [r["part_number"] for r in rows]

    with db.get_conn() as conn, conn.cursor() as cur:
        for row in rows:
            cur.execute(
                """
                INSERT INTO items (part_number, description, product_code, product_group, std_cost, length_std, plan_code, synced_at)
                VALUES (%(part_number)s, %(description)s, %(product_code)s, %(product_group)s, %(std_cost)s, %(length_std)s, %(plan_code)s, now())
                ON CONFLICT (part_number) DO UPDATE SET
                    description   = EXCLUDED.description,
                    product_code  = EXCLUDED.product_code,
                    product_group = EXCLUDED.product_group,
                    std_cost      = EXCLUDED.std_cost,
                    length_std    = EXCLUDED.length_std,
                    plan_code     = EXCLUDED.plan_code,
                    synced_at     = EXCLUDED.synced_at
                """,
                row,
            )
        cur.execute(
            "DELETE FROM items WHERE synced_at IS NOT NULL AND NOT (part_number = ANY(%s))",
            (part_numbers,),
        )
    return len(rows)


def sync_colours() -> int:
    rows = erp.fetch_all(queries.COLOURS_QUERY)
    rows = [r for r in rows if r.get("ColourDescription")]
    names = [r["ColourDescription"].strip() for r in rows]

    with db.get_conn() as conn, conn.cursor() as cur:
        for r in rows:
            cur.execute(
                """
                INSERT INTO colours (name, code, dulux_code, rgb, base_colour_code, base_colour_description, active, synced_at)
                VALUES (%(name)s, %(code)s, %(dulux_code)s, %(rgb)s, %(base_colour_code)s, %(base_colour_description)s, TRUE, now())
                ON CONFLICT (name) DO UPDATE SET
                    code = EXCLUDED.code, dulux_code = EXCLUDED.dulux_code, rgb = EXCLUDED.rgb,
                    base_colour_code = EXCLUDED.base_colour_code, base_colour_description = EXCLUDED.base_colour_description,
                    active = TRUE, synced_at = now()
                """,
                {
                    "name": r["ColourDescription"].strip(),
                    "code": r.get("Colour"),
                    "dulux_code": r.get("DuluxCode"),
                    "rgb": r.get("RGB"),
                    "base_colour_code": r.get("BaseColour"),
                    "base_colour_description": r.get("BaseColourDescription"),
                },
            )
        cur.execute(
            "UPDATE colours SET active = FALSE "
            "WHERE synced_at IS NOT NULL AND NOT (name = ANY(%s))",
            (names,),
        )
    return len(names)


def sync_orders() -> dict:
    """Pulls every open order line (+ each referenced job's materials) out of
    SyteLine into the local synced_orders/synced_order_materials cache --
    see erp_lookup.py, which reads from these tables instead of querying
    SyteLine live on every entry-form SO lookup.
    """
    rows = erp.fetch_all(queries.ORDERS_SYNC_QUERY)
    job_numbers = sorted({r["job_number"] for r in rows if r.get("job_number")})

    materials = erp.fetch_all(queries.job_materials_for_jobs_query(job_numbers)) if job_numbers else []

    with db.get_conn() as conn, conn.cursor() as cur:
        for row in rows:
            cur.execute(
                """
                INSERT INTO synced_orders
                    (so_number, job_number, height, width, cpq_door_code,
                     colour_in_code, colour_out_code, qty_ordered, due_date, stat, synced_at)
                VALUES
                    (%(so_number)s, %(job_number)s, %(height)s, %(width)s, %(cpq_door_code)s,
                     %(colour_in_code)s, %(colour_out_code)s, %(qty_ordered)s, %(due_date)s, %(stat)s, now())
                ON CONFLICT (so_number) DO UPDATE SET
                    job_number = EXCLUDED.job_number, height = EXCLUDED.height, width = EXCLUDED.width,
                    cpq_door_code = EXCLUDED.cpq_door_code, colour_in_code = EXCLUDED.colour_in_code,
                    colour_out_code = EXCLUDED.colour_out_code, qty_ordered = EXCLUDED.qty_ordered,
                    due_date = EXCLUDED.due_date, stat = EXCLUDED.stat, synced_at = now()
                """,
                row,
            )
        for m in materials:
            cur.execute(
                """
                INSERT INTO synced_order_materials (job_number, part_number, description, qty, unit, unit_cost, synced_at)
                VALUES (%(job_number)s, %(part_number)s, %(description)s, %(qty)s, %(unit)s, %(unit_cost)s, now())
                ON CONFLICT (job_number, part_number) DO UPDATE SET
                    description = EXCLUDED.description, qty = EXCLUDED.qty, unit = EXCLUDED.unit,
                    unit_cost = EXCLUDED.unit_cost, synced_at = now()
                """,
                m,
            )
    return {"orders": len(rows), "jobs": len(job_numbers), "materials": len(materials)}


def sync_scrap_transactions() -> int:
    """Pulls Doors scrap write-off transactions (reason_code='SCR') from the
    last 2 calendar years into erp_scrap_transactions -- the "ERP actual"
    side of the Turret and Doors Scrap write-off tabs (services/turret.py,
    services/rework.py)."""
    rows = erp.fetch_all(queries.SCRAP_TRANSACTIONS_QUERY, (date.today().year - 1,))

    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute("TRUNCATE erp_scrap_transactions")
        for row in rows:
            cur.execute(
                """
                INSERT INTO erp_scrap_transactions
                    (txn_date, item, description, qty, scrap_cost, scrap_labour_cost,
                     product_group, product_code, type, user_code, synced_at)
                VALUES
                    (%(txn_date)s, %(item)s, %(description)s, %(qty)s, %(scrap_cost)s, %(scrap_labour_cost)s,
                     %(product_group)s, %(product_code)s, %(type)s, %(user_code)s, now())
                """,
                row,
            )
    return len(rows)
