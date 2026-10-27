"""SQL Server (SyteLine ERP) query text -- kept separate from db.py / erp.py,
same convention as Scheduler's queries.py.

Column names confirmed live against `alpac_App` on 2026-10-19 (not guessed):
`item_mst.unit_cost` matches the old spreadsheet's "Std Cost" column exactly
(checked against part 02101.360.01: both 86.50000).

`item_mst.stat` is Active / Slow-moving / Obsolete (confirmed 2026-10-20,
values 'A'/'S'/'O' -- initially guessed from the row-count coincidence with
the old SL-Items sheet, since confirmed correct). Filtering `stat = 'A'`
means slow-moving parts aren't synced; a slow-moving part someone needs to
log a rework entry against won't show up in the Product Code search until
this filter is revisited (a wider filter was flagged as coming separately).

Also filtered to `uf_emdaProductGroup = 'DO'` (Doors) as of 2026-10-20,
checked against the real imported rework log first: of the 82 distinct
product codes actually used across all 11,961 historical entries, 74 matched
an item at all, and every one of those 74 is in group 'DO' -- the other 8
(e.g. the literal "DOOR" placeholder, raw sheet-stock numbers) don't match
any item regardless of group. Without this filter the sync pulls 5,223
items across the whole plant (HW/FP/GC/DO/CS/... groups); with it, 537 --
zero measured loss of real coverage for this app's actual usage.

`ITEMS_QUERY`'s `uf_emdaLength` is a real per-item length field (confirmed
present), answering the "does SyteLine hold lengths" question from planning --
but it's the item's own physical length, not the same concept as the old
Material masters sheet's family-grouped "Lengths std/oversize" (that maps to
a separate length-charting subsystem: `emdaLengthCharts`/`emdaLengths`/
`emdaLengthChartKey` -- not yet wired up, needs its own investigation).

`plan_code` (added 2026-10-22) is a genuine, clean ERP classification for
raw sheet stock -- `plan_code = 'SHT'` -- confirmed live against every known
sheet item (`79020062`/`5903015`/`5902412`/`5902412.0.9`/`5903615`, plus 4
more: `24123`/`36121.5`/`3902210.0.9`/`5902410`) with zero false positives
tested (a finished door-frame part with "SHEET" in its own description
("00346.500.01") has `plan_code = 'EXT'`; ANO/pretreat surcharge line items
and poly sheet all have `plan_code = NULL`). Replaces the hand-curated set
`services.erp_reconciliation.sheet_item_codes()` started with -- see that
function's docstring. **Known gap**: `3902210.1.2` (a real sheet variant,
confirmed needed on a real job) doesn't have `plan_code` set in SyteLine at
all -- an ERP data gap on that specific item, not something to work around
locally by guessing from its description.
"""

ITEMS_QUERY = """
SELECT
    item                  AS part_number,
    description           AS description,
    product_code          AS product_code,
    uf_emdaProductGroup   AS product_group,
    unit_cost             AS std_cost,
    uf_emdaLength         AS length_std,
    plan_code             AS plan_code
FROM alpac_App.dbo.item_mst WITH (NOLOCK)
WHERE stat = 'A' AND uf_emdaProductGroup = 'DO'
"""

# Verified live against alpac_App on 2026-10-20: 500 active colours, one row
# per colour code. `Colour` (the code, e.g. T24, AP) is the real ERP key --
# sales-order lines reference it directly (uf_emdaColourInside/Outside and
# the backing/sheet-detail colour fields) -- not ColourDescription, which is
# just the display name. The self-join resolves the base colour's own name
# (used by woodgrain/metallic finishes, e.g. WDR = Woodgrain Dark Red) so no
# extra lookup is needed for that column. RGB is "R,G,B" text (363 of 500
# colours have it); parse to hex for a swatch.
COLOURS_QUERY = """
SELECT
    c.Colour,
    c.ColourDescription,
    c.DuluxCode,
    c.RGB,
    c.BaseColour,
    b.ColourDescription AS BaseColourDescription,
    c.Door
FROM alpac_App.dbo.emdaColour AS c WITH (NOLOCK)
LEFT JOIN alpac_App.dbo.emdaColour AS b WITH (NOLOCK)
    ON b.Colour = c.BaseColour AND b.Obsolete = 0
WHERE c.Obsolete = 0
ORDER BY c.ColourDescription
"""

