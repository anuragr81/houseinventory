# Run from the tastefinder/ directory. Every target's steps have been
# executed against a fresh checkout -- see README.md's setup section for the
# reasoning behind anything non-obvious here (particularly the pip upgrade
# below).

.PHONY: setup test test-mysql lint run-server run-client regen-client migrate

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

# The persistence suite runs against SQLite always, and against MySQL too when
# TEST_MYSQL_URL is set -- unset, those cases skip rather than fail. Dialects
# disagree about things that look settled (see docs/01_STACK_DECISIONS.md), so
# the dialect this deploys on is worth exercising before deploying on it.
#
# test_persistence_schema.py is included alongside test_persistence_repositories.py
# because it carries test_migration_round_trips_on_mysql -- the migration
# up/down/up cycle against MySQL. A migration whose SQLite rollback passes but
# whose MySQL rollback fails outright (error 1553, an index still backing a
# foreign key) has broken this twice already; that test is the guard, and it
# is only reachable if this target actually runs it.
test-mysql:
	cd server && TEST_MYSQL_URL="$${TEST_MYSQL_URL:?set TEST_MYSQL_URL, e.g. mysql+pymysql://root:pass@127.0.0.1:3306/tastefinder}" \
		.venv/bin/pytest tests/test_persistence_repositories.py tests/test_persistence_schema.py

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
