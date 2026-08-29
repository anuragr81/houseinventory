# CLAUDE.md — Project Context

Read this before doing anything in this repository.

## What this project is

A preference-aggregation platform for narrow interest communities (wine-lovers,
mountain-bikers, runners, cricketers). Members rate real-world venues on a
schema the platform owns; the product is the **aggregate, taste-weighted signal**
for a community, never individual profiles.

It is not a review site, not a venue directory, and not a Google Maps competitor.
Google Places is used as a live lookup service only. See `docs/01_STACK_DECISIONS.md`.

## Repository layout

```
/server     Python + FastAPI. Owns the domain model, aggregation, and privacy gate.
/client     Flutter. Android-first, but must build for iOS/web/desktop unchanged.
/docs       Specifications. Read before implementing; update when reality diverges.
```

## The one rule that overrides everything

**Identified per-person data is transient. Aggregates are what persist.**

A `RawContribution` carries an identifiable person's rating. It is folded into a
`CommunityAggregate` and then purged. Nothing in this system may retain, index,
log, or expose a queryable history of what a specific person rated.

If a change you are about to make would make it possible to reconstruct one
person's rating history, **stop and raise it** rather than implementing it.
`docs/04_PRIVACY_INVARIANTS.md` lists these rules with their tests. Those tests
are not optional and must not be weakened, skipped, or marked xfail to get a
build green. If an invariant test fails, the code is wrong, not the test.

## Working conventions

- **Specs lead code.** If an implementation needs to diverge from `docs/`, change
  the doc in the same commit and say why in the message.
- **Type everything.** Server uses Pydantic models and full type hints; client
  uses sound null safety. The typed contract is what keeps the two ends aligned.
- **The API contract is generated, not hand-copied.** The Dart client models are
  generated from the server's OpenAPI schema. Never hand-write a client model
  that duplicates a server model.
- **No secrets in the repo.** API keys via environment variables only. There must
  be no Google API key, OAuth client secret, or database credential in any
  committed file, including test fixtures and example configs.
- **Small commits, conventional messages.** `feat:`, `fix:`, `docs:`, `test:`,
  `chore:`.

## Testing expectations

- Server: `pytest`. Domain logic and every privacy invariant must be unit-tested.
  Aggregation and suppression logic need property-based tests (Hypothesis), not
  just examples — the failure modes here are edge cases at small cohort sizes.
- Client: `flutter test` for widget and unit tests.
- A phase is not complete until its tests pass. Report failures; do not work
  around them.

## What to ask about rather than decide

- Anything that changes what data is persisted or for how long.
- Anything that would expose an aggregate below the cohort threshold.
- Adding a dependency that processes personal data (analytics, crash reporting,
  ad SDKs). Default answer is no.
- Choice of privacy mechanism parameters (thresholds, epsilon). These are not
  engineering defaults to guess — they are open decisions flagged in the report.
- Any bot/Sybil-resistance mechanism (device attestation, invitation chains,
  rate limiting). Deliberately deferred — see `docs/01_STACK_DECISIONS.md` and
  `OPEN-6` in `docs/04_PRIVACY_INVARIANTS.md`. Do not add phone-number
  verification as a substitute; it was considered and rejected (identifying,
  weakly effective, and the UK specifically has no mandatory SIM registration
  for it to piggyback on).