# Every distinct CPQ door code seen on a real order -- cross-referenced in
# Python against cpq_door_codes to show an admin exactly which codes still
# need a Door Type mapping (Admin -> Door Codes), instead of them having to
# already know what's out there.
DISTINCT_CPQ_DOOR_CODES_QUERY = """
SELECT DISTINCT Uf_aplCPQDoorProdCode AS cpq_code
FROM alpac_App.dbo.coitem_all WITH (NOLOCK)
WHERE Uf_aplCPQDoorProdCode IS NOT NULL AND Uf_aplCPQDoorProdCode <> ''
"""

# services/erp_sync.py's daily sync (services/erp_lookup.py reads the local
# synced_orders table this writes into, never SyteLine live -- see that
# module's docstring). Deliberately NEVER touches `coitem_mst_all` (shipped/
# completed lines) -- only `coitem_all`, which SyteLine itself only ever
# keeps non-shipped lines in, confirmed via Scheduler's own queries. Adding
# coverage for shipped orders would mean a second query against
# `coitem_mst_all`, not yet done (see services/erp_sync.py's module
# docstring for exactly what's confirmed vs. not on that table).
#
# First shipped with NO filter at all (reasoning: `coitem_all` only holds
# lines that haven't shipped yet, so there's no date window needed). Wrong in
# practice -- confirmed live 2026-10-21: an unfiltered sync ran for over 10
# minutes against the real ERP and never returned, almost certainly because
# `coitem_all` with no scope at all means every open order line *company-
# wide*, not just Doors (the exact same mistake `ITEMS_QUERY` made first,
# see its own comment above -- 5,223 plant-wide items vs. 537 once scoped to
# Doors). Fixed the same way, plus a date window the department asked for on
# top of it:
#   - `item_mst` join + `uf_emdaProductGroup = 'DO'`, same confirmed filter
#     as ITEMS_QUERY, via the order line's own `item` (part number) column.
#   - `due_date >= 30 days ago` (or NULL) -- ongoing rework is logged against
#     recent orders, not multi-year-old ones; a 30-day rolling window keeps
#     every sync fast regardless of how `coitem_all` grows. Orders already
#     cached from a previous sync are never deleted when they age out of this
#     window (see services/erp_sync.sync_orders's docstring) -- only today's
#     newly-in-window rows get refreshed.
ORDERS_SYNC_QUERY = """
SELECT
    co.co_num                  AS so_number,
    co.ref_num                 AS job_number,
    co.uf_emdaHeight           AS height,
    co.uf_emdaWidth            AS width,
    co.Uf_aplCPQDoorProdCode   AS cpq_door_code,
    co.uf_emdaColourInside     AS colour_in_code,
    co.uf_emdaColourOutside    AS colour_out_code,
    co.qty_ordered             AS qty_ordered,
    co.due_date                AS due_date,
    co.stat                    AS stat
FROM alpac_App.dbo.coitem_all AS co WITH (NOLOCK)
INNER JOIN alpac_App.dbo.item_mst AS im WITH (NOLOCK) ON im.item = co.item
WHERE im.uf_emdaProductGroup = 'DO'
  AND (co.due_date IS NULL OR co.due_date >= DATEADD(DAY, -30, CAST(GETDATE() AS DATE)))
"""


def job_materials_for_jobs_query(job_numbers: list[str]) -> str:
    """Every job's real material lines, for the entry form's Product Code
    list once a Sales Order resolves to a job -- confirmed live 2026-10-20
    (job J001110683, 29 lines across suffix 0 and 1). `jobmatl_mst.cost` is a
    PER-UNIT figure (confirmed equal to item_mst.unit_cost on every sampled
    row), not the line's extended total -- `matl_qty * cost` is the real
    line cost, and summing that across the job (not summing `cost` alone,
    which would just add unit prices together) is the real total material
    cost of the whole door: $464.53 extended vs. a meaningless $309.67 from
    naively summing `cost` directly, on that same sample job (see
    services/erp_lookup.py, which does this sum once materials are cached).

    Pulls every job in one bulk sync pass instead of one job per live
    lookup. Scoped to just the job numbers the orders sync actually found
    (not all of jobmatl_mst, which covers every job in the plant, not only
    Doors) -- same dynamic-IN-clause convention Scheduler already uses for
    its own bulk material queries. job_numbers come from our own
    just-fetched ORDERS_SYNC_QUERY result, not user input, so building the
    IN-list as literals (rather than ? params, which SQL Server caps at
    2100) is safe here.
    """
    escaped = ",".join("'" + j.replace("'", "''") + "'" for j in job_numbers)
    return f"""
SELECT
    jm.job                AS job_number,
    jm.item               AS part_number,
    jm.description        AS description,
    jm.matl_qty           AS qty,
    jm.u_m                AS unit,
    jm.cost               AS unit_cost
FROM alpac_App.dbo.jobmatl_mst AS jm WITH (NOLOCK)
WHERE jm.job IN ({escaped})
"""

