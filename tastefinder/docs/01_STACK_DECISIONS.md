# 01 — Stack Decisions

Recorded so that neither a future agent nor a future human re-opens a settled
question without knowing why it was settled. If you want to change one of these,
that is fine — but read the rationale first and say which part you disagree with.

## Client: Flutter

**Chosen.** One codebase targeting Android (primary), iOS, web, and desktop.

Rationale: the app is form-, list-, and search-heavy with a map view. Flutter
renders its own widgets, which gives consistent behaviour across targets and a
mature widget set for exactly this kind of UI. For a new product with no existing
mobile codebase and a single small team targeting several platforms, it is the
default recommendation in the current landscape.

Sequencing: Android ships first; iOS support is architectural from day one
(`flutter create` enables both targets in Phase 4) but iOS *builds* are deferred
until Mac/CI access exists. This is a build-schedule decision, not a code-path
split — see "Keeping iOS free" below.

### Rejected: Unity

Unity was considered because of its cross-platform reach. It is the wrong tool
here and should not be revisited without new reasons:

- It is a real-time rendering engine. Its cross-platform strength is a scene
  graph, not native UI composition.
- Text input, form controls, scrolling lists, and accessibility are weak — and
  this app is almost entirely those things.
- Binary size and startup cost are disproportionate for a CRUD application.
- Integrating platform SDKs (Places, OAuth) means writing native plugins anyway,
  which forfeits the reason for choosing it.

"Cross-platform" was the right instinct; Unity was the wrong instantiation of it.

### Also considered

- **Kotlin Multiplatform** — the strongest alternative. Better where you have an
  existing native Android team and want to share only business logic while
  keeping native UI. That is not this project: there is no existing native
  codebase and no appetite to staff both Android and iOS UI specialists.
- **React Native** — reasonable, and the pick if the team were already deep in
  React/TypeScript. It is not.

### Keeping iOS free while shipping Android first

Deferring the iOS *build* must never mean writing anything Android-specific.
Concretely:

- Do not introduce `Platform.isAndroid` branches for convenience. If a plugin or
  feature needs one, flag it rather than silently shipping an Android-only path.
- Before adopting any plugin, confirm it declares iOS support, even though iOS
  won't be built yet — a plugin picked without checking can quietly become a
  porting problem later instead of a non-issue now.
- Run `flutter analyze` and (once available) a CI job doing
  `flutter build ios --no-codesign` on a macOS runner as a standing check, even
  before anyone has a Mac to fully build and sign on. The goal is that iOS
  readiness is a continuously-true fact, not a future project.

## Server: Python + FastAPI

**Chosen.**

Rationale:

- Matches existing working practice, so the server is maintainable by the person
  who owns the project rather than only by an agent.
- Pydantic gives a typed domain model that maps almost directly onto the UML in
  the design report, and produces an OpenAPI schema for free.
- That schema generates the Dart client models, so client and server cannot
  silently drift — the contract is one artefact, not two.

Flask experience transfers; FastAPI is preferred here specifically for the typed
schema and generated contract, which matter more than usual in this project
because the domain model is doing legal work as well as functional work.

## Persistence: SQL, provider-agnostic

SQLAlchemy + Alembic. SQLite for local development and tests, PostgreSQL in any
deployed environment. No provider-specific features in the schema.

The data volume here is small — aggregates, not raw contributions — so the
constraint on the database is correctness and auditability, not scale.

## Venue lookup: behind an interface, always

`VenueLookupService` is an interface with a Google Places implementation. This is
not gold-plating. The design report's core architectural principle is that Google
must remain swappable, and an interface is how that principle is enforced in code
rather than merely asserted in a document.

**The test:** deleting the Google implementation must break exactly one file. If
it would break more, the abstraction has leaked and should be repaired.

The same applies to `GoogleImportConnector` when the import channel is built.

## Bot / Sybil resistance: deferred, direction chosen

**Not implemented at bootstrap.** Recorded here so the reasoning survives to
whenever it is picked up (see `OPEN-6` in `docs/04_PRIVACY_INVARIANTS.md`).

**Rejected: phone-number (SMS OTP) verification as a signup gate.** The
reasoning was that SIM issuance implies identity verification, so a verified
phone number is a cheap bot-resistance proxy. Two problems killed it:

- *Factually weak in the launch market.* The UK is one of a small set of
  countries (with the US and Czech Republic) that deliberately does not mandate
  prepaid SIM registration — anonymous PAYG SIMs are legally sold with no ID.
  The verification the argument depends on doesn't exist here. Even where
  registration is mandatory elsewhere, commodity SMS-receiving services resell
  one-time verifications cheaply, so the defence is weaker everywhere than it
  looks.
- *Architecturally disproportionate.* `User` is deliberately pseudonymous, with
  no directly identifying fields. A phone number is a strong, stable,
  real-world identifier — adding one to every account would be the largest
  privacy regression available in this design, permanently, in exchange for a
  weak defence. Hashing does not fix this: the space of valid phone numbers is
  small enough to brute-force, so a hash is a reversible pseudonym, not
  anonymisation.

**Chosen direction: device attestation** (Play Integrity on Android, App Attest
on iOS, when that build exists). Verifies the request comes from a genuine app
on a genuine device, without collecting any personal identifier. Fits the
pseudonymous `User` model without compromising it.

**The actual threat model to design against:** not generic bot signups, but a
*Sybil attack on a specific aggregate* — a venue or business creating enough
fake accounts in one community to manufacture a favourable published verdict.
Note the interaction with `min_cohort_threshold`: the number that makes a slice
safe to publish also tells an attacker exactly how many accounts they need, so
this is not a generic "add more bot defence" problem — it is specific to how
aggregation and publication work in this system. Complementary directions,
roughly in priority order:

