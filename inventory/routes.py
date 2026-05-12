"""
inventory/routes.py
--------------------
Flask routes for the inventory Blueprint.
Each route is a thin wrapper — validates input, calls a model function,
returns JSON or renders a template. No SQL here.
"""

from flask import request, jsonify, render_template, current_app
from flask_login import login_required, current_user
from inventory import inventory_bp
from inventory.db import get_db, close_db, init_db, seed_db, init_db_command, clear_inventory_command
from inventory import models


# ── Teardown ──────────────────────────────────────────────────────────────────

@inventory_bp.teardown_app_request
def teardown_db(e=None):
    close_db(e)


# ── CLI command registration ──────────────────────────────────────────────────

@inventory_bp.record_once
def register_cli(state):
    state.app.cli.add_command(init_db_command)
    state.app.cli.add_command(clear_inventory_command)


# ── Page routes ───────────────────────────────────────────────────────────────

@inventory_bp.route('/find')
@login_required
def find_page():
    return render_template('inventory/find.html')


@inventory_bp.route('/update')
@login_required
def update_page():
    return render_template('inventory/update.html', username=current_user.username)


# ── API: search ───────────────────────────────────────────────────────────────

@inventory_bp.route('/api/search')
@login_required
def api_search():
    """GET /inventory/api/search?q=chickpeas"""
    q = request.args.get('q', '').strip()
    if not q:
        return jsonify([])
    return jsonify(models.search_boxes(get_db(), q))


# ── API: location hierarchy ───────────────────────────────────────────────────

@inventory_bp.route('/api/locations')
@login_required
def api_locations():
    """GET /inventory/api/locations"""
    return jsonify(models.get_location_hierarchy(get_db()))


# ── API: category hierarchy ───────────────────────────────────────────────────

@inventory_bp.route('/api/categories')
@login_required
def api_categories():
    """GET /inventory/api/categories"""
    return jsonify(models.get_category_hierarchy(get_db()))


# ── API: boxes at a location ──────────────────────────────────────────────────

@inventory_bp.route('/api/location/<int:location_id>/boxes')
@login_required
def api_location_boxes(location_id):
    """GET /inventory/api/location/<id>/boxes"""
    db  = get_db()
    loc = models.get_location_by_id(db, location_id)
    if not loc:
        return jsonify({'error': 'Location not found'}), 404
    return jsonify(models.get_boxes_at_location(db, location_id))


# ── API: boxes by category ────────────────────────────────────────────────────

@inventory_bp.route('/api/category/<int:category_id>/boxes')
@login_required
def api_category_boxes(category_id):
    """GET /inventory/api/category/<id>/boxes"""
    db  = get_db()
    cat = models.get_category_by_id(db, category_id)
    if not cat:
        return jsonify({'error': 'Category not found'}), 404
    return jsonify(models.get_boxes_by_category(db, category_id))


# ── API: autocomplete ─────────────────────────────────────────────────────────

@inventory_bp.route('/api/autocomplete')
@login_required
def api_autocomplete():
    """GET /inventory/api/autocomplete?q=chick"""
    q = request.args.get('q', '').strip()
    if not q:
        return jsonify([])
    return jsonify(models.autocomplete_boxes(get_db(), q))


# ── API: get single box ───────────────────────────────────────────────────────

@inventory_bp.route('/api/box/<int:box_id>', methods=['GET'])
@login_required
def api_get_box(box_id):
    """GET /inventory/api/box/<id>"""
    box = models.get_box_by_id(get_db(), box_id)
    if not box:
        return jsonify({'error': 'Box not found'}), 404
    return jsonify(box)


# ── API: save box (create or update) ─────────────────────────────────────────

