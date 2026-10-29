-- Qty to Remove from the job's own material qty instead of a per-item rule:
-- how many stile / rail pieces one door of this CPQ code has (NULL = not set
-- yet, 0 = the door has none), and which component an entry scrapped.
ALTER TABLE cpq_door_codes ADD COLUMN stile_pieces INTEGER;
ALTER TABLE cpq_door_codes ADD COLUMN rail_pieces INTEGER;
ALTER TABLE rework_events ADD COLUMN component TEXT;
