"""
inventory/models.py
--------------------
Pure database query functions. No Flask request/response objects.
All functions take a db connection as first argument — easily testable in isolation.

Functions are grouped by entity:
  - Location queries
  - Category queries
  - Box queries
  - Box item queries
"""

from datetime import datetime


# ── Helpers ───────────────────────────────────────────────────────────────────

def location_path(db, location_id):
    """
    Traverse parent_id chain and return full path string.
    e.g. "Kitchen > Cupboard 2 > Middle shelf"
    """
    parts = []
    node_id = location_id
    while node_id:
        row = db.execute(
            "SELECT id, name, parent_id FROM location WHERE id = ?",
            (node_id,)
        ).fetchone()
        if not row:
            break
        parts.append(row['name'])
        node_id = row['parent_id']
    parts.reverse()
    return ' > '.join(parts)


def coord_dict(row):
    """
    Extract (wall, i, j) from any row that carries coordinate columns.
    Returns a dict with wall/i/j — all None if not yet logged.
    Also returns a human-readable label when all three are present.
    """
    wall = row['wall'] if row['wall'] is not None else None
    i    = row['i']    if row['i']    is not None else None
    j    = row['j']    if row['j']    is not None else None
    label = None
    if wall is not None and i is not None and j is not None:
        row_name = {1: 'top', 2: 'middle', 3: 'bottom'}[i]
        col_name = {1: 'left', 2: 'centre', 3: 'right'}[j]
        label = f'W{wall} · {row_name} row · {col_name} column'
    return {'wall': wall, 'i': i, 'j': j, 'label': label}


def box_categories(db, box_id):
    """Return active category rows for a box, including item coordinates."""
    return db.execute("""
        SELECT c.id    AS category_id,
               c.name  AS category,
               mc.name AS mid_category,
               sc.name AS super_category,
               bi.wall, bi.i, bi.j
        FROM box_item bi
        JOIN category c           ON bi.category_id = c.id
        LEFT JOIN mid_category mc ON c.mid_category_id = mc.id
        JOIN super_category sc    ON c.super_category_id = sc.id
        WHERE bi.box_id = ? AND bi.is_removed = 0
        ORDER BY sc.name, mc.name, c.name
    """, (box_id,)).fetchall()


def box_to_dict(db, box):
    """Serialise a box Row to a plain dict with location path, coordinates and categories."""
    cats = box_categories(db, box['id'])
    return {
        'id':          box['id'],
        'label':       box['label'],
        'location_id': box['location_id'],
        'location':    location_path(db, box['location_id']),
        'coord':       coord_dict(box),
        'notes':       box['notes'],
        'updated_by':  box['updated_by'],
        'updated_at':  box['updated_at'],
        'categories': [
            {
                'category_id':    c['category_id'],
                'category':       c['category'],
                'mid_category':   c['mid_category'],
                'super_category': c['super_category'],
                'coord':          coord_dict(c),
            }
            for c in cats
        ],
    }


# ── Location queries ──────────────────────────────────────────────────────────

def get_location_hierarchy(db):
    """
    Return the full location hierarchy as a nested list:
    [ { room }, { furniture: [ { shelves: [] } ] } ]
    """
    rooms = db.execute(
        "SELECT * FROM location WHERE level = 'ROOM' ORDER BY name"
    ).fetchall()

    result = []
    for room in rooms:
        furniture_rows = db.execute(
            "SELECT * FROM location WHERE parent_id = ? AND level = 'FURNITURE' ORDER BY name",
            (room['id'],)
        ).fetchall()

        furniture_list = []
        for furn in furniture_rows:
            shelf_rows = db.execute(
                "SELECT * FROM location WHERE parent_id = ? AND level = 'SHELF' ORDER BY name",
                (furn['id'],)
            ).fetchall()
            furniture_list.append({
                'id':      furn['id'],
                'code':    furn['code'],
                'name':    furn['name'],
                'shelves': [
                    {'id': s['id'], 'code': s['code'], 'name': s['name']}
                    for s in shelf_rows
                ],
            })

        result.append({
            'id':        room['id'],
            'code':      room['code'],
            'name':      room['name'],
            'furniture': furniture_list,
        })
    return result


def get_location_by_id(db, location_id):
    """Return a single location row or None."""
    return db.execute(
        "SELECT * FROM location WHERE id = ?", (location_id,)
    ).fetchone()


# ── Category queries ──────────────────────────────────────────────────────────

