# Implementation Memo: Share-Surface Regression Suite + Shared-Payload Sanitization

Date: 2026-07-27
Status: **implemented** (commit `6fe7133`; `BL-P4-20260727-16`)

## 1. Problem Statement

Tracking rule 9 (from `DEC-032`/memo `dev/12`) requires exactly one piece of share evidence: a regression suite proving the agents feature introduces **no agent-private data as a new shared surface** in Curio's existing flow-sharing. That evidence had never been recorded — flagged in the `2.1` status pass — and writing the suite exposed a **live leak**: the unauthenticated `GET /api/projects/<id>/shared` route served the raw on-disk spec, which carries the backend-owned agent sections. A shared link therefore exposed the install lockfile (`dataflow.agents`), every attachment record — including **edited intents, manual conversation titles, attachment ids, and session ids** — and the project's `agentDefaults` policy record.

(Transcripts, account settings, and quota counters were never exposed: they live in FS sidecars outside the spec per `DEC-040`/memo `dev/20`, behind owner-only endpoints.)

## 2. As-Built Fix

- Pure `project_agents.strip_agent_state(spec)`: a sanitized **copy** of the spec whose dataflow omits `_AGENT_SPEC_KEYS` (`agents`, `agentAttachments`, `agentDefaults`) — the same key list `preserve_agent_state` protects, so a future backend-owned section added there is automatically excluded from the share surface too. Non-mutating; tolerant of missing/malformed specs.
- `load_shared_project` serves the sanitized copy (spec payload, detail derivation, and output hydration all see it); the on-disk spec is untouched, and the shared viewer's non-agent graph (nodes/edges/packages/datasets) is intact.

## 3. The Regression Suite (`tests/test_agents/test_share_regression.py`)

Written **before** the fix and failing against the leak, then green after:

1. `strip_agent_state` unit behavior (strips all agent keys, keeps the rest, never mutates, tolerates malformed specs).
2. End-to-end: a project with the full private surface (install + canvas attachment with an edited intent and a manual title + a persisted session) → the unauthenticated shared payload contains **no** agent sections and none of the private strings (coordinate, attachment id, session id, intent text, title text).
3. Sanitization leaves the on-disk spec byte-equivalent in its agent sections.
4. Owner-only endpoints: another user's `GET` on the attachments list, the session transcript, and the project defaults all 404 without leaking the session id.

## 4. Traceability

- Rule 9 evidence recorded: `BL-P4-20260727-16`; `DEC-032` and the lifecycle REQ row in `2.1` updated from "evidence pending" to recorded.
- `REQ-SHARE-001`/`REQ-SHARE-002`, `RISK-SHARE-001`/`RISK-SHARE-002` (invariant now test-enforced); `dev/29`/`dev/30` (the `_AGENT_SPEC_KEYS` single source now feeds both preserve and strip).
