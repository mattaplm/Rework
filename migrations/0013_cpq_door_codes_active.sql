-- Door Codes tab dropped its Delete button in favour of the same
-- deactivate/reactivate pattern as Reasons/Colours/Work Centres (requested
-- 2026-10-22) -- nothing in this app hard-deletes reference data, since a
-- code might still be referenced by a real historical order lookup even
-- after it's no longer wanted going forward, and reversibility costs
-- nothing. Defaults every existing row to active so nothing currently
-- suggested on the SO-lookup auto-fill silently disappears.
ALTER TABLE cpq_door_codes ADD COLUMN IF NOT EXISTS active BOOLEAN NOT NULL DEFAULT TRUE;