def get_category_hierarchy(db):
    """
    Return the full category hierarchy as a nested list.
    Flat super-cats have flat=True and categories=[].
    Three-level super-cats have flat=False and mid_categories=[].
    """
    super_cats = db.execute(
        "SELECT * FROM super_category ORDER BY name"
    ).fetchall()

    result = []
    for sc in super_cats:
        mid_cats = db.execute(
            "SELECT * FROM mid_category WHERE super_category_id = ? ORDER BY name",
            (sc['id'],)
        ).fetchall()

        if mid_cats:
            mid_list = []
            for mc in mid_cats:
                cats = db.execute(
                    "SELECT * FROM category WHERE mid_category_id = ? ORDER BY name",
                    (mc['id'],)
                ).fetchall()
                mid_list.append({
                    'id':         mc['id'],
                    'name':       mc['name'],
                    'categories': [
                        {'id': c['id'], 'name': c['name']} for c in cats
                    ],
                })
            result.append({
                'id':             sc['id'],
                'name':           sc['name'],
                'flat':           False,
                'mid_categories': mid_list,
            })
        else:
            cats = db.execute(
                "SELECT * FROM category WHERE super_category_id = ? ORDER BY name",
                (sc['id'],)
            ).fetchall()
            result.append({
                'id':         sc['id'],
                'name':       sc['name'],
                'flat':       True,
                'categories': [
                    {'id': c['id'], 'name': c['name']} for c in cats
                ],
            })
    return result


def get_category_by_id(db, category_id):
    """Return a single category row or None."""
    return db.execute(
        "SELECT * FROM category WHERE id = ?", (category_id,)
    ).fetchone()


# ── Box queries ───────────────────────────────────────────────────────────────

def search_boxes(db, query):
    """
    Search boxes by label, notes, or category name.
    Returns list of dicts.
    """
    like = f'%{query}%'
    rows = db.execute("""
        SELECT DISTINCT b.id
        FROM box b
        LEFT JOIN box_item bi ON bi.box_id = b.id AND bi.is_removed = 0
        LEFT JOIN category c  ON bi.category_id = c.id
        WHERE b.is_deleted = 0
          AND (b.label LIKE ? OR b.notes LIKE ? OR c.name LIKE ?)
        ORDER BY b.updated_at DESC
    """, (like, like, like)).fetchall()

    result = []
    for row in rows:
        box = db.execute(
            "SELECT * FROM box WHERE id = ?", (row['id'],)
        ).fetchone()
        result.append(box_to_dict(db, box))
    return result


def get_boxes_at_location(db, location_id):
    """Return all active boxes at a given location_id."""
    rows = db.execute(
        "SELECT * FROM box WHERE location_id = ? AND is_deleted = 0 ORDER BY label",
        (location_id,)
    ).fetchall()
    return [box_to_dict(db, b) for b in rows]


def get_boxes_by_category(db, category_id):
    """Return all active boxes containing the given category."""
    rows = db.execute("""
        SELECT b.* FROM box b
        JOIN box_item bi ON bi.box_id = b.id
        WHERE bi.category_id = ? AND bi.is_removed = 0 AND b.is_deleted = 0
        ORDER BY b.label
    """, (category_id,)).fetchall()
    return [box_to_dict(db, b) for b in rows]


def get_box_by_id(db, box_id):
    """Return a single active box dict or None."""
    box = db.execute(
        "SELECT * FROM box WHERE id = ? AND is_deleted = 0", (box_id,)
    ).fetchone()
    return box_to_dict(db, box) if box else None


def get_box_by_label(db, label):
    """Return a box row (including deleted) matching label, or None."""
    return db.execute(
        "SELECT * FROM box WHERE label = ?", (label,)
    ).fetchone()


def autocomplete_boxes(db, query, limit=10):
    """Return matching box labels for autocomplete."""
    rows = db.execute("""
        SELECT id, label, location_id, updated_by
        FROM box
        WHERE label LIKE ? AND is_deleted = 0
        ORDER BY label
        LIMIT ?
    """, (f'%{query}%', limit)).fetchall()

    return [
        {
            'id':         r['id'],
            'label':      r['label'],
            'location':   location_path(db, r['location_id']),
            'updated_by': r['updated_by'],
        }
        for r in rows
    ]


