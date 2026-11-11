-- Hardware's open order lines from SyteLine (2026-11-11) -- one row per SO
-- line, since each Hardware line is its own job (see queries.py's
-- HW_ORDER_LINES_QUERY). Refreshed by erp_sync.sync_orders alongside Doors'
-- synced_orders; like that cache, rows are never deleted when they age out.
-- Each job's materials go into the shared synced_order_materials table.
CREATE TABLE hw_synced_order_lines (
    so_number       TEXT NOT NULL,
    co_line         INTEGER NOT NULL,
    job_number      TEXT,
    item            TEXT,
    description     TEXT,
    colour_in_code  TEXT,
    colour_out_code TEXT,
    qty_ordered     NUMERIC(12,2),
    due_date        DATE,
    stat            TEXT,
    synced_at       TIMESTAMPTZ NOT NULL DEFAULT (now()),
    PRIMARY KEY (so_number, co_line)
);
CREATE INDEX idx_hw_synced_order_lines_job ON hw_synced_order_lines (job_number);
