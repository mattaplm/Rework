-- `plan_code` is a genuine ERP classification for raw sheet stock
-- (`plan_code = 'SHT'`), confirmed live 2026-10-22 against every known
-- sheet item with zero false positives -- replaces the hand-curated
-- services.erp_reconciliation.SHEET_ITEMS set. See queries.py's module
-- docstring for the full confirmation.

ALTER TABLE items ADD COLUMN IF NOT EXISTS plan_code TEXT;