def save_box(db, label, location_id, notes, updated_by, wall=None, i=None, j=None):
    """
    Create a new box or update an existing one (by label).
    wall/i/j are optional coordinates within the parent location.
    Returns (action, box_dict) where action is 'created' or 'updated'.
    """
    now = datetime.utcnow().isoformat()
    existing = get_box_by_label(db, label)

    if existing:
        db.execute("""
            UPDATE box
            SET location_id = ?, notes = ?, updated_by = ?, updated_at = ?,
                is_deleted = 0, deleted_at = NULL,
                wall = ?, i = ?, j = ?
            WHERE id = ?
        """, (location_id, notes, updated_by, now, wall, i, j, existing['id']))
        db.commit()
        box = db.execute("SELECT * FROM box WHERE id = ?", (existing['id'],)).fetchone()
        return 'updated', box_to_dict(db, box)
    else:
        cur = db.execute("""
            INSERT INTO box (label, location_id, notes, updated_by, updated_at, wall, i, j)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (label, location_id, notes, updated_by, now, wall, i, j))
        db.commit()
        box = db.execute("SELECT * FROM box WHERE id = ?", (cur.lastrowid,)).fetchone()
        return 'created', box_to_dict(db, box)


def delete_box(db, box_id, deleted_by):
    """
    Soft delete a box.
    Returns the box label if found and deleted, None if not found.
    """
    box = db.execute(
        "SELECT * FROM box WHERE id = ? AND is_deleted = 0", (box_id,)
    ).fetchone()
    if not box:
        return None

    now = datetime.utcnow().isoformat()
    db.execute("""
        UPDATE box
        SET is_deleted = 1, deleted_at = ?, updated_by = ?, updated_at = ?
        WHERE id = ?
    """, (now, deleted_by, now, box_id))
    db.commit()
    return box['label']


# ── Box item queries ──────────────────────────────────────────────────────────

def add_box_item(db, box_id, category_id, added_by, wall=None, i=None, j=None):
    """
    Add a category to a box. Enforces cardinality = 1.
    wall/i/j are optional coordinates within the box.
    Returns (success, message, item_id).
    """
    now = datetime.utcnow().isoformat()

    # Verify box exists
    box = db.execute(
        "SELECT id FROM box WHERE id = ? AND is_deleted = 0", (box_id,)
    ).fetchone()
    if not box:
        return False, 'Box not found', None

    # Verify category exists
    cat = get_category_by_id(db, category_id)
    if not cat:
        return False, 'Category not found', None

    # Check for existing row (active or removed)
    existing = db.execute(
        "SELECT * FROM box_item WHERE box_id = ? AND category_id = ?",
        (box_id, category_id)
    ).fetchone()

    if existing:
        if not existing['is_removed']:
            return False, 'Category already active in this box', None
        # Reinstate previously removed item, update coordinates
        db.execute("""
            UPDATE box_item
            SET is_removed = 0, removed_at = NULL, removed_by = NULL,
                reason = NULL, added_by = ?, added_at = ?,
                wall = ?, i = ?, j = ?
            WHERE id = ?
        """, (added_by, now, wall, i, j, existing['id']))
        item_id = existing['id']
    else:
        cur = db.execute("""
            INSERT INTO box_item (box_id, category_id, added_by, added_at, wall, i, j)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (box_id, category_id, added_by, now, wall, i, j))
        item_id = cur.lastrowid

    # Log
    db.execute("""
        INSERT INTO box_item_log (box_id, box_item_id, action, category_id, changed_by, changed_at)
        VALUES (?, ?, 'added', ?, ?, ?)
    """, (box_id, item_id, category_id, added_by, now))

    # Update box timestamp
    db.execute(
        "UPDATE box SET updated_by = ?, updated_at = ? WHERE id = ?",
        (added_by, now, box_id)
    )
    db.commit()
    return True, 'added', item_id


def remove_box_item(db, box_id, item_id, removed_by, reason='consumed'):
    """
    Soft-remove a category from a box.
    Returns (success, message).
    reason: 'consumed' | 'moved' | 'wrong_entry'
    """
    valid_reasons = ('consumed', 'moved', 'wrong_entry')
    if reason not in valid_reasons:
        reason = 'consumed'

    now  = datetime.utcnow().isoformat()
    item = db.execute(
        "SELECT * FROM box_item WHERE id = ? AND box_id = ?",
        (item_id, box_id)
    ).fetchone()

    if not item:
        return False, 'Item not found'

    if item['is_removed']:
        return False, 'Item already removed'

    db.execute("""
        UPDATE box_item
        SET is_removed = 1, removed_at = ?, removed_by = ?, reason = ?
        WHERE id = ?
    """, (now, removed_by, reason, item_id))

    db.execute("""
        INSERT INTO box_item_log (box_id, box_item_id, action, category_id, changed_by, changed_at)
        VALUES (?, ?, 'removed', ?, ?, ?)
    """, (box_id, item_id, item['category_id'], removed_by, now))

    db.execute(
        "UPDATE box SET updated_by = ?, updated_at = ? WHERE id = ?",
        (removed_by, now, box_id)
    )
    db.commit()
    return True, 'removed'
