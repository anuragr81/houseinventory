"""
wsgi.py
-------
WSGI entry point for PythonAnywhere.

Mounts several independent Flask apps under one domain by URL prefix:

    research.anurags-econ.net/houseinventory/  -> flask_app.py       (inventory)
    research.anurags-econ.net/tastefinder/     -> tastefinder/flask_app.py

To deploy, point the PythonAnywhere WSGI configuration file at this module,
e.g. by replacing its contents with:

    import sys
    sys.path.insert(0, '/home/anuragr/houseinventory')
    from wsgi import application  # noqa

Each mounted app is loaded under a unique module name so that several
directories can each contain a top-level 'flask_app.py' without shadowing
one another in sys.modules.
"""

import importlib.util
import os
import sys

from werkzeug.middleware.dispatcher import DispatcherMiddleware

BASE = os.path.dirname(os.path.abspath(__file__))

# Project packages must be importable ('inventory', and whatever tastefinder
# grows into). Site-packages for a --user pip install on PythonAnywhere is
# already on sys.path in most configs; add it here if yours needs it.
for _path in (BASE, os.path.join(BASE, 'tastefinder')):
    if _path not in sys.path:
        sys.path.insert(0, _path)


def load_app(module_name, relative_path, attr='app'):
    """Import a Flask app from a file path under a unique module name."""
    path = os.path.join(BASE, relative_path)
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return getattr(module, attr)


def root(environ, start_response):
    """Landing response for the bare domain, which mounts no app of its own."""
    body = (
        b'<html><body style="font-family:-apple-system,sans-serif;'
        b'max-width:400px;margin:80px auto;text-align:center">'
        b'<h2>anurags-econ</h2>'
        b'<p><a href="/houseinventory/">Home Inventory</a></p>'
        b'</body></html>'
    )
    start_response('200 OK', [
        ('Content-Type', 'text/html; charset=utf-8'),
        ('Content-Length', str(len(body))),
    ])
    return [body]


MOUNTS = {
    '/houseinventory': load_app('houseinventory_app', 'flask_app.py'),
    # '/tastefinder': load_app('tastefinder_app', 'tastefinder/flask_app.py'),
}

application = DispatcherMiddleware(root, MOUNTS)
