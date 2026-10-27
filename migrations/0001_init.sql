-- Initial schema for the Doors Rework tracker.
-- Mirrors Scheduler's users/sessions shape (see db.py there) so auth behaves
-- identically; everything else is new.

CREATE TABLE IF NOT EXISTS users (
    id                    SERIAL PRIMARY KEY,
    username              TEXT UNIQUE NOT NULL,
    password_hash         TEXT NOT NULL,
    role                  TEXT NOT NULL DEFAULT 'viewer',
    active                BOOLEAN NOT NULL DEFAULT TRUE,
    must_change_password  BOOLEAN NOT NULL DEFAULT FALSE,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_login_at         TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS sessions (
    sid           TEXT PRIMARY KEY,
    user_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    username      TEXT NOT NULL,
    role          TEXT NOT NULL,
    ip            TEXT,
    user_agent    TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── Reference data ──────────────────────────────────────────────────────────
-- Admin-editable (door_types, work_centres, rework_reasons). Colours and
-- items are the same shape but carry a `synced_at` — set whenever a row last
-- came from the ERP sync; NULL means it only exists locally.

CREATE TABLE IF NOT EXISTS rework_reasons (
    id             SERIAL PRIMARY KEY,
    reason         TEXT UNIQUE NOT NULL,
    code           TEXT,
    source         TEXT NOT NULL,
    fault_category TEXT,
    active         BOOLEAN NOT NULL DEFAULT TRUE,
    sort_order     INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS door_types (
    id         SERIAL PRIMARY KEY,
    name       TEXT UNIQUE NOT NULL,
    active     BOOLEAN NOT NULL DEFAULT TRUE,
    sort_order INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS work_centres (
    id         SERIAL PRIMARY KEY,
    name       TEXT UNIQUE NOT NULL,
    active     BOOLEAN NOT NULL DEFAULT TRUE,
    sort_order INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS colours (
    id        SERIAL PRIMARY KEY,
    name      TEXT UNIQUE NOT NULL,
    active    BOOLEAN NOT NULL DEFAULT TRUE,
    synced_at TIMESTAMPTZ
);

-- Item master. `rule` (units-per-part multiplier for Qty to Remove) is
-- locally owned and must survive an ERP sync untouched -- same pattern as
-- Scheduler's colour-rank sync preserving rank/family across a re-sync.
CREATE TABLE IF NOT EXISTS items (
    part_number     TEXT PRIMARY KEY,
    description     TEXT,
    product_code    TEXT,
    product_group   TEXT,
    std_cost        NUMERIC(12,5),
    length_std      NUMERIC(10,1),
    length_oversize NUMERIC(10,1),
    rule            NUMERIC(10,4) NOT NULL DEFAULT 1,
    synced_at       TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS rework_rates (
    part_number   TEXT PRIMARY KEY REFERENCES items(part_number) ON DELETE CASCADE,
    picking_min   NUMERIC(8,2) NOT NULL DEFAULT 0,
    cutting_min   NUMERIC(8,2) NOT NULL DEFAULT 0,
    machining_min NUMERIC(8,2) NOT NULL DEFAULT 0,
    unjig_cost    NUMERIC(8,2) NOT NULL DEFAULT 0,
    assembly_min  NUMERIC(8,2) NOT NULL DEFAULT 0,
    notes         TEXT
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
INSERT INTO settings (key, value) VALUES ('hourly_rate', '110')
    ON CONFLICT (key) DO NOTHING;

-- ── Core log ────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS rework_events (
    id                 SERIAL PRIMARY KEY,
    entered_date       DATE NOT NULL DEFAULT CURRENT_DATE,
    rework_date        DATE NOT NULL,
    due_date           DATE,
    type               TEXT NOT NULL CHECK (type IN ('Rework / Recoat', 'Replace Part', 'Scrap Entire Door')),
    so_number          TEXT NOT NULL,
    product_code       TEXT NOT NULL,
    quantity           NUMERIC(10,2) NOT NULL CHECK (quantity > 0),
    height_mm          NUMERIC(10,1),
    width_mm           NUMERIC(10,1),
    cut_length_mm      NUMERIC(10,1),
    qty_to_remove      NUMERIC(10,2),
    material_cost      NUMERIC(12,2),
    labour_cost        NUMERIC(12,2),
    reason             TEXT NOT NULL,
    source             TEXT,
    colour             TEXT NOT NULL,
    door_type          TEXT NOT NULL,
    work_centre        TEXT NOT NULL,
    notes              TEXT,
    entered_by_user_id INTEGER REFERENCES users(id),
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_rework_events_rework_date  ON rework_events (rework_date);
CREATE INDEX IF NOT EXISTS idx_rework_events_product_code ON rework_events (product_code);
CREATE INDEX IF NOT EXISTS idx_rework_events_reason       ON rework_events (reason);

-- ── Turret scrap log (separate shape -- keyed by job/sheet, not by door) ─────

CREATE TABLE IF NOT EXISTS turret_events (
    id                 SERIAL PRIMARY KEY,
    event_date         DATE NOT NULL,
    type               TEXT,
    sales_number       TEXT,
    job_number         TEXT,
    sheet_a            TEXT, qty_a_ordered NUMERIC(10,2), qty_a_picked NUMERIC(10,2),
    sheet_b            TEXT, qty_b_ordered NUMERIC(10,2), qty_b_picked NUMERIC(10,2),
    sheet_c            TEXT, qty_c_ordered NUMERIC(10,2), qty_c_picked NUMERIC(10,2),
    variation          TEXT,
    comments           TEXT,
    scrap_code         TEXT,
    scrap_cost         NUMERIC(12,2),
    entered_by_user_id INTEGER REFERENCES users(id),
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── ERP scrap transactions, for reconciliation (wholesale-replaced each sync) ─

CREATE TABLE IF NOT EXISTS erp_scrap_transactions (
    id                SERIAL PRIMARY KEY,
    week_num          INTEGER,
    txn_date          DATE,
    item              TEXT,
    description       TEXT,
    qty               NUMERIC(12,2),
    scrap_cost        NUMERIC(12,2),
    scrap_labour_cost NUMERIC(12,2),
    product_group     TEXT,
    product_code      TEXT,
    type              TEXT,
    user_code         TEXT,
    synced_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);
