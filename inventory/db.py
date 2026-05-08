"""
inventory/db.py
---------------
Database connection management.

- get_db()    : returns a per-request connection stored on Flask g
- close_db()  : tears it down at end of request (registered in routes.py)
- init_db()   : creates schema from schema.sql (used by init script and tests)
- get_db_path(): resolves the database path from app config
"""

import sqlite3
import os
import click
from flask import g, current_app


def get_db_path():
    """
    Resolve DB path. Checks app config first (allows tests to override),
    then falls back to inventory.db alongside the package.
    """
    if current_app.config.get('DATABASE'):
        return current_app.config['DATABASE']
    return os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        '..', 'inventory.db'
    )


def get_db():
    """Return a per-request SQLite connection stored on Flask g."""
    if 'inv_db' not in g:
        path = get_db_path()
        g.inv_db = sqlite3.connect(path)
        g.inv_db.row_factory = sqlite3.Row
        g.inv_db.execute("PRAGMA foreign_keys = ON")
    return g.inv_db


def close_db(e=None):
    """Close the connection at the end of the request."""
    db = g.pop('inv_db', None)
    if db is not None:
        db.close()


def init_db():
    """Create all tables from schema.sql. Safe to re-run (IF NOT EXISTS)."""
    db = get_db()
    schema_path = os.path.join(os.path.dirname(__file__), 'schema.sql')
    with open(schema_path, 'r') as f:
        db.executescript(f.read())
    db.commit()


def seed_db():
    """Seed categories and sample locations. Safe to re-run (INSERT OR IGNORE)."""
    db = get_db()
    seed_path = os.path.join(os.path.dirname(__file__), 'seed.sql')
    with open(seed_path, 'r') as f:
        db.executescript(f.read())
    db.commit()


@click.command('init-inventory-db')
def init_db_command():
    """Flask CLI command: flask init-inventory-db"""
    init_db()
    seed_db()
    click.echo('Inventory database initialised and seeded.')
