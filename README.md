# Home Inventory App

A private home inventory system. Runs entirely locally — no cloud, no public server.

## Structure

```
inventory_app/
├── flask_app.py              ← app entry point
├── requirements.txt
├── .flaskenv                 ← local dev config
├── .gitignore
├── inventory/
│   ├── __init__.py           ← Blueprint definition
│   ├── db.py                 ← database connection + XML loader
│   ├── models.py             ← query functions
│   ├── routes.py             ← Flask routes
│   ├── schema.sql            ← table definitions
│   ├── seed.sql              ← category hierarchy
│   ├── config/
│   │   ├── house.xml         ← your house layout (edit this)
│   │   └── house.xsd         ← schema that validates house.xml
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

## Defining your house layout

Edit `inventory/config/house.xml` to describe your rooms, furniture, and shelves before running `flask init-inventory-db`. The hierarchy is three levels deep:

```xml
<house>
  <room code="LIV" name="Living room">
    <furniture code="LIV-CB" name="Cupboard">
      <shelf code="LIV-CB-S1" name="Top shelf"/>
      <shelf code="LIV-CB-S2" name="Bottom shelf"/>
    </furniture>
  </room>
  <room code="GAR" name="Garage"/>   <!-- room with no furniture is fine -->
</house>
```

Rules enforced by `house.xsd`:
- Every `room`, `furniture`, and `shelf` element must have a `code` and a `name` attribute.
- Codes must be unique across the entire file.
- Nesting must follow `room → furniture → shelf` exactly (no deeper).

`flask init-inventory-db` validates the XML against the schema before writing anything to the database, so a malformed file will produce a clear error rather than bad data.

## Setup

```bash
pip install -r requirements.txt
# Edit inventory/config/house.xml to match your actual house, then:
flask init-inventory-db
flask create-user <username>    # prompts for a password
flask run --debug
```

Alternatively you can launch the app directly with Python:

```bash
python flask_app.py
```

Both methods start the server at `http://127.0.0.1:5000`. `flask run` is preferred for development because it supports auto-reload on code changes (`--debug` flag); `python flask_app.py` is handy if you don't want to set the `FLASK_APP` environment variable.

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

## Clearing the inventory

To wipe all boxes, items, and locations, then reload locations fresh from `house.xml`:

```bash
flask clear-inventory
```

You will be prompted to confirm before anything is deleted. Users are preserved — you do not need to run `flask create-user` again unless you also deleted `inventory.db` manually.

## Tests

```bash
pytest
```

All tests run against an in-memory database — `inventory.db` is never touched.
