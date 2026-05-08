"""
inventory/auth.py
-----------------
Authentication routes and user management.

Provides:
  - /login   GET  — login page
  - /login   POST — credential check
  - /logout  GET  — clear session

  - flask create-user  — CLI command to add/update a user

Users are stored in the `user` table (see schema_auth.sql).
Passwords are hashed with werkzeug.security (pbkdf2:sha256).
"""

import click
from flask import request, redirect, url_for, render_template_string, flash
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required
from werkzeug.security import generate_password_hash, check_password_hash
from inventory.db import get_db

# ── LoginManager (attached to app in flask_app.py) ────────────────────────────

login_manager = LoginManager()
login_manager.login_view = 'auth.login'
login_manager.login_message = 'Please log in to access the inventory.'


# ── User model ────────────────────────────────────────────────────────────────

class User(UserMixin):
    def __init__(self, id_, username):
        self.id = id_
        self.username = username

    @staticmethod
    def get(user_id, db):
        row = db.execute(
            'SELECT id, username FROM user WHERE id = ?', (user_id,)
        ).fetchone()
        return User(row['id'], row['username']) if row else None

    @staticmethod
    def get_by_username(username, db):
        row = db.execute(
            'SELECT id, username, password_hash FROM user WHERE username = ?',
            (username,)
        ).fetchone()
        return row  # return raw row so caller can check password_hash


# ── Flask-Login user loader ───────────────────────────────────────────────────

@login_manager.user_loader
def load_user(user_id):
    from flask import g
    import sqlite3
    from inventory.db import get_db as _get_db
    # get_db() requires an active app context — safe to call here
    try:
        db = _get_db()
        return User.get(int(user_id), db)
    except Exception:
        return None


# ── Blueprint import (auth routes attached to inventory_bp) ──────────────────
# We register these on a separate tiny blueprint so they sit outside /inventory/

from flask import Blueprint
auth_bp = Blueprint('auth', __name__)


_LOGIN_TEMPLATE = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>Login — Home Inventory</title>
  <style>
    *, *::before, *::after { box-sizing: border-box; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
      background: #f4f4f2;
      display: flex; align-items: center; justify-content: center;
      min-height: 100vh; margin: 0;
    }
    .card {
      background: #fff; border-radius: 14px; padding: 40px 36px;
      width: 100%; max-width: 360px;
      box-shadow: 0 2px 16px rgba(0,0,0,0.10);
    }
    h1 { font-size: 20px; font-weight: 600; margin: 0 0 28px; color: #1a1a18; text-align: center; }
    label { display: block; font-size: 13px; color: #555; margin-bottom: 5px; }
    input[type=text], input[type=password] {
      width: 100%; padding: 11px 14px; border: 1px solid #ddd;
      border-radius: 8px; font-size: 15px; margin-bottom: 18px;
      outline: none; transition: border-color .15s;
    }
    input:focus { border-color: #378ADD; }
    button {
      width: 100%; padding: 13px; background: #378ADD; color: #fff;
      border: none; border-radius: 8px; font-size: 16px;
      font-weight: 500; cursor: pointer;
    }
    button:hover { background: #2a6db5; }
    .error {
      background: #fdecea; color: #b00020; border-radius: 8px;
      padding: 10px 14px; font-size: 13px; margin-bottom: 18px;
    }
  </style>
</head>
<body>
  <div class="card">
    <h1>🏠 Home Inventory</h1>
    {% if error %}
      <div class="error">{{ error }}</div>
    {% endif %}
    <form method="post">
      <label for="username">Username</label>
      <input id="username" name="username" type="text" autocomplete="username"
             required autofocus value="{{ username or '' }}"/>
      <label for="password">Password</label>
      <input id="password" name="password" type="password" autocomplete="current-password" required/>
      <button type="submit">Sign in</button>
    </form>
  </div>
</body>
</html>
"""


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    from flask_login import current_user
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    error = None
    submitted_username = ''

    if request.method == 'POST':
        submitted_username = (request.form.get('username') or '').strip()
        password           = (request.form.get('password') or '')

        db  = get_db()
        row = User.get_by_username(submitted_username, db)

        if row and check_password_hash(row['password_hash'], password):
            user = User(row['id'], row['username'])
            login_user(user, remember=True)
            # Redirect to the page they were trying to reach, or home
            next_page = request.args.get('next') or url_for('index')
            return redirect(next_page)
        else:
            error = 'Incorrect username or password.'

    return render_template_string(_LOGIN_TEMPLATE, error=error, username=submitted_username)


@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('auth.login'))


# ── CLI: create-user ──────────────────────────────────────────────────────────

@click.command('create-user')
@click.argument('username')
@click.password_option(help='Password for the new user (will prompt if omitted).')
def create_user_command(username, password):
    """
    Create or update a user in the inventory database.

    Usage:
        flask create-user alice
        flask create-user alice --password secret123
    """
    from flask import current_app
    from inventory.db import get_db as _get_db

    with current_app.app_context():
        db   = _get_db()
        hash_ = generate_password_hash(password)

        existing = db.execute(
            'SELECT id FROM user WHERE username = ?', (username,)
        ).fetchone()

        if existing:
            db.execute(
                'UPDATE user SET password_hash = ? WHERE username = ?',
                (hash_, username)
            )
            db.commit()
            click.echo(f"Password updated for user '{username}'.")
        else:
            db.execute(
                'INSERT INTO user (username, password_hash) VALUES (?, ?)',
                (username, hash_)
            )
            db.commit()
            click.echo(f"User '{username}' created successfully.")
