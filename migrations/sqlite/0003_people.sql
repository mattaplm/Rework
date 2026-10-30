-- People who fill out the rework form on the factory floor (see migrations/0016_people.sql).
CREATE TABLE people (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT UNIQUE NOT NULL,
    active     BOOLEAN NOT NULL DEFAULT TRUE,
    sort_order INTEGER NOT NULL DEFAULT 0
);
CREATE UNIQUE INDEX idx_people_name_lower ON people (LOWER(name));

INSERT INTO people (name)
SELECT MIN(TRIM(entered_by_name)) FROM rework_events
WHERE entered_by_name IS NOT NULL AND TRIM(entered_by_name) <> '' AND entered_date >= '2026-07-01'
GROUP BY LOWER(TRIM(entered_by_name));
