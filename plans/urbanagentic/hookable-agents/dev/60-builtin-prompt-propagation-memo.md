# Implementation Memo: Built-in Prompt Propagation — Roster Bytes Reach Existing Installs (dev/59 follow-up)

Date: 2026-08-05
Status: implemented 2026-08-05 — COMMIT-c2cac301. Verification: backend `pytest tests
--ignore=tests/test_frontend` → 1047 passed; the reported scenario is regression-pinned
(a stale materialized instruction on disk; the run composes the current roster bytes) plus
the owned-import-shadow regression.

## 1. Problem Statement (root cause, confirmed in code)

The model's refusal is a verbatim recitation of the superseded dev/52 instruction — because it
still RUNS it. Two compounding gaps:

1. **Runtime resolution is store-first for prompt BYTES.** `_resolve_prompt_text` reads the
   materialized store copy before the roster. `_resolve_definition` already prefers the ROSTER
   for built-in-trust definitions ("evolving built-in metadata always takes effect") — but the
   prompt bytes never got the same rule, so an install made before a roster prompt update runs
   the stale instruction forever.
2. **The dev/44 heal checks completeness, not freshness.** `_materialize_builtin` skips any
   store copy whose asset SET matches (`complete → return`) — changed bytes inside an existing
   asset are never rewritten, even on re-install.

Every past and future built-in prompt improvement (dev/59's removal posture, dev/48/50/52's
net-new instructions, any future fix) silently fails to reach users who installed earlier.

## 2. Approach — the roster is the single truth for built-in bytes (both layers)

- `_resolve_prompt_text`: for a **built-in-trust** resolved definition, the roster's prompt
  bytes win (fall back to the store copy only when the roster file is absent) — the exact rule
  `_resolve_definition` already applies to metadata, extended to prompts with the same
  rationale. Owned/imported definitions — including deliberate shadows of a built-in coord —
  keep their own bytes untouched (their trust differs; regression-pinned).
- `_materialize_builtin`: completeness isn't freshness — the heal also compares each declared
  asset's store bytes against the roster source and rewrites drifted copies, so
  install/import-time materialization (which exists for publish/upload flows) stays honest too.
- No migration needed: the runtime fix takes effect on the next run of any existing install.

## 3. Tests / Acceptance

- A store copy holding STALE instruction bytes: the run's system turn carries the CURRENT
  roster instruction (route-level, by content — the dev/59 removal posture).
- Re-install heals drifted bytes on disk; an owned-import shadow of a built-in coord keeps its
  bytes through both paths (regression).
- [x] "Clear the canvas" reaches a model that knows removals are in its authority — the run
      composes the dev/59 instruction regardless of when the agent was installed.

## 4. Commits

1. `Built-in prompt propagation: roster bytes win for built-in trust + freshness-aware heal (dev/60)`
2. Docs: memo implemented + BL-P5 amendment.
