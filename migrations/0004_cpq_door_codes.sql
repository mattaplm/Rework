-- Maps coitem_all.Uf_aplCPQDoorProdCode (the CPQ door product code on a sales
-- order line, e.g. 'AXL', 'SUM') to this app's door_types.name, so looking up
-- a Sales Order can suggest a Door Type instead of leaving it to be typed
-- from memory. Admin-editable (like rework_reasons/door_types/work_centres),
-- not hardcoded in Python -- several real codes are genuinely ambiguous
-- between two or three plausible door types with nothing in the data alone
-- to disambiguate them, so this is seeded with only the confirmed mappings
-- and left for an admin to fill in the rest.
CREATE TABLE IF NOT EXISTS cpq_door_codes (
    cpq_code  TEXT PRIMARY KEY,
    door_type TEXT NOT NULL
);

-- Confirmed 2026-10-20 against real orders + the historical rework log's own
-- door_type counts (e.g. 'SUM' -> 508 real "Summerset" entries, 'AQ' -> 17
-- real "Aquila" entries). Deliberately NOT seeded: DR, DSM, SLP, the PL*
-- family (PLD/PLG/PLL/PLN/PLP/PLS), and every 'M'/'L'-suffixed code
-- (AXL/AXM/AXP, CLM, LTL/LTM) -- corrected 2026-10-20, confirmed with the
-- department: these suffixes mark distinct variants this app's door_types
-- doesn't have yet (e.g. AXL = "Axis Lite", not plain Axis), not the base
-- type as first guessed. Only 'P' = "Plus" was confirmed safe to keep,
-- because "Classic Plus"/"Latitude Plus" already exist as their own
-- door_types -- CLP/LTP map to those, not to plain Classic/Latitude.
-- Left unmapped until the missing door_types rows exist (admin-added) and
-- someone maps the matching code to them via Admin -> Door Codes.
INSERT INTO cpq_door_codes (cpq_code, door_type) VALUES
    ('AQ',  'Aquila'),
    ('AX',  'Axis'),
    ('BP',  'Panel'),
    ('CL',  'Classic'),
    ('CLP', 'Classic Plus'),
    ('LT',  'Latitude'),
    ('LTP', 'Latitude Plus'),
    ('SUM', 'Summerset')
ON CONFLICT (cpq_code) DO NOTHING;
