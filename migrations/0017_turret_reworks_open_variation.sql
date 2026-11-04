-- Turret entry form, 2026-11-04:
--
-- 1. More than one rework per job. Each rework has its own type, reason and up
--    to 3 scrapped materials (each with its own stamped scrap_date), so they
--    live in a child table instead of turret_events' single set of
--    rework_type/reason/scrap_* columns. Historical imported rows
--    (source_row_hash IS NOT NULL) keep their scrap in the parent columns
--    untouched; web-form rows that already had rework recorded are moved into
--    the child table below so the form has one place to read/write them.
--    turret_events.scrap_cost stays the row's total (sum of its reworks).
--
-- 2. Admin-maintained picklists for the Open and Variation columns
--    (turret_events.open_status / variation already exist from the import).

CREATE TABLE turret_reworks (
    id              SERIAL PRIMARY KEY,
    turret_event_id INTEGER NOT NULL REFERENCES turret_events(id) ON DELETE CASCADE,
    position        INTEGER NOT NULL DEFAULT 0,
    rework_type     TEXT,
    reason          TEXT,
    scrap_sheet_a   TEXT, scrap_qty_a NUMERIC(10,2), scrap_date_a DATE,
    scrap_sheet_b   TEXT, scrap_qty_b NUMERIC(10,2), scrap_date_b DATE,
    scrap_sheet_c   TEXT, scrap_qty_c NUMERIC(10,2), scrap_date_c DATE,
    scrap_cost      NUMERIC(12,2),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_turret_reworks_event ON turret_reworks (turret_event_id);

INSERT INTO turret_reworks (
    turret_event_id, position, rework_type, reason,
    scrap_sheet_a, scrap_qty_a, scrap_date_a,
    scrap_sheet_b, scrap_qty_b, scrap_date_b,
    scrap_sheet_c, scrap_qty_c, scrap_date_c, scrap_cost
)
SELECT id, 0, rework_type, reason,
       scrap_sheet_a, scrap_qty_a, scrap_date_a,
       scrap_sheet_b, scrap_qty_b, scrap_date_b,
       scrap_sheet_c, scrap_qty_c, scrap_date_c, scrap_cost
FROM turret_events
WHERE source_row_hash IS NULL
  AND (rework_type IS NOT NULL OR reason IS NOT NULL
       OR scrap_sheet_a IS NOT NULL OR scrap_sheet_b IS NOT NULL OR scrap_sheet_c IS NOT NULL
       OR scrap_qty_a IS NOT NULL OR scrap_qty_b IS NOT NULL OR scrap_qty_c IS NOT NULL);

UPDATE turret_events SET
    rework_type = NULL, reason = NULL,
    scrap_sheet_a = NULL, scrap_qty_a = NULL, scrap_date_a = NULL,
    scrap_sheet_b = NULL, scrap_qty_b = NULL, scrap_date_b = NULL,
    scrap_sheet_c = NULL, scrap_qty_c = NULL, scrap_date_c = NULL
WHERE source_row_hash IS NULL
  AND id IN (SELECT turret_event_id FROM turret_reworks);

CREATE TABLE turret_open_options (
    id         SERIAL PRIMARY KEY,
    name       TEXT UNIQUE NOT NULL,
    active     BOOLEAN NOT NULL DEFAULT TRUE,
    sort_order INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE turret_variations (
    id         SERIAL PRIMARY KEY,
    name       TEXT UNIQUE NOT NULL,
    active     BOOLEAN NOT NULL DEFAULT TRUE,
    sort_order INTEGER NOT NULL DEFAULT 0
);

-- The four values the historical sheets actually use; Variation is left for
-- the department to fill in (the imported free text is too inconsistent to seed from).
INSERT INTO turret_open_options (name, sort_order) VALUES
    ('LH IN', 1), ('RH IN', 2), ('LH OUT', 3), ('RH OUT', 4);
