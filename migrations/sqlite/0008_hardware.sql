-- Hardware department (2026-11-11): its own PC rework/scrap log, replacing
-- the "Master Data Sheet" of 'Scrap Rework - Use this one V2.xlsx', plus its
-- own admin data. Nothing here is shared with Doors except users/colours.

-- Reasons / fault types: the sheet's DATA VALIDATION tab, column D, with
-- column E's Scrap Y/N (a reason decides whether the parts are scrapped or
-- just reworked).
CREATE TABLE hw_reasons (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    reason     TEXT UNIQUE NOT NULL,
    is_scrap   BOOLEAN NOT NULL DEFAULT TRUE,
    active     BOOLEAN NOT NULL DEFAULT TRUE,
    sort_order INTEGER NOT NULL DEFAULT 0
);

-- Parts and their costs: the sheet's "Data Sheet" tab (what its VLOOKUPs
-- read). Admin-maintained here; the import only adds parts not already listed.
CREATE TABLE hw_parts (
    part_number   TEXT PRIMARY KEY,
    unit_cost     NUMERIC(12,6),
    supplier      TEXT,
    product_code  TEXT,
    material      TEXT,
    material_cost NUMERIC(12,6),
    active        BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE hw_powdercoaters (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT UNIQUE NOT NULL,
    active     BOOLEAN NOT NULL DEFAULT TRUE,
    sort_order INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE hw_assemblers (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT UNIQUE NOT NULL,
    active     BOOLEAN NOT NULL DEFAULT TRUE,
    sort_order INTEGER NOT NULL DEFAULT 0
);

-- One row per part line of a remake request. Part cost fields are a snapshot
-- taken when the entry is saved (or the sheet's own cached figures, for
-- imported rows), so a later cost change never rewrites history.
CREATE TABLE hw_events (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    status              TEXT NOT NULL,
    so_number           TEXT,
    job_number          TEXT,
    part_number         TEXT NOT NULL,
    quantity            INTEGER NOT NULL,
    colour              TEXT,
    colour_code         TEXT,
    location            TEXT,
    request_date        DATE NOT NULL,
    cocreate_date       DATE,
    pick_date           DATE,
    complete_date       DATE,
    reason              TEXT,
    is_scrap            BOOLEAN NOT NULL DEFAULT FALSE,
    powdercoater        TEXT,
    assembler           TEXT,
    comments            TEXT,
    product_code        TEXT,
    material            TEXT,
    supplier            TEXT,
    unit_cost           NUMERIC(12,6),
    material_cost       NUMERIC(12,6),
    scrap_cost          NUMERIC(12,2),
    material_scrap_cost NUMERIC(12,2),
    entered_by_user_id  INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT (now()),
    updated_at          TIMESTAMPTZ,
    source_row_hash     TEXT UNIQUE
);
CREATE INDEX idx_hw_events_request_date ON hw_events (request_date);
CREATE INDEX idx_hw_events_part ON hw_events (part_number);
CREATE INDEX idx_hw_events_status ON hw_events (status);

INSERT INTO hw_reasons (reason, is_scrap, sort_order) VALUES
    ('ANO FAULT', TRUE, 1),
    ('ASSEMBLY ERROR', TRUE, 2),
    ('BENT', TRUE, 3),
    ('BOWED', TRUE, 4),
    ('CANCELLED ORDER', TRUE, 5),
    ('CONTAMINATION', TRUE, 6),
    ('DEFECTIVE', TRUE, 7),
    ('DENTS', TRUE, 8),
    ('EXCESS', TRUE, 9),
    ('FELL IN OVEN', TRUE, 10),
    ('HOARDING', TRUE, 11),
    ('JIG', TRUE, 12),
    ('OVEN FAULT', TRUE, 13),
    ('PITTING', TRUE, 14),
    ('POWDER SPIT', TRUE, 15),
    ('POWDER THICK', TRUE, 16),
    ('RUBBISH', TRUE, 17),
    ('WRONG COLOUR', TRUE, 18),
    ('WRONG SIZE', TRUE, 19),
    ('WRONG SUPPLY', TRUE, 20),
    ('TESTING', TRUE, 21),
    ('CNC', TRUE, 22),
    ('BAD POWDER', TRUE, 23),
    ('GAS BUBBLE', TRUE, 24),
    ('COLD LAYER', TRUE, 25),
    ('CASTING EDGE', TRUE, 26),
    ('INCOMPLETE CASTING', TRUE, 27),
    ('OLD PRODUCT', TRUE, 28),
    ('LIGHT PC', FALSE, 29),
    ('MISSING', FALSE, 30),
    ('SCRATCH', TRUE, 31),
    ('NOT POWDERCOATED', FALSE, 32),
    ('EMERGENCY / OVEN BREAKDOWN', TRUE, 33),
    ('Extra', TRUE, 34),
    ('Fell In Oven HW', TRUE, 35),
    ('Fell in Oven Batch', TRUE, 36),
    ('INCORRECT ORDERING', TRUE, 37),
    ('OBSOLETE COLOUR', TRUE, 38),
    ('PIN HOLES', TRUE, 39),
    ('ZINC CRACK', TRUE, 40),
    ('ZINC DEFECTIVE', TRUE, 41),
    ('POWDER BUBBLE', TRUE, 42),
    ('GREEN BUBBLE', TRUE, 43),
    ('RESPRAY', TRUE, 44),
    ('INCORRECT BOMS', FALSE, 45),
    ('ANO PC', TRUE, 46),
    ('GATING LINE', TRUE, 47);
