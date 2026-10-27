-- Supports the new Turret web entry form (2026-10-21): create a job's
-- material usage, then reopen the same row later to add rework/scrap.
--
-- `type` is renamed to `door_type` -- it already held door-family values
-- for every imported row ("Plasma", "Classic", "Blank Panel", ...), i.e.
-- it already meant Door type, not a replace-vs-rework-whole-door
-- distinction. That distinction is new: `rework_type` ('Replacement Parts'
-- / 'Rework Entire Door'), which didn't exist in the imported sheet at all
-- (the sheet only ever carried a `scrap_code` reason, no type split).
--
-- `colour` is new -- the imported sheet never carried it.
--
-- `reason` is new and free text (same non-FK convention as
-- rework_events.reason) -- distinct from `scrap_code`, which stays as-is
-- for imported rows in their original "CODE - DESCRIPTION" format; new
-- web-form rows populate `reason` from turret_reasons.reason instead.
--
-- `updated_at` tracks the reopen-for-editing flow -- `created_at` already
-- exists and stays as "when this row was first created".

ALTER TABLE turret_events RENAME COLUMN type TO door_type;

ALTER TABLE turret_events
    ADD COLUMN IF NOT EXISTS colour      TEXT,
    ADD COLUMN IF NOT EXISTS rework_type TEXT,
    ADD COLUMN IF NOT EXISTS reason      TEXT,
    ADD COLUMN IF NOT EXISTS updated_at  TIMESTAMPTZ;

-- Turret's own reasons list -- deliberately separate from rework_reasons
-- (Doors' list): different department-facing picklist, no shared meaning
-- between e.g. Doors' "WRONG COLOUR" and whatever Turret wants under the
-- same label.
CREATE TABLE IF NOT EXISTS turret_reasons (
    id         SERIAL PRIMARY KEY,
    reason     TEXT NOT NULL UNIQUE,
    code       TEXT,
    sort_order INTEGER NOT NULL DEFAULT 0,
    active     BOOLEAN NOT NULL DEFAULT TRUE
);
