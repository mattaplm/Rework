-- Door Types and Door Codes are being merged into one tab/concept: the
-- entry form's Door Type dropdown now comes from DISTINCT family_name here
-- instead of the separate door_types table (that table is left in place,
-- unused, rather than dropped -- nothing references it by foreign key, so
-- there's no integrity reason to remove it, only tidiness, and reversibility
-- costs nothing).
ALTER TABLE cpq_door_codes ADD COLUMN IF NOT EXISTS family_name TEXT;

-- Bootstrap family_name from the existing description column -- for every
-- code mapped so far, description already held the door type name (e.g.
-- 'AX' -> 'Axis'), so it's a correct starting value, not a guess.
UPDATE cpq_door_codes SET family_name = description WHERE family_name IS NULL;
