"""
tests/conftest.py
------------------
Shared pytest fixtures.

The core problem with SQLite :memory: databases in Flask tests:
  - Each sqlite3.connect(':memory:') creates a brand new empty database
  - Flask's get_db() calls connect() on every new request context via g
  - So each test request would get a fresh empty database with no tables

The fix:
  - Create ONE persistent connection per test function
  - Run schema.sql and seed.sql directly on that connection
  - Monkey-patch get_db() in inventory.db and inventory.routes to always
    return this single connection for the lifetime of the test
  - Close the connection after the test completes
"""

import pytest
import sqlite3
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from flask import Flask


def _base():
    return os.path.join(os.path.dirname(__file__), '..', 'inventory')


def _make_connection():
    """Create and fully initialise one in-memory SQLite connection."""
    conn = sqlite3.connect(':memory:', check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    with open(os.path.join(_base(), 'schema.sql')) as f:
        conn.executescript(f.read())
    with open(os.path.join(_base(), 'seed.sql')) as f:
        conn.executescript(f.read())
    return conn


def _patch_get_db(conn):
    """Replace get_db() in every module that imports it."""
    import inventory.db     as db_mod
    import inventory.routes as routes_mod

    def _get_db():
        return conn

    db_mod.get_db     = _get_db
    routes_mod.get_db = _get_db


@pytest.fixture(scope='function')
def conn():
    """One persistent in-memory SQLite connection per test."""
    c = _make_connection()
    _seed_test_data(c)
    yield c
    c.close()


@pytest.fixture(scope='function')
def app(conn):
    """Flask test app wired to the persistent test connection."""
    from inventory import inventory_bp

    _app = Flask(
        __name__,
        template_folder=os.path.join(_base(), 'templates')
    )
    _app.config.update({
        'TESTING':    True,
        'DATABASE':   ':memory:',
        'SECRET_KEY': 'test',
    })
    _app.register_blueprint(inventory_bp)
    _patch_get_db(conn)
    return _app


@pytest.fixture(scope='function')
def client(app):
    return app.test_client()


@pytest.fixture(scope='function')
def db(conn):
    """Direct database connection — same one the app uses."""
    return conn


def _seed_test_data(db):
    def loc(code):
        row = db.execute(
            "SELECT id FROM location WHERE code = ?", (code,)
        ).fetchone()
        assert row is not None, f"Location '{code}' not in seed.sql"
        return row['id']

    def cat(name):
        row = db.execute(
            "SELECT id FROM category WHERE name = ?", (name,)
        ).fetchone()
        assert row is not None, f"Category '{name}' not in seed.sql"
        return row['id']

    db.executemany("""
        INSERT OR IGNORE INTO box (label, location_id, notes, updated_by, updated_at)
        VALUES (?, ?, ?, ?, datetime('now'))
    """, [
        ('Chickpeas & Pulses', loc('KIT-C2-S2'), '3 tins',    'Anurag'),
        ('Pasta & Rice',       loc('KIT-C1-S1'), '',           'Spouse'),
        ('Stationery',         loc('STU-BS1-S3'), '',          'Anurag'),
        ('Power drill kit',    loc('GAR-SH-S1'), 'Bosch 18V', 'Anurag'),
    ])
    db.commit()

    for box_label, cat_name in [
        ('Chickpeas & Pulses', 'Dry food items'),
        ('Pasta & Rice',       'Dry food items'),
        ('Stationery',         'Stationery'),
        ('Power drill kit',    'Power tools'),
    ]:
        box_id = db.execute(
            "SELECT id FROM box WHERE label = ?", (box_label,)
        ).fetchone()['id']
        db.execute("""
            INSERT OR IGNORE INTO box_item (box_id, category_id, added_by, added_at)
            VALUES (?, ?, 'test', datetime('now'))
        """, (box_id, cat(cat_name)))
    db.commit()


def get_box_id(db, label):
    row = db.execute("SELECT id FROM box WHERE label = ?", (label,)).fetchone()
    return row['id'] if row else None


def get_category_id(db, name):
    row = db.execute("SELECT id FROM category WHERE name = ?", (name,)).fetchone()
    return row['id'] if row else None


def get_location_id(db, code):
    row = db.execute("SELECT id FROM location WHERE code = ?", (code,)).fetchone()
    return row['id'] if row else None
