# START HERE

**You are Claude Code. This is your orientation document. Read it fully before
touching anything.**

## Current state of this repository

**The bootstrap is finished and the project is past it.** All six phases of
`docs/00_BOOTSTRAP.md` are complete, and work has continued beyond them. There
is a working server, a Flutter client, a persistence layer, CI, and a test
suite that pins every privacy invariant.

What exists, roughly newest first:

| Area | State |
|---|---|
| `GET /health`, `/facets`, `/communities`, `/communities/{slug}` | Built, tested, live |
| `GET /communities/{slug}/places/{place_id}/aggregate` | Built, tested, live -- first route through `PrivacyGate` |
| Authentication (`POST /auth/google`, Part 1 of `docs/05_AUTH_DESIGN.md`) | **Built**: Google ID-token verification, `identity_link`, server-issued bearer sessions |
| `POST /communities` (founding) | **Built**: wired to `get_current_user_id`; decision logic and atomic write both tested |
| Persistence layer | Built: repositories, transactions, atomic founding write |
| Domain model, aggregation, privacy gate | Built and tested |
| Facet catalogue | Built; **no content** — the platform's actual facet list is unset |
| Cohort bucketing | Built; **no boundaries configured** — `COHORT_BUCKETING_BOUNDARIES` is the owner's to set |
| Flutter client | Scaffolded, builds for Android/Linux/web, calls `/health` |
| Databases | SQLite locally and in tests; **MySQL** deployed. Suite runs against both |
| Google Places, Google import, Sybil resistance, moderation | Not started, deliberately |

**The single most useful thing to know:** the writable API is unblocked now.
A client can sign in with Google, get a bearer session, and found a
community, end to end. What is missing is product content the owner
supplies, not more code: the facet catalogue is empty
(`FACET_CATALOGUE_PATH`), cohort bucket boundaries are unset
(`COHORT_BUCKETING_BOUNDARIES`), and `min_cohort_threshold` per community has
no safe default (`OPEN-1`). `GET /communities/{slug}/aggregates?bbox=...`
(the list variant) is the one documented route still unbuilt; it needs a new
`AggregateRepository` method the single-aggregate route does not.

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
| 3 | `docs/00_BOOTSTRAP.md` | How the codebase came to look like this. Six phases, all complete. Historical now, not a task list. |
| 4 | `docs/01_STACK_DECISIONS.md` | What was chosen and rejected, with reasons. Read before proposing any stack change. |
| 5 | `docs/02_DOMAIN_MODEL.md` | Entities, enums, relationships, field names. The implementation contract. |
| 6 | `docs/03_API_CONTRACT.md` | The HTTP surface. `[implemented]` marks what is real; the rest is still specification. |
| 7 | `docs/04_PRIVACY_INVARIANTS.md` | Non-negotiable rules as testable assertions. The most important file here. |
| 8 | `docs/05_AUTH_DESIGN.md` | How sign-in will work. Designed, unbuilt — and the next thing to build. |

There is also a design report (`community-taste-platform-report.pdf`, held
outside this repo) that explains *why* the model has this shape, with the legal
analysis and full source citations. You do not need it to implement, but the docs
reference its section numbers where the reasoning matters.

## Where to pick up

There is no single prescribed next task any more — the phased plan is done,
and so is the authentication work that used to head this list (Part 1 of
`docs/05_AUTH_DESIGN.md`, plus wiring `POST /communities` to it). The
candidates now:

1. **Set the product-content values nothing has a safe default for.** The
   facet catalogue (`FACET_CATALOGUE_PATH`) is empty, cohort bucket
   boundaries (`COHORT_BUCKETING_BOUNDARIES`) are unset, and
   `min_cohort_threshold` has no default per community (`OPEN-1`). None of
   these are implementation tasks — each is deliberately un-guessable, and
   each is the owner's to supply.
