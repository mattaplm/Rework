"""Fake Sales Order for manually exercising the Doors/Turret entry forms --
create, reopen/edit, and Scrap write-off -- without risking mixing it up
with a real order number (requested 2026-10-22: "make a fake sales order...
don't use a real one"). Toggled on/off from Admin -> SQL Connection.

Only the SO/job linking is fake -- `so_number`/`job_number` are plain text,
no FK to anything ERP-side, and a real orders sync never touches or removes
them. Everything else it points at is real: the colour (`ARCTIC WHITE MATT
20S1358M`, code `AW` -- an existing row, not a fake one created for this;
"Test" is not a real colour, confirmed 2026-10-22), the door type (`Plasma`,
resolved via a real, already-mapped `cpq_door_codes` row, `PLS`), and the 4
material lines (real items already in the synced `items` table -- 2 Sheet
items for Turret's BOM-scoping, 2 real Plasma door parts with a `rule` set
for Doors' Replace Part costing).

A fake entry is never silently indistinguishable from a real one: the entry
forms, the log tables, and both Scrap write-off tabs all flag anything tied
to `SO_NUMBER` with the same pink "TEST" styling (`static/style.css`'s
`.conn-banner.test`/`.test-order-row`/`.test-badge`) -- see
`services.rework.scrap_writeoff_summary`'s and `services.turret.
scrap_summary_by_week`'s `includes_test_data` flag for how an aggregated
write-off row gets marked even though it only has one underlying so_number
column to check.

Turning it off deletes the fake order/materials *and* any rework_events/
turret_events logged against the fake SO while testing -- otherwise a
dangling fake SO number would keep showing up in the real log/Dashboard
after being switched off. This is a deliberate full reset, not a soft hide:
the whole point is a safe, repeatable sandbox, not a second permanent data
set to maintain. The colour is real and shared, so disabling never touches
`colours` at all.
"""

from __future__ import annotations

import datetime

import db

SO_NUMBER = "test"
JOB_NUMBER = "J009999999"
COLOUR_NAME = "ARCTIC WHITE MATT 20S1358M"  # real, existing colour -- "Test" isn't a colour
COLOUR_CODE = "AW"
CPQ_DOOR_CODE = "PLS"  # real code, family_name 'Plasma' -- confirmed live 2026-10-22

# (part_number, qty) -- part_number must already exist in `items` (real ERP
# data); only the order/job linking them together is fake.
MATERIALS = [
    ("5902412", 2),
    ("79020062", 2),
    ("00347.500.01", 4),
    ("00349.500.01", 2),
]


def is_enabled() -> bool:
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT 1 FROM synced_orders WHERE so_number = %s", (SO_NUMBER,))
        return cur.fetchone() is not None


def enable() -> None:
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO synced_orders (
                so_number, job_number, height, width, cpq_door_code,
                colour_in_code, colour_out_code, qty_ordered, due_date, stat
            ) VALUES (%s, %s, 2040, 860, %s, %s, %s, 1, %s, 'Open (test data)')
            ON CONFLICT (so_number) DO UPDATE SET
                job_number = EXCLUDED.job_number, cpq_door_code = EXCLUDED.cpq_door_code,
                colour_in_code = EXCLUDED.colour_in_code, colour_out_code = EXCLUDED.colour_out_code,
                due_date = EXCLUDED.due_date, synced_at = now()
            """,
            (
                SO_NUMBER, JOB_NUMBER, CPQ_DOOR_CODE, COLOUR_CODE, COLOUR_CODE,
                datetime.date.today() + datetime.timedelta(days=14),
            ),
        )
        cur.execute("DELETE FROM synced_order_materials WHERE job_number = %s", (JOB_NUMBER,))
        for part_number, qty in MATERIALS:
            cur.execute(
                """
                INSERT INTO synced_order_materials (job_number, part_number, description, qty, unit, unit_cost)
                SELECT %s, part_number, description, %s, 'EA', std_cost FROM items WHERE part_number = %s
                """,
                (JOB_NUMBER, qty, part_number),
            )


def disable() -> dict:
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM rework_events WHERE so_number = %s RETURNING id", (SO_NUMBER,))
        rework_deleted = len(cur.fetchall())
        cur.execute("DELETE FROM turret_events WHERE sales_number = %s RETURNING id", (SO_NUMBER,))
        turret_deleted = len(cur.fetchall())
        cur.execute("DELETE FROM synced_order_materials WHERE job_number = %s", (JOB_NUMBER,))
        cur.execute("DELETE FROM synced_orders WHERE so_number = %s", (SO_NUMBER,))
    return {"rework_events_deleted": rework_deleted, "turret_events_deleted": turret_deleted}
