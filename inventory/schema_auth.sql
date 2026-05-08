-- inventory/schema_auth.sql
-- User table for Flask-Login authentication.
-- Run once after schema.sql:
--   flask init-inventory-db   (already runs schema.sql)
--   Then run this manually, or let init_db() pick it up via the updated db.py

CREATE TABLE IF NOT EXISTS user (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT    NOT NULL UNIQUE,
    password_hash TEXT    NOT NULL,
    created_at    DATETIME DEFAULT CURRENT_TIMESTAMP
);
