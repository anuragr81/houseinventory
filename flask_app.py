"""
flask_app.py
-------------
Standalone Flask app for the home inventory system.

Setup:
    pip install -r requirements.txt
    flask init-inventory-db
    flask create-user <username>    # sets up login credentials
    flask run --debug

Or with host exposed to home network:
    flask run --debug --host=0.0.0.0

Then visit:  http://127.0.0.1:5000
"""

import sys
import os

# Ensure the project root is on sys.path so 'inventory' package is found
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask
from flask_cors import CORS
from flask_login import login_required

from inventory import inventory_bp
from inventory.db import init_db_command
from inventory.auth import login_manager, auth_bp, create_user_command

# ── App ───────────────────────────────────────────────────────────────────────

app = Flask(__name__)
CORS(app)

# SECRET_KEY is required for sessions (Flask-Login).
# On PythonAnywhere: set this as an environment variable, never commit it.
# Locally it falls back to a dev-only value.
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'change-me-before-deploying')

# ── Flask-Login ───────────────────────────────────────────────────────────────

login_manager.init_app(app)

# ── Register blueprints ───────────────────────────────────────────────────────

app.register_blueprint(auth_bp)           # /login, /logout
app.register_blueprint(inventory_bp)      # /inventory/...

# ── Register CLI commands ─────────────────────────────────────────────────────

app.cli.add_command(init_db_command)
app.cli.add_command(create_user_command)

# ── Root ──────────────────────────────────────────────────────────────────────

@app.route('/')
@login_required
def index():
    return '''
    <html>
    <head>
      <title>Home Inventory</title>
      <meta name="viewport" content="width=device-width, initial-scale=1"/>
      <style>
        *, *::before, *::after { box-sizing: border-box; }
        body { font-family: -apple-system, sans-serif; max-width: 400px;
               margin: 80px auto; padding: 20px; text-align: center; }
        h2   { font-size: 20px; margin-bottom: 32px; color: #1a1a18; }
        a    { display: block; padding: 16px; margin: 12px 0;
               border-radius: 10px; text-decoration: none;
               font-size: 16px; font-weight: 500; }
        .find   { background: #378ADD; color: #fff; }
        .update { background: #1D9E75; color: #fff; }
        .logout { background: #eee; color: #555; font-size: 14px;
                  padding: 10px; margin-top: 32px; }
      </style>
    </head>
    <body>
      <h2>Home Inventory</h2>
      <a class="find"   href="/inventory/find">Find a box</a>
      <a class="update" href="/inventory/update">Store a box</a>
      <a class="logout" href="/logout">Sign out</a>
    </body>
    </html>
    '''

# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == '__main__':
    app.run(debug=True)
