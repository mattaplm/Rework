-- Powder-coat cost per rework entry (2026-11-11) -- see
-- migrations/0020_rework_pc_cost.sql.
ALTER TABLE rework_events ADD COLUMN pc_cost NUMERIC(12,2);
