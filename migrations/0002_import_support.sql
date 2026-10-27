-- Supports both the one-off historical backfill and the ongoing "Import from
-- Excel" admin page -- same importer, run as many times as needed.

-- A deterministic hash of each imported row's raw values. NULL for rows
-- created through the web form (a NULL never collides with another NULL in
-- a unique index, so this doesn't constrain normal entries at all) --
-- re-uploading the same spreadsheet is then just ON CONFLICT (source_row_hash)
-- DO NOTHING: already-imported rows are silently skipped, never duplicated.
ALTER TABLE rework_events ADD COLUMN IF NOT EXISTS source_row_hash TEXT UNIQUE;

-- The old spreadsheet's NAME column (who logged it) is free text with no
-- real user account behind it. New entries via the web form attribute to
-- entered_by_user_id instead; this is only populated for imported rows.
ALTER TABLE rework_events ADD COLUMN IF NOT EXISTS entered_by_name TEXT;
