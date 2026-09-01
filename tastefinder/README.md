# Taste Platform

A preference-aggregation platform for narrow interest communities (wine-lovers,
mountain-bikers, runners, cricketers). Members rate real-world venues on a
schema the platform owns; the product is the **aggregate, taste-weighted
signal** for a community, never an individual's profile or history. See
`CLAUDE.md` for the project's working rules, and `docs/` for the full
specification.

```
/server     Python + FastAPI. Domain model, aggregation, privacy gate.
/client     Flutter. Android-first, also builds for Linux desktop and web.
/docs       Specifications. Read before implementing; update when reality diverges.
```

## Prerequisites

- **Python 3.13+** with `pip >= 25.1` obtainable (a fresh `python3 -m venv`
  typically bootstraps an older pip; `make setup` upgrades it for you — see
  the note in the `Makefile`).
- **Flutter** (stable channel; this project was scaffolded and CI-pinned
  against 3.47.2 — see `docs/00_BOOTSTRAP.md`, Phase 4) on your `PATH`.
- For building/running the Android target specifically: the Android SDK,
  with `cmdline-tools` installed (Android Studio's "Standard" setup may skip
  this component — check for `<sdk>/cmdline-tools/latest/bin/sdkmanager`) and
  licenses accepted. Not needed for `flutter analyze` / `flutter test`, only
  for `flutter build apk` / `flutter run -d <android-device>`.
