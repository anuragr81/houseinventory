# 00 — Bootstrap Instruction

**Audience:** Claude Code, running in the repository root.
**Goal:** Initialise a working server and client skeleton that compiles, runs,
and enforces the privacy invariants — with no business features yet.

## How to execute this

Work through the phases **in order**. Each phase ends with a **GATE**. At a gate:

1. Run the stated checks.
2. Report what you did, what you pinned, and anything that surprised you.
3. **Stop and wait for review.** Do not start the next phase unprompted.

If a phase cannot be completed as written — a tool is unavailable, a version
conflict, an instruction is ambiguous — stop and say so. Do not improvise a
substitute and continue silently.

---

## Phase 0 — Environment survey

Do not create anything yet. Establish what is actually available.

1. Report versions of: `python3`, `pip`, `flutter`, `dart`, `git`. If Flutter is
   absent, run `flutter doctor` if present, otherwise report it as missing and
   stop — the client cannot be scaffolded without it.
2. Confirm the repository is a git repo with a clean working tree.
3. Resolve the **current stable** versions of: Python (3.x), FastAPI, Pydantic,
   SQLAlchemy, Alembic, pytest, Hypothesis, and the Flutter/Dart SDK constraint.
   Do not rely on any version number written in these docs — there are none, by
   design. Record what you find.

**GATE 0.** Report the version table and confirm the tree is clean. Wait.

---

## Phase 1 — Repository skeleton

Create the directory structure and tooling config. No domain logic yet.

```
/server
  pyproject.toml          # deps, pytest config, ruff config
  app/
    __init__.py
    main.py               # FastAPI app factory, health endpoint only
    config.py             # env-driven settings (Pydantic Settings)
    domain/__init__.py    # empty for now
    api/__init__.py
    services/__init__.py
    persistence/__init__.py
  tests/
    __init__.py
    test_health.py
  .env.example            # documented keys, NO values
/client
  (created by `flutter create` in Phase 4)
/docs
  (already present — do not modify in this phase)
.gitignore
```

Requirements:

- `pyproject.toml` uses a modern build backend and declares dev dependencies
  (`pytest`, `hypothesis`, `ruff`, `mypy`) in a dev group.
- `config.py` reads every external dependency from the environment:
  `DATABASE_URL`, `GOOGLE_PLACES_API_KEY`, `GOOGLE_OAUTH_CLIENT_ID`,
  `GOOGLE_OAUTH_CLIENT_SECRET`. All must be absent-by-default and fail loudly
  if required and unset. **No defaults that embed real values.**
- `.env.example` lists the keys with empty or obviously-fake values.
- `.gitignore` covers Python, Flutter/Dart, IDE files, `.env`, and build output.
- `main.py` exposes `GET /health` returning `{"status": "ok"}` and nothing else.
- `test_health.py` asserts that endpoint returns 200.

**GATE 1.** `pytest` passes. `ruff check` is clean. Report the dependency list
you actually pinned. Wait.

---

## Phase 2 — Domain model

Implement `docs/02_DOMAIN_MODEL.md` as Pydantic models plus SQLAlchemy tables.
Read that document fully before starting.

Order of work:

1. **Enums** first (`domain/enums.py`) — they are referenced by everything else.
2. **Pydantic domain models** (`domain/models.py`) — the in-memory representation.
   Type every field. Use `Optional[...]` exactly where the spec says optional.
3. **Persistence tables** (`persistence/tables.py`) — SQLAlchemy models.

   Note the asymmetry, it is deliberate: `User`, `CommunityMembership`,
   `Community`, `Facet`, `ConsentRecord`, `GoogleImportJob`, `PlaceRef` and
   `CommunityAggregate` are persisted. **`RawContribution` is not a durable
   table.** Model it as a short-lived working row with a `folded_at` column and a
   hard deletion path, or as an in-flight object — but it must not accumulate.
   Whichever you choose, document the choice in `docs/02_DOMAIN_MODEL.md`.

4. **Alembic** initialised with one migration creating the persisted tables.