1. Device attestation (above).
2. A vouching/invitation chain leveraging the founder/joiner structure that
   already exists for cold-start — Sybil resistance grounded in a social graph
   rather than an identifier.
3. Rate-limiting and anomaly detection on contribution patterns (e.g. a cluster
   of new accounts rating one venue in a short window).
4. Weighting contributions by account tenure/history, making a manufactured
   verdict expensive in time rather than money.

If phone verification is reconsidered later for a narrow, high-trust action
(e.g. founder enrolment only), that is a materially different and more
defensible proposal than a blanket signup gate — but do not default to it.

## Deployment topology

Settled at design time; revisit only if a constraint below changes.

**Where each piece runs.** These never share a machine:

| Piece | Runs on |
|---|---|
| Flutter SDK, Dart, Android SDK, emulator | Developer machine only — a build toolchain, never deployed |
| FastAPI server + MySQL | PythonAnywhere (EU region) |
| Compiled `.aab` / `.apk` | Google Play Store → users' phones |

**Server host: PythonAnywhere, EU system** (`username.eu.pythonanywhere.com`).
EU rather than US deliberately — keeps personal data within the UK/EU regime and
avoids bringing international-transfer rules into scope, which matters given the
data-protection analysis this project is built around.

Two caveats to carry forward, both from PythonAnywhere's own documentation:

- ASGI hosting there is **still marked experimental**. No static file mappings
  (irrelevant — this server is a JSON API), a minimal web UI so management is
  CLI-driven via the `pa` tool, and no guarantee the CLI/API syntax stays stable.
  Deployment scripting should therefore be thin and easy to redo.
- Long-term ASGI pricing is not yet settled by the vendor.

Because of both, **do not couple the application to this host.** Keep the server
a plain ASGI app runnable by any ASGI server. If the host ever needs changing,
that must be a deployment concern only, touching no application code.

**Database: MySQL** (revised — was PostgreSQL).

The original choice was Postgres, because PythonAnywhere gives each account its
own Postgres server in a container, where their MySQL is multi-tenanted. That
isolation argument still stands and is the thing being traded away here. What
changed is the price of it: Postgres on PythonAnywhere requires a paid plan and
enabling the add-on, while MySQL was already provisioned on the account this
deploys to. Taking the smaller isolation boundary — a shared server with
per-account database and user permissions, rather than a separate container —
was judged an acceptable trade for not upgrading the plan.

Recorded as a decision rather than a drift, which is what the previous version
of this paragraph asked for. Postgres remains supported: nothing in the schema
uses a Postgres-specific feature (no JSONB, no arrays, and enums are
deliberately `native_enum=False`), and the `postgres` extra is still declared.

**What this cost, concretely.** "Provider-agnostic schema" is a claim, and
testing it found three real dialect divergences that no amount of reading
would have:

- MySQL's `DATETIME` carries no timezone, and `timezone=True` is accepted and
  ignored by the dialect. The `UtcDateTime` type decorator, originally written
  because SQLite silently returned naive datetimes, now normalises for MySQL
  too. A non-UTC input round-tripping to the same instant is tested on every
  dialect, because that is the case that distinguishes a real conversion from
  one that happens to work on UTC test data.
- **MySQL ignored `CHECK` constraints entirely before 8.0.16.** The schema has
  one (`cohort_size >= 0`). MySQL 8.4 enforces it, verified; a 5.7 server would
  not, silently. The same rule is therefore *also* enforced on the Pydantic
  model, because an integrity rule only some dialects keep is not an integrity
  rule. **Check the server version before deploying** — PythonAnywhere accounts
  are not all on MySQL 8, and migrating is a support request, not a setting.
- The initial migration's `downgrade` could not run on MySQL at all: Alembic
  generated a `DROP INDEX` for each index before its table, and MySQL refuses
  to drop an index still backing a foreign key (error 1553). Fixed by dropping
  the tables directly, which removes their indexes anyway.

**The suite runs against every dialect this project claims to support.** That,
rather than an abstraction layer over SQLAlchemy, is the portability
insurance: SQLAlchemy is already the adapter, and the repositories already
return domain models rather than ORM rows, so the swap surface is confined to
`app/persistence/`. What was missing was not indirection but evidence.

**Client/server coupling** is exactly one value: the API base URL.
`http://10.0.2.2:8000` from the Android emulator during development (that address
is the emulator's alias for the host machine's localhost), the deployed HTTPS URL
in release builds. This must be configurable, never a hardcoded literal.

## Deliberately not chosen yet
- ~~**Auth provider.**~~ **Now settled — see `docs/05_AUTH_DESIGN.md`.** Google
  OAuth for sign-in; the server issues its own bearer session token afterwards.
  The Google `sub` is stored only as an HMAC keyed by a server-held pepper, in
  a separate `identity_link` table, so `User` stays pseudonymous and a database
  leak yields no Google account identifiers. Still unbuilt.
- **Privacy mechanism.** Threshold suppression vs. differential privacy is open.
  The `PrivacyGate` interface exists; the mechanism behind it does not. Do not
  pick parameters to make something runnable.
- **Bot/Sybil resistance mechanism.** Direction chosen (device attestation);
  not implemented. See above.

## Explicitly excluded dependencies

No analytics SDK, no crash-reporting SDK, no advertising SDK, no session-replay
tooling. Each would process personal data on the client and would need its own
lawful-basis and transparency analysis. If observability is needed, raise it as a
question — the answer may be yes, but it is not a default.