2. **Resolve an `OPEN-` item.** `OPEN-1` (cohort threshold) and `OPEN-7`
   (`cohort_size` counts contributions, not contributors) are the two that
   most constrain what can safely be published. `OPEN-6` (Sybil resistance)
   now matters more than it did: a valid session proves an account, not a
   person, and solo founding means nothing else in the platform structurally
   requires more than one.
3. **Build `GET /communities/{slug}/aggregates?bbox=...`**, the list variant
   of the aggregate route. It needs a new `AggregateRepository` method the
   single-aggregate route (`GET /communities/{slug}/places/{place_id}/aggregate`)
   does not.
4. **Wire `POST /communities/{slug}/membership`** (join a community) and
   `POST /communities/{slug}/contributions` (rate a venue) — both specified
   in `docs/03_API_CONTRACT.md`, neither built. `get_current_user_id`
   (`app/api/deps.py`) is ready for either to use.

## What success looks like

- `pytest` passes, including every privacy-invariant test, and the meta-test
  confirming every documented invariant *has* a test.
- `ruff check` and `mypy` are clean.
- `flutter analyze` and `flutter test` are clean.
- The persistence suite passes against **both** SQLite and MySQL
  (`make test-mysql`) -- dialects disagree, and each disagreement so far was
  found by running real SQL rather than by reading documentation.
- Anything that diverges from `docs/` changed the doc in the same commit.

## What is explicitly NOT a target yet

Do not build these. They are omissions by design, each needing its own
specification pass first:

- Google Places integration (venue lookup)
- Google Data Portability import (the founder seeding flow)
- The normalisation adapter
- Per-community facet content (the mechanism yes, the actual wine/cricket facet
  sets no)
- Any business-facing aggregate query API
- Bot / Sybil resistance — direction chosen (device attestation), not built
- Deployment automation

If you find yourself wanting to build one of these because it would make
something else easier to test, stop and say so instead.

## How to work

The phase gates are spent, but the habit they enforced is the reason this
codebase is worth trusting, and it still applies:

1. Run the checks — `make test`, `make lint`, and `make test-mysql` if the
   change touches persistence.
2. Report what you did and anything that surprised you. The surprises have
   consistently been the valuable part: SQLite silently ignoring foreign keys
   and dropping timezones, MySQL ignoring `CHECK` constraints before 8.0.16,
   Alembic generating a downgrade MySQL refuses to run. None of those were
   found by reading documentation.
3. **Stop and raise it** rather than improvising, when a decision is the
   owner's. `CLAUDE.md`'s "What to ask about rather than decide" list is not
   decoration — most of the good decisions in this project came from that
   pause.

**Verify claims rather than asserting them.** Where an invariant says something
must not exist, plant the thing and confirm the test fails; several tests in
this suite were written that way and one was found to be vacuous. Where a
route is meant to work, run a real server and hit it, not only a test client.

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
- **The server is a separate deployment** — PythonAnywhere, mounted under
  `/tastefinder` by the repository-root `wsgi.py`, alongside an unrelated Flask
  app. That file degrades gracefully: if the tastefinder dependencies are not
  importable it unmounts the whole thing rather than breaking the other app, so
  a missing dependency shows up as `/tastefinder/*` returning 404 rather than
  as an error. Locally the server runs on `localhost:8000`, and the Android
  emulator reaches it at `http://10.0.2.2:8000`.
- **The database is MySQL when deployed**, SQLite locally and in tests. The
  persistence suite runs against both; see `docs/01_STACK_DECISIONS.md` for why
  MySQL was chosen over Postgres and what that trade cost.
- **The API base URL is the only coupling between client and server.** It must be
  configurable — build-time or runtime config, not a hardcoded literal — so that
  switching between local and deployed requires no code change.

## First action

Read `CLAUDE.md`, then skim `docs/04_PRIVACY_INVARIANTS.md` -- it is the file
most likely to make you reject an otherwise reasonable design.

Then ask what to work on rather than assuming. The phased plan that used to
answer that question is finished; "Where to pick up" above lists candidates,
but several of them turn on decisions that are the owner's to make, not
yours.