@inventory_bp.route('/api/box', methods=['POST'])
@login_required
def api_save_box():
    """
    POST /inventory/api/box
    Body: { label, location_id, notes, updated_by, wall?, i?, j? }
    wall/i/j are optional — null means coordinate not yet logged.
    """
    data = request.get_json(silent=True)
    if not data:
        return jsonify({'error': 'Invalid JSON'}), 400

    label       = (data.get('label') or '').strip()
    location_id = data.get('location_id')
    notes       = (data.get('notes') or '').strip()
    updated_by  = (data.get('updated_by') or '').strip()
    wall        = data.get('wall')
    i           = data.get('i')
    j           = data.get('j')

    if not label:
        return jsonify({'error': 'label is required'}), 400
    if not location_id:
        return jsonify({'error': 'location_id is required'}), 400
    if not updated_by:
        return jsonify({'error': 'updated_by is required'}), 400

    # Validate coordinates if provided
    for name, val in [('wall', wall), ('i', i), ('j', j)]:
        if val is not None:
            if not isinstance(val, int):
                return jsonify({'error': f'{name} must be an integer'}), 400
            lo, hi = (1, 4) if name == 'wall' else (1, 3)
            if not (lo <= val <= hi):
                return jsonify({'error': f'{name} must be between {lo} and {hi}'}), 400

    db  = get_db()
    loc = models.get_location_by_id(db, location_id)
    if not loc:
        return jsonify({'error': 'location_id does not exist'}), 400

    action, box = models.save_box(db, label, location_id, notes, updated_by, wall, i, j)
    status_code = 201 if action == 'created' else 200
    return jsonify({'action': action, 'box': box}), status_code


# ── API: soft delete box ──────────────────────────────────────────────────────

@inventory_bp.route('/api/box/<int:box_id>', methods=['DELETE'])
@login_required
def api_delete_box(box_id):
    """
    DELETE /inventory/api/box/<id>
    Body: { deleted_by }
    """
    data       = request.get_json(silent=True) or {}
    deleted_by = (data.get('deleted_by') or '').strip()

    label = models.delete_box(get_db(), box_id, deleted_by)
    if label is None:
        return jsonify({'error': 'Box not found'}), 404
    return jsonify({'action': 'deleted', 'label': label}), 200


# ── API: add category to box ──────────────────────────────────────────────────

@inventory_bp.route('/api/box/<int:box_id>/item', methods=['POST'])
@login_required
def api_add_box_item(box_id):
    """
    POST /inventory/api/box/<id>/item
    Body: { category_id, added_by, wall?, i?, j? }
    wall/i/j locate the item within the box — all optional.
    """
    data = request.get_json(silent=True)
    if not data:
        return jsonify({'error': 'Invalid JSON'}), 400

    category_id = data.get('category_id')
    added_by    = (data.get('added_by') or '').strip()
    wall        = data.get('wall')
    i           = data.get('i')
    j           = data.get('j')

    if not category_id:
        return jsonify({'error': 'category_id is required'}), 400
    if not added_by:
        return jsonify({'error': 'added_by is required'}), 400

    # Validate coordinates if provided
    for name, val in [('wall', wall), ('i', i), ('j', j)]:
        if val is not None:
            if not isinstance(val, int):
                return jsonify({'error': f'{name} must be an integer'}), 400
            lo, hi = (1, 4) if name == 'wall' else (1, 3)
            if not (lo <= val <= hi):
                return jsonify({'error': f'{name} must be between {lo} and {hi}'}), 400

    success, message, item_id = models.add_box_item(
        get_db(), box_id, category_id, added_by, wall, i, j
    )

    if not success:
        status = 409 if 'already active' in message else 404
        return jsonify({'error': message}), status

    return jsonify({'action': 'added', 'box_item_id': item_id}), 201


# ── API: remove category from box ────────────────────────────────────────────

@inventory_bp.route('/api/box/<int:box_id>/item/<int:item_id>', methods=['DELETE'])
@login_required
def api_remove_box_item(box_id, item_id):
    """
    DELETE /inventory/api/box/<id>/item/<item_id>
    Body: { removed_by, reason }
    """
    data       = request.get_json(silent=True) or {}
    removed_by = (data.get('removed_by') or '').strip()
    reason     = (data.get('reason') or 'consumed').strip()

    success, message = models.remove_box_item(
        get_db(), box_id, item_id, removed_by, reason
    )

    if not success:
        return jsonify({'error': message}), 404
    return jsonify({'action': 'removed', 'reason': reason}), 200
