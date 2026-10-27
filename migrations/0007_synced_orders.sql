-- Local cache of SyteLine sales orders + their job materials, refreshed by a
-- scheduled sync (services.erp_sync.sync_orders) instead of the entry form's
-- SO lookup hitting SyteLine live on every single use -- that was the whole
-- problem: every lookup was a live ERP round trip, so it was only as fast
-- and only as available as SyteLine itself, confirmed down more than once
-- during real use. Same architecture Scheduler already uses for open_orders
-- (its own local cache, refreshed on a schedule, never queried live per page
-- view -- see its CLAUDE.md's "Database" section).

CREATE TABLE IF NOT EXISTS synced_orders (
    so_number       TEXT PRIMARY KEY,
    job_number      TEXT,
    height          NUMERIC(10,1),
    width           NUMERIC(10,1),
    cpq_door_code   TEXT,
    colour_in_code  TEXT,
    colour_out_code TEXT,
    qty_ordered     NUMERIC(10,2),
    due_date        DATE,
    stat            TEXT,
    synced_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_synced_orders_job_number ON synced_orders (job_number);

CREATE TABLE IF NOT EXISTS synced_order_materials (
    job_number   TEXT NOT NULL,
    part_number  TEXT NOT NULL,
    description  TEXT,
    qty          NUMERIC(12,4),
    unit         TEXT,
    unit_cost    NUMERIC(12,5),
    synced_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (job_number, part_number)
);
