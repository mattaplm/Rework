"""Shared read helper for reconciling the Turret and Doors Scrap write-off
tabs (services/turret.py, services/rework.py) against the real SyteLine
scrap transactions synced by services/erp_sync.sync_scrap_transactions.
Both tabs group their own logged scrap by (item or product_code, write-off
week); this gives them the matching ERP-side total to show alongside it.
"""

from __future__ import annotations

import db

def sheet_item_codes() -> set[str]:
    """Raw sheet-stock item codes -- `items.plan_code = 'SHT'`, a genuine
    ERP classification synced from SyteLine (see queries.py's module
    docstring for how this was confirmed), not a hand-curated list. Sheet
    items are Turret's own raw material, already reconciled on that tab;
    excluded from the Doors write-off tab so the same item doesn't get
    double-counted across both tabs (confirmed 2026-10-21: Plank items like
    00392.215.01 stay IN the Doors view -- the department confirmed those
    belong there, unlike Sheet).

    Queried fresh each call rather than cached -- it's a local, indexed,
    small-table lookup (a handful of rows), and staying live means a sync
    that adds/changes a sheet item takes effect immediately everywhere this
    is used, with no separate cache to remember to invalidate.
    """
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT part_number FROM items WHERE plan_code = 'SHT'")
        return {r["part_number"] for r in cur.fetchall()}


def erp_actuals_by_item_week() -> dict[tuple[str, int, int], dict]:
    """{(item, isoyear, isoweek): {"qty": ..., "cost": ...}}, keyed by the
    ISO year/week the transaction actually happened in SyteLine (derived
    here the same way Turret/Doors derive their own write-off weeks, not
    SyteLine's own non-ISO WeekNum -- see queries.py's
    SCRAP_TRANSACTIONS_QUERY, which doesn't even fetch that column).

    `qty`/`cost` are returned as positive magnitudes: SyteLine records a
    scrap write-off as a negative stock movement (confirmed live: ~99% of
    real rows), while this app's own logged totals are positive "amount
    scrapped" counts -- summing signed and then taking abs() still lets a
    genuine correcting reversal (a wrong entry immediately offset by its
    exact negative) net out to zero first, which is correct.
    """
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                item,
                EXTRACT(ISOYEAR FROM txn_date)::int AS isoyear,
                EXTRACT(WEEK FROM txn_date)::int AS isoweek,
                SUM(qty) AS qty,
                SUM(scrap_cost) AS cost
            FROM erp_scrap_transactions
            GROUP BY item, isoyear, isoweek
            """
        )
        return {
            (r["item"], r["isoyear"], r["isoweek"]): {"qty": abs(r["qty"]), "cost": abs(r["cost"])}
            for r in cur.fetchall()
        }


def last_synced_at():
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT MAX(synced_at) AS t FROM erp_scrap_transactions")
        return cur.fetchone()["t"]
