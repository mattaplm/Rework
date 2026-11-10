-- Powder-coat cost per rework entry (2026-11-11): Admin -> Cost's PC
-- flightbar rate + Powder, charged once per entry on its first Rework /
-- Recoat or Replace Part line. Replaces the old flat $132 Rework / Recoat
-- charge for new entries; historical rows keep their own material_cost
-- (including the $132 figures) untouched and leave this NULL.
ALTER TABLE rework_events ADD COLUMN pc_cost NUMERIC(12,2);