- For `make regen-client` only: a Java runtime and
  [`openapi-generator-cli.jar`](https://repo1.maven.org/maven2/org/openapitools/openapi-generator-cli/)
  (set `OPENAPI_GENERATOR_JAR` to its path, or place it at
  `~/install/openapi-generator/openapi-generator-cli.jar`).

## Setup

```
make setup
```

Creates the server's virtualenv (`server/.venv`) with its dependencies —
including the dev tools, installed via `pyproject.toml`'s
`[dependency-groups] dev` — and runs `flutter pub get` for the client. Verified
against a clean checkout with none of the above already installed except
Python and Flutter themselves.

## Everyday commands

All run from this directory (`tastefinder/`):

| Command | What it does |
|---|---|
| `make test` | `pytest` (server, incl. every privacy invariant) + `flutter test` (client) |
| `make test-mysql` | The persistence suite against a real MySQL. Needs `TEST_MYSQL_URL` |
| `make lint` | `ruff check` + `mypy` (server) + `flutter analyze` (client) |
| `make run-server` | `uvicorn app.main:app --reload` on `localhost:8000` |
| `make run-client` | `flutter run` — picks a connected device/emulator, or pass e.g. `flutter run -d linux` directly from `client/` for a specific target |
| `make regen-client` | Regenerates `client/packages/tastefinder_api_client/` from the server's current OpenAPI schema. Requires the server's venv to exist (`make setup` first) |
| `make migrate` | `alembic upgrade head`. Requires `DATABASE_URL` — via the environment or `server/.env` (see `server/.env.example`); there is deliberately no default |

## Databases

SQLite for local development and tests; **MySQL** is the deployment target
(`docs/01_STACK_DECISIONS.md` records why it was chosen over Postgres, and what
that trade costs). Postgres remains supported — nothing in the schema uses a
dialect-specific feature.

Install the driver for whichever you deploy against:

```
pip install -e ".[mysql]"      # or ".[postgres]"
```

The persistence suite runs against **every dialect the project claims to
support**, because they disagree about things that look settled — SQLite
silently ignored foreign keys and dropped timezones, MySQL has no
timezone-aware `DATETIME`, and MySQL before 8.0.16 ignored `CHECK` constraints
outright. Each of those was found by running real SQL, not by reading
documentation.

To include MySQL locally, point `TEST_MYSQL_URL` at a throwaway server and run
`make test-mysql`. Unset, those cases skip and SQLite still runs in full. A
disposable one via Podman:

```
podman run -d --name tf-mysql --security-opt label=disable \
  --tmpfs /var/lib/mysql:rw,size=2g \
  -e MYSQL_ROOT_PASSWORD=devroot -e MYSQL_DATABASE=tastefinder \
  -p 13306:3306 docker.io/library/mysql:8.4
```

(`--tmpfs` puts the data directory in RAM: throwaway anyway, and it turns a
multi-minute InnoDB initialisation into seconds. `label=disable` is needed
where SELinux blocks the container's dynamic linker.)

> **Before deploying to MySQL, check the server version:** `SELECT VERSION();`.
> `CHECK` constraints are silently ignored before 8.0.16, and PythonAnywhere
> accounts are not all on MySQL 8 — migrating is a support request, not a
> setting.

Pointing the client at a local server instead of the deployed one:

```
flutter run --dart-define=API_BASE_URL=http://127.0.0.1:8000
```

(On the Android emulator, use `http://10.0.2.2:8000` instead of `127.0.0.1` —
that address is the emulator's alias for the host machine.)

## CI

`.github/workflows/tastefinder-ci.yml`, scoped to changes under `tastefinder/`
(this is one project inside a larger monorepo — see the root
`.code-workspace` file). Runs the same `pytest`/`ruff`/`mypy` and
`flutter analyze`/`flutter test` checks as `make test lint`, on every push and
PR touching this directory. The server job runs a MySQL 8.4 service container
so the persistence suite is exercised against the deployment dialect, not only
SQLite.

The Android SDK isn't installed on the CI runner, so `flutter build apk` isn't
exercised there — a real gap, not a deliberate one, worth revisiting.

## Documentation

| File | Purpose |
|---|---|
| `CLAUDE.md` | Project context and working rules, loaded automatically by Claude Code every session. |
| `docs/00_BOOTSTRAP.md` | The phased build plan this project was scaffolded from. All six phases complete — historical, not a task list. |
| `docs/01_STACK_DECISIONS.md` | What was chosen and rejected, with reasons. Read before proposing a stack change. |
| `docs/02_DOMAIN_MODEL.md` | Entities, enums, relationships — the implementation contract. |
| `docs/03_API_CONTRACT.md` | The HTTP surface. `[implemented]` marks what's real; the rest is specification for later phases. |
| `docs/04_PRIVACY_INVARIANTS.md` | Non-negotiable rules as testable assertions — the most important file here. |
| `docs/05_AUTH_DESIGN.md` | How sign-in will work: Google OAuth, pseudonymous accounts, HMAC'd identity link. Designed, unbuilt. |

## Status

The bootstrap (`docs/00_BOOTSTRAP.md`, six phases) is complete, and work has
continued past it.

**Built and tested:** the domain model, aggregation and privacy gate; the
persistence layer (repositories, transactions, an atomic founding write);
community founding as a service; the platform-owned facet catalogue; four
read-only routes (`/health`, `/facets`, `/communities`,
`/communities/{slug}`); and the Flutter client, which builds for Android,
Linux and web.

**Designed but not built:** authentication (`docs/05_AUTH_DESIGN.md`). This is
the immediate blocker — `POST /communities` needs only a session to identify
the founder; its decision logic and atomic write both already exist.

**Deliberately not started:** Google Places, the Google Data Portability
import, per-community facet *content* (the mechanism exists, the facets are
unset), bot/Sybil resistance, and any moderation or takedown channel.

Eight decisions in `docs/04_PRIVACY_INVARIANTS.md` are recorded as open
(`OPEN-1` through `OPEN-8`) rather than resolved with a guessed default. Two
constrain what can safely be published and are worth reading before building
anything that publishes: `OPEN-1` (the minimum cohort threshold, which has no
safe default) and `OPEN-7` (`cohort_size` counts contributions rather than
contributors, so one account can raise it alone — which matters more now that
founding is a solo act). **Nothing here is
legal advice**; the invariants are an engineering translation of a design
discussion, not a compliance sign-off, and need review by a UK
data-protection solicitor and a DPIA before any real user data is processed.

## For agents continuing this build

`START_HERE.md` and `docs/00_BOOTSTRAP.md` are the original phased
instructions this project was built from (each phase ends in a gate: run the
checks, report, stop for review — don't run phases unattended). They remain
the reference for *how this codebase came to look the way it does* and for
picking up any phase that isn't done yet.
