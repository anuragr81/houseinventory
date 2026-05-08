-- inventory/schema.sql
-- All tables for the inventory system.
-- Uses CREATE TABLE IF NOT EXISTS throughout — safe to re-run.

PRAGMA foreign_keys = ON;

-- ── Location hierarchy ────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS location (
    id         INTEGER  PRIMARY KEY AUTOINCREMENT,
    code       TEXT     NOT NULL UNIQUE,
    name       TEXT     NOT NULL,
    parent_id  INTEGER  REFERENCES location(id) ON DELETE RESTRICT,
    level      TEXT     NOT NULL   CHECK(level IN ('ROOM','FURNITURE','SHELF')),
    -- coordinate within parent (wall/i/j all nullable — added progressively)
    -- i = row 1-3 top→bottom, j = col 1-3 left→right, wall 1-4
    wall       INTEGER  CHECK(wall BETWEEN 1 AND 4),
    i          INTEGER  CHECK(i BETWEEN 1 AND 3),
    j          INTEGER  CHECK(j BETWEEN 1 AND 3),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- ── Category hierarchy ────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS super_category (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT    NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS mid_category (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    name              TEXT    NOT NULL,
    super_category_id INTEGER NOT NULL REFERENCES super_category(id),
    UNIQUE (name, super_category_id)
);

CREATE TABLE IF NOT EXISTS category (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    name              TEXT    NOT NULL,
    mid_category_id   INTEGER REFERENCES mid_category(id),
    super_category_id INTEGER NOT NULL REFERENCES super_category(id),
    UNIQUE (name, super_category_id)
);

-- ── Box ───────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS box (
    id          INTEGER  PRIMARY KEY AUTOINCREMENT,
    label       TEXT     NOT NULL UNIQUE,
    location_id INTEGER  NOT NULL REFERENCES location(id),
    notes       TEXT,
    updated_by  TEXT,
    updated_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    is_deleted  INTEGER  NOT NULL DEFAULT 0,
    deleted_at  DATETIME,
    -- coordinate within parent location
    wall        INTEGER  CHECK(wall BETWEEN 1 AND 4),
    i           INTEGER  CHECK(i BETWEEN 1 AND 3),
    j           INTEGER  CHECK(j BETWEEN 1 AND 3)
);

-- ── Box items (category membership — cardinality = 1 enforced by UNIQUE) ──────

CREATE TABLE IF NOT EXISTS box_item (
    id          INTEGER  PRIMARY KEY AUTOINCREMENT,
    box_id      INTEGER  NOT NULL REFERENCES box(id),
    category_id INTEGER  NOT NULL REFERENCES category(id),
    added_by    TEXT     NOT NULL,
    added_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
    is_removed  INTEGER  NOT NULL DEFAULT 0,
    removed_at  DATETIME,
    removed_by  TEXT,
    reason      TEXT     CHECK(reason IN ('consumed','moved','wrong_entry') OR reason IS NULL),
    -- coordinate within parent box
    wall        INTEGER  CHECK(wall BETWEEN 1 AND 4),
    i           INTEGER  CHECK(i BETWEEN 1 AND 3),
    j           INTEGER  CHECK(j BETWEEN 1 AND 3),
    UNIQUE (box_id, category_id)
);

-- ── Audit log ─────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS box_item_log (
    id          INTEGER  PRIMARY KEY AUTOINCREMENT,
    box_id      INTEGER  NOT NULL REFERENCES box(id),
    box_item_id INTEGER  REFERENCES box_item(id),
    action      TEXT     NOT NULL CHECK(action IN ('added','removed')),
    category_id INTEGER  NOT NULL REFERENCES category(id),
    changed_by  TEXT,
    changed_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);
