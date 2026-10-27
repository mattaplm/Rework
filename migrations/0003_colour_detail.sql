-- The real ERP key for a colour is its short code (e.g. T24, AP) -- sales-
-- order lines reference it directly. `colours.name` (the human-readable
-- ColourDescription) stays the primary key this app's UI is built around,
-- but the real code plus swatch/base-colour detail are now captured too.
ALTER TABLE colours ADD COLUMN IF NOT EXISTS code TEXT;
ALTER TABLE colours ADD COLUMN IF NOT EXISTS dulux_code TEXT;
ALTER TABLE colours ADD COLUMN IF NOT EXISTS rgb TEXT;
ALTER TABLE colours ADD COLUMN IF NOT EXISTS base_colour_code TEXT;
ALTER TABLE colours ADD COLUMN IF NOT EXISTS base_colour_description TEXT;

CREATE INDEX IF NOT EXISTS idx_colours_code ON colours (code);
