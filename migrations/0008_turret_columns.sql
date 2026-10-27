-- Fills out turret_events to match the real tracker's columns (confirmed
-- against 'Turret Sheet Audit 2026.xlsx' 2026-10-21): a week number, an
-- open/outstanding-side status, and the full per-sheet-slot scrap sub-log
-- (up to 3 independent scrap events per job row, one per sheet slot) --
-- migration 0001 only had a single scrap_code/scrap_cost pair, not enough
-- to represent a row with scrap recorded against more than one sheet slot.
-- source_row_hash follows the exact same dedup convention as
-- rework_events.source_row_hash (migration 0002) -- safe to re-run the
-- importer against a newer export of the same workbook.

ALTER TABLE turret_events
    ADD COLUMN IF NOT EXISTS week_num        INTEGER,
    ADD COLUMN IF NOT EXISTS open_status     TEXT,
    ADD COLUMN IF NOT EXISTS scrap_date_a    DATE,
    ADD COLUMN IF NOT EXISTS scrap_sheet_a   TEXT,
    ADD COLUMN IF NOT EXISTS scrap_qty_a     NUMERIC(10,2),
    ADD COLUMN IF NOT EXISTS scrap_date_b    DATE,
    ADD COLUMN IF NOT EXISTS scrap_sheet_b   TEXT,
    ADD COLUMN IF NOT EXISTS scrap_qty_b     NUMERIC(10,2),
    ADD COLUMN IF NOT EXISTS scrap_date_c    DATE,
    ADD COLUMN IF NOT EXISTS scrap_sheet_c   TEXT,
    ADD COLUMN IF NOT EXISTS scrap_qty_c     NUMERIC(10,2),
    ADD COLUMN IF NOT EXISTS scrap_comments  TEXT,
    ADD COLUMN IF NOT EXISTS scrap_week      INTEGER,
    ADD COLUMN IF NOT EXISTS scrap_year      INTEGER,
    ADD COLUMN IF NOT EXISTS source_row_hash TEXT UNIQUE;

CREATE INDEX IF NOT EXISTS idx_turret_events_event_date  ON turret_events (event_date);
CREATE INDEX IF NOT EXISTS idx_turret_events_job_number  ON turret_events (job_number);
