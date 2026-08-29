"""
wsgi.py
-------
WSGI entry point for PythonAnywhere.

Mounts several independent apps under one domain by URL prefix:

    research.anurags-econ.net/                 -> landing page (below)
    research.anurags-econ.net/houseinventory/  -> flask_app.py            (Flask, WSGI)
    research.anurags-econ.net/tastefinder/     -> tastefinder/server      (FastAPI, ASGI)

To deploy, point the PythonAnywhere WSGI configuration file at this module,
e.g. by replacing its contents with:

    import sys
    sys.path.insert(0, '/home/anuragr/houseinventory')
    from wsgi import application  # noqa

Two things worth knowing before editing this file:

1. Flask apps are loaded under unique module names so that several directories
   can each hold a top-level 'flask_app.py' without shadowing one another in
   sys.modules.

2. The tastefinder server is a FastAPI app, which speaks ASGI, while
   DispatcherMiddleware speaks WSGI. a2wsgi's ASGIMiddleware bridges the two.
   The adapter lives here, at the deployment boundary, so the FastAPI app
   itself stays a plain ASGI app with no provider lock-in -- see
   tastefinder/docs/01_STACK_DECISIONS.md.
"""

import importlib.util
import os
import sys

from werkzeug.middleware.dispatcher import DispatcherMiddleware

BASE = os.path.dirname(os.path.abspath(__file__))

# Project packages must be importable: 'inventory' from the repo root, and the
# tastefinder server package from tastefinder/server. Site-packages for a --user
# pip install on PythonAnywhere is already on sys.path in most configs; add it
# here if yours needs it.
for _path in (BASE, os.path.join(BASE, 'tastefinder', 'server')):
    if _path not in sys.path:
        sys.path.insert(0, _path)


def load_app(module_name, relative_path, attr='app'):
    """Import a WSGI/Flask app from a file path under a unique module name."""
    path = os.path.join(BASE, relative_path)
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return getattr(module, attr)


def tastefinder_available():
    """Whether the tastefinder dependencies are importable, without building anything."""
    try:
        import a2wsgi  # noqa: F401

        import app.main  # noqa: F401
    except ImportError:
        return False
    return True


class LazyASGIApp:
    """WSGI callable that builds its ASGIMiddleware on first call, not at import time.

    uWSGI here runs in preforking mode: wsgi.py is fully imported once in the
    master process, which then fork()s the worker processes. asyncio event
    loops (and the epoll file descriptors they hold) do not survive fork()
    safely -- a worker that inherits an event loop built in the master can
    hang indefinitely on any request that touches it, including completely
    unrelated ones served by the same worker.

    Deferring construction to the first request made *in* a worker avoids
    this: each forked worker builds its own event loop after the fork, not
    before it.
    """

    def __init__(self):
        self._app = None

    def __call__(self, environ, start_response):
        if self._app is None:
            from a2wsgi import ASGIMiddleware

            from app.main import create_app
            self._app = ASGIMiddleware(create_app())
        return self._app(environ, start_response)


# ── Mounts ────────────────────────────────────────────────────────────────────

MOUNTS = {'/houseinventory': load_app('houseinventory_app', 'flask_app.py')}

if tastefinder_available():
    MOUNTS['/tastefinder'] = LazyASGIApp()


# ── Landing page ──────────────────────────────────────────────────────────────

APPS = [
    ('/houseinventory/', 'Home Inventory', 'Find and store household boxes'),
    ('/tastefinder/docs', 'Taste Platform', 'Community taste-preference API'),
]


def root(environ, start_response):
    """Landing page for the bare domain, which mounts no app of its own.

    This is also the dispatcher's fallback, so it must 404 on anything that is
    not the bare domain -- otherwise every unmatched path would answer 200 with
    the landing page.
    """
    if environ.get('PATH_INFO', '/') not in ('', '/'):
        body = b'<html><body><h1>404 Not Found</h1></body></html>'
        start_response('404 Not Found', [
            ('Content-Type', 'text/html; charset=utf-8'),
            ('Content-Length', str(len(body))),
        ])
        return [body]

    links = ''.join(
        f'<a href="{href}"><strong>{name}</strong><span>{desc}</span></a>'
        for href, name, desc in APPS
        # Only advertise what is actually mounted.
        if any(href.startswith(prefix) for prefix in MOUNTS)
    )
    body = f'''<html>
<head>
  <title>anurags-econ</title>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; }}
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
           max-width: 420px; margin: 80px auto; padding: 20px; color: #1a1a18; }}
    h2 {{ font-size: 20px; margin: 0 0 28px; }}
    a {{ display: block; padding: 16px; margin: 12px 0; border-radius: 10px;
        border: .5px solid #d4d3cf; text-decoration: none; color: inherit; }}
    a:hover {{ border-color: #378ADD; background: #E6F1FB; }}
    strong {{ display: block; font-size: 16px; font-weight: 600; }}
    span {{ display: block; font-size: 13px; color: #6b6b66; margin-top: 3px; }}
    @media (prefers-color-scheme: dark) {{
      body {{ background: #1a1a18; color: #f0ede6; }}
      a {{ border-color: #52524e; }}
      a:hover {{ border-color: #378ADD; background: #0d2a4a; }}
      span {{ color: #b0aea6; }}
    }}
  </style>
</head>
<body>
  <h2>anurags-econ</h2>
  {links}
</body>
</html>'''.encode()
    start_response('200 OK', [
        ('Content-Type', 'text/html; charset=utf-8'),
        ('Content-Length', str(len(body))),
    ])
    return [body]


application = DispatcherMiddleware(root, MOUNTS)
