-- People who fill out the rework form on the factory floor (the entry form's
-- "Person" field). Distinct from `users`, who log entries into the app.
-- Case-insensitively unique so "gary" / "Gary" can't both exist.
CREATE TABLE people (
    id         SERIAL PRIMARY KEY,
    name       TEXT UNIQUE NOT NULL,
    active     BOOLEAN NOT NULL DEFAULT TRUE,
    sort_order INTEGER NOT NULL DEFAULT 0
);
CREATE UNIQUE INDEX idx_people_name_lower ON people (LOWER(name));

-- Start from who's actually been filling forms recently (one spelling per name);
-- older names stay on the historical rows but don't clutter the dropdown.
INSERT INTO people (name)
SELECT MIN(TRIM(entered_by_name)) FROM rework_events
WHERE entered_by_name IS NOT NULL AND TRIM(entered_by_name) <> '' AND entered_date >= '2026-07-01'
GROUP BY LOWER(TRIM(entered_by_name));
