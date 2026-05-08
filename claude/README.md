# Home Inventory App

A private home inventory system. Runs entirely locally — no cloud, no public server.

## Structure

```
inventory_app/
├── flask_app.py              ← app entry point
├── requirements.txt
├── .flaskenv                 ← local dev config
├── .gitignore
├── manage_locations.py       ← define your house layout (run once)
├── inventory/
│   ├── __init__.py           ← Blueprint definition
│   ├── db.py                 ← database connection
│   ├── models.py             ← query functions
│   ├── routes.py             ← Flask routes
│   ├── schema.sql            ← table definitions
│   ├── seed.sql              ← category hierarchy
│   └── templates/inventory/
│       ├── find.html         ← retriever UI
│       └── update.html       ← updater UI
└── tests/
    ├── conftest.py
    ├── test_db.py
    ├── test_models.py
    ├── test_routes.py
    └── test_coordinates.py
```

## Setup

```bash
pip install -r requirements.txt
flask init-inventory-db
python manage_locations.py    # define your house layout first
flask run --debug
```

## Access

```
http://127.0.0.1:5000/              ← home screen
http://127.0.0.1:5000/inventory/find    ← retriever
http://127.0.0.1:5000/inventory/update  ← updater
```

## On home WiFi (phone access)

```bash
flask run --debug --host=0.0.0.0
```

Then visit `http://<your-pc-ip>:5000` from any device on your network.
Find your PC's IP with `ipconfig` (Windows) or `ifconfig` (Mac/Linux).

## Tests

```bash
pytest
```

All tests run against an in-memory database — `inventory.db` is never touched.
