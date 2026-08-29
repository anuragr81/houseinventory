# START HERE

**You are Claude Code. This is your orientation document. Read it fully before
touching anything.**

## Current state of this repository

There is **no application code yet**. This repository currently contains
specifications only. You are being asked to build the first code that will exist
here.

That is deliberate. The specifications were written before the code because this
project has legal and privacy constraints that must shape the implementation
rather than be retrofitted onto it. Treat the documents as binding, not as
background reading.

## What this project is, in one paragraph

A preference-aggregation platform for narrow interest communities (wine-lovers,
mountain-bikers, runners, cricketers). Members rate real-world venues on a schema
the platform owns. The product is the **aggregate, taste-weighted signal** for a
community — never an individual's profile or history. Individual contributions
are processed briefly and destroyed; aggregates are what persist. Google Places
is used as a live venue-lookup service only, behind an interface, and is never
the source of truth for anything.

## What is in this bundle

Read in this order. Do not skip ahead to implementation.

| Order | File | What it gives you |
|---|---|---|
| 1 | `START_HERE.md` | This file. Orientation and current targets. |
| 2 | `CLAUDE.md` | Standing project context and working conventions. Auto-loaded every session. |
| 3 | `docs/00_BOOTSTRAP.md` | **Your actual task list.** Six phases, each ending in a gate where you stop and report. |
| 4 | `docs/01_STACK_DECISIONS.md` | What was chosen and rejected, with reasons. Read before proposing any stack change. |
| 5 | `docs/02_DOMAIN_MODEL.md` | Entities, enums, relationships, field names. The implementation contract. |
| 6 | `docs/03_API_CONTRACT.md` | The HTTP surface. Only `/health` is in scope right now. |
| 7 | `docs/04_PRIVACY_INVARIANTS.md` | Non-negotiable rules as testable assertions. The most important file here. |

There is also a design report (`community-taste-platform-report.pdf`, held
outside this repo) that explains *why* the model has this shape, with the legal
analysis and full source citations. You do not need it to implement, but the docs
reference its section numbers where the reasoning matters.

## Your targets at this stage

The goal right now is **a correct skeleton, not a working product.** Specifically,
by the end of Phase 5 you should have produced:

1. A FastAPI server that starts, exposes `GET /health`, and nothing else.
2. The full domain model as typed Pydantic models plus SQLAlchemy tables, with a
   working Alembic migration.
3. A `PrivacyGate` and `StreamingAggregator` whose behaviour is pinned by tests
   derived from `docs/04_PRIVACY_INVARIANTS.md` — one test per invariant, each
   carrying the invariant ID in its name.
4. A Flutter client that builds for Android, calls `GET /health`, and displays
   the result.
5. Dart API models **generated** from the server's OpenAPI schema, with a
   one-command regeneration target.
6. A Makefile and CI config such that a fresh clone can reach passing tests using
   only the README.

That is the whole target. No features beyond this.

## What success looks like

- `pytest` passes, including every privacy-invariant test.
- `ruff check` and `mypy` are clean.
- `flutter analyze` and `flutter test` are clean.
- The Android app talks to a locally running server.
- Every phase gate was reported and reviewed before the next began.

## What is explicitly NOT a target yet

Do not build these. They are omissions by design, each needing its own
specification pass first:

- Google Places integration (venue lookup)
- Google Data Portability import (the founder seeding flow)
- The normalisation adapter
- Authentication, sessions, or any user identity beyond a pseudonymous UUID
- Per-community facet content (the mechanism yes, the actual wine/cricket facet
  sets no)
- Any business-facing aggregate query API
- Bot / Sybil resistance — direction chosen (device attestation), not built
- Deployment automation

If you find yourself wanting to build one of these because it would make
something else easier to test, stop and say so instead.

## How to work

`docs/00_BOOTSTRAP.md` defines six phases. Each ends in a **GATE**. At a gate you:

1. Run the stated checks.
2. Report what you did, what versions you pinned, and anything that surprised you.
3. **Stop.** Wait for review. Do not continue unprompted.

The gates exist because two decisions in particular need a human eye before they
harden: how `RawContribution` is persisted (Gate 2), and the mapping from
invariants to tests (Gate 3).

If a phase cannot be completed as written — a missing tool, a version conflict,
an ambiguous instruction — stop and say so. Do not improvise a substitute and
carry on silently.

## The single rule that overrides everything else

**Identified per-person data is transient. Aggregates are what persist.**

Nothing in this system may retain, index, log, or expose a queryable history of
what a specific person rated. If a change you are about to make would make it
possible to reconstruct one person's rating history, stop and raise it.

The invariant tests are not optional and must not be weakened, skipped, or marked
`xfail` to get a build green. **If an invariant test fails, the code is wrong,
not the test.**

## Environment notes

- **Flutter runs on the development machine only.** It is a build toolchain that
  compiles Dart into an Android binary. Nothing Flutter-related is ever deployed
  to the server. Do not add Flutter or Dart to any server-side config, container,
  or deployment script.
- **The server is a separate deployment** (see `docs/01_STACK_DECISIONS.md` for
  the current target). During all bootstrap phases the server runs locally on
  `localhost:8000` and the Android emulator reaches it at `http://10.0.2.2:8000`.
- **The API base URL is the only coupling between client and server.** It must be
  configurable — build-time or runtime config, not a hardcoded literal — so that
  switching between local and deployed requires no code change.

## First action

Read `CLAUDE.md`, then `docs/00_BOOTSTRAP.md`, then execute **Phase 0** only.
Phase 0 creates nothing; it surveys the environment and reports.

Stop at the Phase 0 gate.
