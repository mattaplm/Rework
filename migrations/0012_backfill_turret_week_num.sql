-- Every turret_events row saved through the new web entry form (2026-10-21
-- onward, before this fix) never set week_num at all -- create_event's
-- INSERT simply didn't include it. That showed up on the Scrap write-off
-- tab's "From week(s)" column as the literal text "None" (array_agg'd
-- alongside real week numbers from historical imported rows, then Jinja's
-- join filter stringified the NULL). services/turret.py's create_event now
-- stamps week_num from event_date's own ISO week going forward; this
-- backfills every row already saved before that fix, using the same
-- definition (EXTRACT(WEEK FROM ...), confirmed elsewhere in this app to
-- match SQL Server's own DATEPART(WEEK, ...) for real dates).
UPDATE turret_events
SET week_num = EXTRACT(WEEK FROM event_date)::int
WHERE week_num IS NULL;