# Doors scrap write-off reconciliation (services/erp_sync.sync_scrap_transactions,
# erp_scrap_transactions table) -- confirmed live 2026-10-21 against the
# department's own Power Query source for the workbook's write-off pivots:
# 1,211 rows for 2025-2026, Doors only.
#
# `matltran_mst` is the job *material transaction* history -- `reason_code =
# 'SCR'` is specifically what marks a scrap write-off among the 44 distinct
# reason codes seen on this table (confirmed: 7,483 'SCR' rows plant-wide).
# **`qty` is signed, and a scrap write-off is overwhelmingly negative**
# (confirmed: 1,193 of 1,211 real rows) -- SyteLine records it as stock
# *leaving* inventory, not a positive "amount scrapped" count the way this
# app's own qty_to_remove/scrap_qty fields are. Summing signed qty as-is
# also makes a correcting reversal (a wrong entry immediately offset by its
# exact negative) net out to zero automatically, which is correct behaviour,
# not a bug to filter out.
#
# `it.product_code` is item_mst's own FAMILY/category code (e.g. "PLD",
# "CSD", "DR") -- confirmed NOT the same thing as this app's product_code
# column (which stores the actual item/part number everywhere else, e.g.
# rework_events.product_code, turret_events.sheet_a). Reconciliation must
# join/match on `item` (`mt.item`/`it.item`), never on this field -- kept
# only for reference, same shape as the department's own export.
#
# The `Type` classification (Sheet/Plank/NULL) is the department's own
# curated split -- confirmed live: Sheet = the raw sheet-stock codes already
# known from the Turret tracker (79020062/5903015/5902412/3902210/5903615),
# Plank = 2 codes not otherwise seen in this app yet (00392.260.01/
# 00392.215.01), NULL = everything else (finished door parts, matching
# rework_events.product_code). One real row also has the literal item "Door"
# ("Configurable Door", product_code "DR") -- confirmed this is how a whole
# scrapped door shows up here, the ERP-side equivalent of this app's "Scrap
# Entire Door" (product_code "DOOR") -- note the item text itself differs
# ("Door" vs this app's "DOOR"), so matching that specific case needs a
# case-insensitive compare, not an exact string match.
#
# This `Sheet`/`Plank` CASE WHEN is left exactly as the department's own
# query (not switched to the `plan_code`-based classification ITEMS_QUERY
# now uses) -- it's a department-authored report, kept verbatim for
# traceability, and only feeds a reference-only column
# (erp_scrap_transactions.type) rather than any actual matching/filtering
# logic. services.erp_reconciliation.sheet_item_codes() is the one that
# actually drives the Doors/Turret exclusion split, and it's now broader
# than this literal list (plan_code = 'SHT' matches more than these 5
# codes) -- the two are allowed to diverge.
SCRAP_TRANSACTIONS_QUERY = """
SELECT
    mt.CreateDate           AS txn_date,
    mt.item                 AS item,
    it.description          AS description,
    mt.qty                  AS qty,
    ROUND(mt.matl_cost * mt.qty, 2) AS scrap_cost,
    ROUND(mt.lbr_cost * mt.qty, 2)  AS scrap_labour_cost,
    it.uf_emdaProductGroup  AS product_group,
    it.product_code         AS product_code,
    CASE
        WHEN mt.item IN ('79020062', '5903015', '5902412', '5902412.0.9', '3902210', '5903615') THEN 'Sheet'
        WHEN mt.item IN ('00392.260.01', '00392.215.01') THEN 'Plank'
        ELSE NULL
    END AS type,
    mt.user_code            AS user_code
FROM alpac_App.dbo.matltran_mst AS mt WITH (NOLOCK)
LEFT JOIN alpac_App.dbo.item_mst AS it WITH (NOLOCK) ON it.item = mt.item
WHERE mt.reason_code = 'SCR'
  AND YEAR(mt.CreateDate) >= ?
  AND it.uf_emdaProductGroup = 'DO'
"""
