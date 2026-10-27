-- Reversed 2026-10-22: Turret now reuses the shared "Reasons" list
-- (rework_reasons) instead of its own separate list -- turret_reasons never
-- held any real data (confirmed empty before being dropped), so there's
-- nothing to migrate into rework_reasons. turret_events.reason stays a
-- plain text column (no FK either way) -- it just draws its values from
-- rework_reasons.reason now instead.

DROP TABLE IF EXISTS turret_reasons;
