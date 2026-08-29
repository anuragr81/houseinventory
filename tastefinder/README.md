# Community Taste-Preference Platform — Bootstrap Bundle

This bundle contains everything Claude Code needs to initialise the server and
client for the community taste-preference platform. It is **instructions and
specifications only** — no application code. Claude Code writes the code.

## What this is for

The design report (`community-taste-platform-report.pdf`) established a domain
model, a service architecture, and a set of legal/privacy constraints. This
bundle is the bridge between that document and an actual codebase: it restates
the model in a form an agent can implement against, and — critically — converts
the privacy constraints from prose into **enforceable invariants with tests**,
so the legal analysis binds the code rather than sitting alongside it.

## How to use it

1. Create an empty git repository and extract this bundle into its root.
2. Commit it as-is, before any code exists. This gives you a clean diff between
   "what we specified" and "what the agent built".
3. Open Claude Code in that directory and give it this prompt:

   ```
   Read START_HERE.md and follow its instructions.
   ```

   That document orients it, points it at the rest in the right order, and tells
   it to execute Phase 0 and stop.

4. Review at each phase gate. Do not let it run all phases unattended — the
   gates exist because Phase 2 and Phase 4 contain decisions you should see
   before they harden.

## Contents

| File | Purpose |
|---|---|
| `START_HERE.md` | Orientation for Claude Code — what exists, what the current targets are, what is out of scope. The first thing it should read. |
| `CLAUDE.md` | Persistent project context. Claude Code reads this automatically on every session. Keep it short and current. |
| `docs/00_BOOTSTRAP.md` | The phased initialisation instruction. This is the main deliverable. |
| `docs/01_STACK_DECISIONS.md` | What we chose, what we rejected, and why. Read this before proposing a stack change. |
| `docs/02_DOMAIN_MODEL.md` | Entities, enums, and relationships from the report's UML, in implementable form. |
| `docs/03_API_CONTRACT.md` | The HTTP surface between client and server. |
| `docs/04_PRIVACY_INVARIANTS.md` | Non-negotiable rules derived from the legal analysis, expressed as testable assertions. |

## A note on versions

This bundle deliberately does **not** pin framework or library versions. Any
version numbers written here in August 2026 would be stale by the time you run
this. `docs/00_BOOTSTRAP.md` instructs Claude Code to resolve current stable
versions at initialisation time and record what it actually pinned. Check that
record rather than trusting a number written in advance.

## Status

First-pass scaffolding specification. The domain model is derived from a design
report that is itself explicitly provisional — in particular the per-community
facet schema and the choice of privacy mechanism (threshold suppression vs.
differential privacy) are open. Expect to revise `docs/02_DOMAIN_MODEL.md` and
`docs/04_PRIVACY_INVARIANTS.md` once those are settled.

**Nothing here is legal advice.** The invariants in `docs/04` are an engineering
translation of a design discussion, not a compliance sign-off. They need review
by a UK data-protection solicitor and a DPIA before any real user data is
processed.
