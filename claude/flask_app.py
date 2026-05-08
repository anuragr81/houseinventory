"""
flask_app.py
-------------
Standalone Flask app for the home inventory system.
No Sanskrit dependencies — runs completely independently.

Setup:
    pip install flask flask-cors python-dotenv
    flask init-inventory-db
    flask run --debug

Or with host exposed to home network:
    flask run --debug --host=0.0.0.0
"""

import sys
import os

# Ensure the project root is on sys.path so 'inventory' package is found
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask
from flask_cors import CORS

from inventory import inventory_bp
from inventory.db import init_db_command

# ── App ───────────────────────────────────────────────────────────────────────

app = Flask(__name__)
CORS(app)

# ── Register inventory blueprint ──────────────────────────────────────────────

app.register_blueprint(inventory_bp)

# ── Register CLI commands ─────────────────────────────────────────────────────

app.cli.add_command(init_db_command)

# ── Root redirect ─────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return '''
    <html>
    <head>
      <title>Home Inventory</title>
      <meta name="viewport" content="width=device-width, initial-scale=1"/>
      <style>
        body { font-family: -apple-system, sans-serif; max-width: 400px;
               margin: 80px auto; padding: 20px; text-align: center; }
        h2   { font-size: 20px; margin-bottom: 32px; color: #1a1a18; }
        a    { display: block; padding: 16px; margin: 12px 0;
               border-radius: 10px; text-decoration: none;
               font-size: 16px; font-weight: 500; }
        .find   { background: #378ADD; color: #fff; }
        .update { background: #1D9E75; color: #fff; }
      </style>
    </head>
    <body>
      <h2>Home Inventory</h2>
      <a class="find"   href="/inventory/find">Find a box</a>
      <a class="update" href="/inventory/update">Store a box</a>
    </body>
    </html>
    '''

# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == '__main__':
    app.run(debug=True)