Constraints:

- `PublicAggregateView` exposes `cohort_size_bucket: str`, never the raw
  `cohort_size: int`. Do not add a "convenience" field that leaks the exact count.
- `RawContribution.foldInto()` and `.purge()` from the spec are behaviour, not
  ORM methods. Put them in `services/aggregation.py` in Phase 3 — keep the
  domain models as data.

**GATE 2.** Models import cleanly, `mypy` passes, migration applies to a scratch
SQLite DB and rolls back. Report the `RawContribution` persistence decision you
made and your reasoning. Wait — this one needs a human look.

---

## Phase 3 — Privacy gate and aggregation

This is the phase that matters most. Read `docs/04_PRIVACY_INVARIANTS.md` first
and treat it as the specification, not as guidance.

Implement:

- `services/aggregation.py` — `StreamingAggregator`: applies a `RawContribution`
  to the running `CommunityAggregate`, then triggers purge of the raw record.
  Aggregation must be incremental (updating running statistics), not a recompute
  over stored raw contributions — there are no stored raw contributions.
- `services/privacy_gate.py` — `PrivacyGate`:
  - `suppress_if_below_threshold(agg) -> Optional[CommunityAggregate]`
  - `apply_noise(agg) -> CommunityAggregate`

  For `apply_noise`, implement the **interface and a clearly-labelled no-op or
  placeholder**. Do not invent an epsilon or pick a noise distribution. The
  choice of mechanism is an open decision (see the report's Section 7.2 caveat).
  Make the placeholder fail loudly if it is ever enabled in a production config
  without parameters being set.
- `tests/test_privacy_invariants.py` — every invariant in `docs/04` as an
  executable test, with the invariant's ID in the test name.

Use Hypothesis for the threshold and aggregation logic. The dangerous cases are
cohorts of size 0, 1, exactly at threshold, and one-above-threshold.

**GATE 3.** All invariant tests pass. Report the test-to-invariant mapping so it
can be checked that none is missing. Wait.

---

## Phase 4 — Client scaffold

1. `flutter create` the client with an application ID you ask about rather than
   guess. Enable Android, iOS, web, and desktop targets — the point of this
   stack choice is that all of them build from day one, so verify they do.
2. Set up state management and routing. Prefer a small, well-established
   combination over anything exotic; state your choice and why at the gate.
3. **Generate** Dart models from the server's OpenAPI schema into
   `client/lib/api/generated/`. Add a `make regen-client` (or equivalent) target
   so regeneration is one command. Mark the directory as generated and excluded
   from manual edits.
4. Build a single screen that calls `GET /health` and displays the result. That
   is the whole feature set for this phase — it proves the wiring end to end.

Do **not** in this phase: add Google Places, add OAuth, add a map, or add any
analytics/crash-reporting SDK.

**GATE 4.** `flutter analyze` clean; `flutter test` passes; the app builds for
Android and at least one other target; the health screen works against a locally
running server. Report which targets you verified. Wait.

---

## Phase 5 — Developer ergonomics

- `Makefile` (or `justfile`) with: `setup`, `test`, `lint`, `run-server`,
  `run-client`, `regen-client`, `migrate`.
- CI config running server tests, client tests, and lint on push.
- `README.md` at repo root updated with real setup steps that you have actually
  executed — not aspirational ones.

**GATE 5.** A fresh clone can go from zero to passing tests using only the
README. Verify this by reasoning through it explicitly and flagging any step
that assumes state you happen to have locally.

---

## Out of scope for bootstrap

Do not start these without a separate instruction. They are listed so you know
they are deliberate omissions, not oversights:

- Google Places integration (venue lookup)
- Google Data Portability import (the founder seeding flow)
- The normalisation adapter
- Authentication and session management
- The per-community facet schemas
- Any business-facing aggregate query API
- Bot/Sybil resistance (device attestation etc.) — see `docs/01_STACK_DECISIONS.md`

Each of these has legal or privacy constraints attached in the design report and
needs its own specification pass before implementation.
