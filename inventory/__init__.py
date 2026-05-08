"""
inventory/__init__.py
---------------------
Defines the inventory Blueprint.

Register in flask_app.py with:

    from inventory import inventory_bp
    app.register_blueprint(inventory_bp)

All inventory routes are then available under /inventory/ prefix.
"""

from flask import Blueprint

inventory_bp = Blueprint(
    'inventory',
    __name__,
    template_folder='templates',   # inventory/templates/
    static_folder='static',        # inventory/static/
    url_prefix='/inventory',
)

# Import routes so they register against the blueprint
from inventory import routes  # noqa: E402, F401
