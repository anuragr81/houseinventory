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
    """Create all tables from schema.sql and schema_auth.sql. Safe to re-run (IF NOT EXISTS)."""
    db = get_db()
    for fname in ('schema.sql', 'schema_auth.sql'):
        schema_path = os.path.join(os.path.dirname(__file__), fname)
        with open(schema_path, 'r') as f:
            db.executescript(f.read())
    db.commit()


def seed_locations_from_xml(db=None):
    """Load house structure from inventory/config/house.xml, validated against house.xsd.

    Accepts an optional db connection so tests can pass their own in-memory connection.
    Schema validation requires lxml; if lxml is not installed it is skipped silently.
    """
    import xml.etree.ElementTree as ET

    if db is None:
        db = get_db()

    config_dir = os.path.join(os.path.dirname(__file__), 'config')
    xml_path   = os.path.join(config_dir, 'house.xml')
    xsd_path   = os.path.join(config_dir, 'house.xsd')

    try:
        from lxml import etree
        with open(xsd_path, 'rb') as f:
            schema = etree.XMLSchema(etree.parse(f))
        with open(xml_path, 'rb') as f:
            schema.assertValid(etree.parse(f))
    except ImportError:
        pass  # lxml not available; skip schema validation

    root = ET.parse(xml_path).getroot()

    seen = {}
    for el in root.iter():
        code = el.get('code')
        if code is None:
            continue
        if code in seen:
            raise ValueError(
                f"Duplicate code '{code}' in house.xml "
                f"(first seen on <{seen[code]}>, repeated on <{el.tag}>)"
            )
        seen[code] = el.tag

    for room_el in root.findall('room'):
        room_code, room_name = room_el.get('code'), room_el.get('name')
        db.execute(
            "INSERT OR IGNORE INTO location (code, name, parent_id, level) VALUES (?, ?, NULL, 'ROOM')",
            (room_code, room_name),
        )
        room_id = db.execute(
            "SELECT id FROM location WHERE code = ?", (room_code,)
        ).fetchone()['id']

        for furn_el in room_el.findall('furniture'):
            furn_code, furn_name = furn_el.get('code'), furn_el.get('name')
            db.execute(
                "INSERT OR IGNORE INTO location (code, name, parent_id, level) VALUES (?, ?, ?, 'FURNITURE')",
                (furn_code, furn_name, room_id),
            )
            furn_id = db.execute(
                "SELECT id FROM location WHERE code = ?", (furn_code,)
            ).fetchone()['id']

            for shelf_el in furn_el.findall('shelf'):
                shelf_code, shelf_name = shelf_el.get('code'), shelf_el.get('name')
                db.execute(
                    "INSERT OR IGNORE INTO location (code, name, parent_id, level) VALUES (?, ?, ?, 'SHELF')",
                    (shelf_code, shelf_name, furn_id),
                )

    db.commit()


def seed_db():
    """Seed categories from seed.sql, then locations from house.xml. Safe to re-run."""
    db = get_db()
    seed_path = os.path.join(os.path.dirname(__file__), 'seed.sql')
    with open(seed_path, 'r') as f:
        db.executescript(f.read())
    db.commit()
    seed_locations_from_xml()


@click.command('init-inventory-db')
def init_db_command():
    """Flask CLI command: flask init-inventory-db"""
    init_db()
    seed_db()
    click.echo('Inventory database initialised and seeded.')


@click.command('clear-inventory')
@click.confirmation_option(prompt='This will delete ALL boxes and items. Continue?')
def clear_inventory_command():
    """Flask CLI command: flask clear-inventory — wipes boxes/items, keeps locations/categories/users."""
    db = get_db()
    db.execute("DELETE FROM box_item_log")
    db.execute("DELETE FROM box_item")
    db.execute("DELETE FROM box")
    # Reset auto-increment counters so IDs restart from 1
    for table in ('box_item_log', 'box_item', 'box'):
        db.execute("DELETE FROM sqlite_sequence WHERE name = ?", (table,))
    db.commit()
    click.echo('Inventory cleared: all boxes and items deleted.')
