-- Variation dropdown options for the turret entry form, as supplied by the
-- department 2026-11-04 (the list from their own spreadsheet). Admin ->
-- Turret Variations can still add/rename/deactivate after this.
INSERT INTO turret_variations (name, sort_order) VALUES
    ('More than one door', 1),
    ('More sheets used', 2),
    ('Less sheets used', 3),
    ('Stock', 4),
    ('Backflush turned on', 5),
    ('No paperwork', 6),
    ('Sheet scrapped', 7),
    ('Offcut', 8),
    ('Shared sheet', 9),
    ('Sheet swapped', 10)
ON CONFLICT (name) DO NOTHING;
