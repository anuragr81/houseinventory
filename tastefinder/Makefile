# Run from the tastefinder/ directory. Every target's steps have been
# executed against a fresh checkout -- see README.md's setup section for the
# reasoning behind anything non-obvious here (particularly the pip upgrade
# below).

.PHONY: setup test lint run-server run-client regen-client migrate

setup:
	python3 -m venv server/.venv
	# server/pyproject.toml declares its dev dependencies as a PEP 735
	# dependency-group, which needs pip >= 25.1. A bare `python3 -m venv`
	# bootstraps whatever pip ships with the system's Python -- verified
	# on this machine to be 24.3.1, which predates --group support and
	# fails outright. Upgrading first is not optional.
	server/.venv/bin/pip install --upgrade pip
	server/.venv/bin/pip install -e ./server
	server/.venv/bin/pip install --group server/pyproject.toml:dev
	cd client && flutter pub get

test:
	cd server && .venv/bin/pytest
	cd client && flutter test

lint:
	cd server && .venv/bin/ruff check .
	cd server && .venv/bin/mypy app tests
	cd client && flutter analyze

run-server:
	cd server && .venv/bin/uvicorn app.main:app --reload --port 8000

run-client:
	cd client && flutter run

regen-client:
	./scripts/regen_client.sh

migrate:
	# Needs DATABASE_URL, via the environment or server/.env -- see
	# server/.env.example. There is no default: a migration silently
	# applied to the wrong database is worse than one that refuses to run.
	cd server && .venv/bin/alembic upgrade head
