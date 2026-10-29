-- SQLite baseline matching PostgreSQL migrations 0001 through 0014.
-- Separate history: future SQLite schema changes get their own migration.

CREATE TABLE audit_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    at          TIMESTAMPTZ NOT NULL DEFAULT (now()),
    username    TEXT NOT NULL,
    user_id     INTEGER REFERENCES users(id) ON DELETE SET NULL,
    action      TEXT NOT NULL,
    entity_type TEXT,
    entity_id   TEXT,
    detail      TEXT
);

CREATE TABLE colours (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    name      TEXT UNIQUE NOT NULL,
    active    BOOLEAN NOT NULL DEFAULT TRUE,
    synced_at TIMESTAMPTZ
, code TEXT, dulux_code TEXT, rgb TEXT, base_colour_code TEXT, base_colour_description TEXT);

CREATE TABLE cpq_door_codes (
    cpq_code  TEXT PRIMARY KEY,
    description TEXT NOT NULL
, family_name TEXT, active BOOLEAN NOT NULL DEFAULT TRUE);
INSERT INTO cpq_door_codes VALUES ('AQ', 'Aquila', 'Aquila', 1);
INSERT INTO cpq_door_codes VALUES ('AX', 'Axis', 'Axis', 1);
INSERT INTO cpq_door_codes VALUES ('BP', 'Panel', 'Panel', 1);
INSERT INTO cpq_door_codes VALUES ('CL', 'Classic', 'Classic', 1);
INSERT INTO cpq_door_codes VALUES ('CLP', 'Classic Plus', 'Classic Plus', 1);
INSERT INTO cpq_door_codes VALUES ('LT', 'Latitude', 'Latitude', 1);
INSERT INTO cpq_door_codes VALUES ('LTP', 'Latitude Plus', 'Latitude Plus', 1);
INSERT INTO cpq_door_codes VALUES ('SUM', 'Summerset', 'Summerset', 1);

CREATE TABLE door_types (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT UNIQUE NOT NULL,
    active     BOOLEAN NOT NULL DEFAULT TRUE,
    sort_order INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE erp_scrap_transactions (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
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
    synced_at         TIMESTAMPTZ NOT NULL DEFAULT (now())
);

CREATE TABLE items (
    part_number     TEXT PRIMARY KEY,
    description     TEXT,
    product_code    TEXT,
    product_group   TEXT,
    std_cost        NUMERIC(12,5),
    length_std      NUMERIC(10,1),
    length_oversize NUMERIC(10,1),
    rule            NUMERIC(10,4) NOT NULL DEFAULT 1,
    synced_at       TIMESTAMPTZ
, plan_code TEXT);

CREATE TABLE rework_events (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
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
    created_at         TIMESTAMPTZ NOT NULL DEFAULT (now()),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT (now())
, source_row_hash TEXT, entered_by_name TEXT);

CREATE TABLE rework_rates (
    part_number   TEXT PRIMARY KEY REFERENCES items(part_number) ON DELETE CASCADE,
    picking_min   NUMERIC(8,2) NOT NULL DEFAULT 0,
    cutting_min   NUMERIC(8,2) NOT NULL DEFAULT 0,
    machining_min NUMERIC(8,2) NOT NULL DEFAULT 0,
    unjig_cost    NUMERIC(8,2) NOT NULL DEFAULT 0,
    assembly_min  NUMERIC(8,2) NOT NULL DEFAULT 0,
    notes         TEXT
);

CREATE TABLE rework_reasons (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    reason         TEXT UNIQUE NOT NULL,
    code           TEXT,
    source         TEXT NOT NULL,
    fault_category TEXT,
    active         BOOLEAN NOT NULL DEFAULT TRUE,
    sort_order     INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE sessions (
    sid           TEXT PRIMARY KEY,
    user_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    username      TEXT NOT NULL,
    role          TEXT NOT NULL,
    ip            TEXT,
    user_agent    TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT (now()),
    last_seen_at  TIMESTAMPTZ NOT NULL DEFAULT (now())
);

CREATE TABLE settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
INSERT INTO settings VALUES ('hourly_rate', '110');

CREATE TABLE synced_order_materials (
    job_number   TEXT NOT NULL,
    part_number  TEXT NOT NULL,
    description  TEXT,
    qty          NUMERIC(12,4),
    unit         TEXT,
    unit_cost    NUMERIC(12,5),
    synced_at    TIMESTAMPTZ NOT NULL DEFAULT (now()),
    PRIMARY KEY (job_number, part_number)
);

CREATE TABLE synced_orders (
    so_number       TEXT PRIMARY KEY,
    job_number      TEXT,
    height          NUMERIC(10,1),
    width           NUMERIC(10,1),
    cpq_door_code   TEXT,
    colour_in_code  TEXT,
    colour_out_code TEXT,
    qty_ordered     NUMERIC(10,2),
    due_date        DATE,
    stat            TEXT,
    synced_at       TIMESTAMPTZ NOT NULL DEFAULT (now())
);

CREATE TABLE turret_events (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    event_date         DATE NOT NULL,
    door_type               TEXT,
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
    created_at         TIMESTAMPTZ NOT NULL DEFAULT (now())
, week_num        INTEGER, open_status     TEXT, scrap_date_a    DATE, scrap_sheet_a   TEXT, scrap_qty_a     NUMERIC(10,2), scrap_date_b    DATE, scrap_sheet_b   TEXT, scrap_qty_b     NUMERIC(10,2), scrap_date_c    DATE, scrap_sheet_c   TEXT, scrap_qty_c     NUMERIC(10,2), scrap_comments  TEXT, scrap_week      INTEGER, scrap_year      INTEGER, source_row_hash TEXT, colour      TEXT, rework_type TEXT, reason      TEXT, updated_at  TIMESTAMPTZ);

CREATE TABLE users (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    username              TEXT UNIQUE NOT NULL,
    password_hash         TEXT,
    role                  TEXT NOT NULL DEFAULT 'viewer',
    active                BOOLEAN NOT NULL DEFAULT TRUE,
    must_change_password  BOOLEAN NOT NULL DEFAULT FALSE,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT (now()),
    last_login_at         TIMESTAMPTZ
);

CREATE TABLE work_centres (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT UNIQUE NOT NULL,
    active     BOOLEAN NOT NULL DEFAULT TRUE,
    sort_order INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX idx_audit_log_at ON audit_log (at DESC);

CREATE INDEX idx_colours_code ON colours (code);

CREATE INDEX idx_rework_events_product_code ON rework_events (product_code);

CREATE INDEX idx_rework_events_reason       ON rework_events (reason);

CREATE INDEX idx_rework_events_rework_date  ON rework_events (rework_date);

CREATE UNIQUE INDEX idx_rework_events_source_row_hash ON rework_events (source_row_hash);

CREATE INDEX idx_synced_orders_job_number ON synced_orders (job_number);

CREATE INDEX idx_turret_events_event_date  ON turret_events (event_date);

CREATE INDEX idx_turret_events_job_number  ON turret_events (job_number);

CREATE UNIQUE INDEX idx_turret_events_source_row_hash ON turret_events (source_row_hash);
