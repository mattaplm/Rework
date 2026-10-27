-- Renamed for honesty: this column is free text an admin types in, not a
-- reference to door_types.name -- "door_type" implied a constraint/foreign
-- key relationship that was never real and got in the way (a code for a
-- door type that doesn't exist in door_types yet couldn't be described at
-- all under the old column name's implied meaning).
ALTER TABLE cpq_door_codes RENAME COLUMN door_type TO description;
