# Implementation Memo: Preserve Backend-Owned Agent State Across Canvas Saves

Date: 2026-07-20 (retroactive record, filed 2026-07-24 — this memo was delivered conversationally before implementation and never written to disk; the durable evidence until now was build-log entry `BL-P4-20260720-07`)
Status: **implemented** (commits `ecb7d43` helper + unit tests, `4fe0438` wiring + regression tests)

## 1. Problem Statement

Installed agents (and their attachments) **vanished on refresh after any canvas save**. Root cause: the client's `saveCurrentProject` builds the project spec via `TrillGenerator.generateTrill`, which serializes nodes/edges/packages/datasets but **omits** the agent sections `dataflow.agents` (the install lockfile) and `dataflow.agentAttachments` (private instances). `update_project` wrote the client snapshot verbatim, so every canvas save wiped the sections the agent endpoints had written server-side. (Packages survive only because the client tracks and re-serializes them — the agents feature deliberately does not put that burden on the client.)

This realized `RISK-STATE-001` (client snapshot clobbers backend-written spec) and violated `REQ-STATE-002` durability: install → save canvas → refresh lost the install.

## 2. Decision

The agent sections of the project spec are **backend-owned**: only the agent endpoints write them, the canvas save path never serializes them, and the save handler carries them forward from the on-disk truth. A client that *does* send a section — even an empty list — is honored, so a future authoritative client can still manage (e.g. uninstall/detach) via save; only a fully **omitted** section is preserved.

## 3. As-Built Implementation

- Pure `project_agents.preserve_agent_state(effective_spec, existing_spec)`: for each key in `_AGENT_SPEC_KEYS`, copy it from the on-disk spec into the incoming save **only when the incoming dataflow omits that key**; explicitly-sent values (including `[]`) win. Tolerant of missing/malformed specs (no-ops).
- Wired into `app/projects/services.update_project` **inside the `spec_write_lock`**, guarded by `data.spec is not None` (outputs-only updates untouched) — so the merge always runs against the latest on-disk spec, not a stale pre-lock read.
- No frontend change: avoiding a client-side snapshot race (the pitfall the datasets code documents) was the point.

## 4. Verification

- `test_preserve_agent_state.py` (5 pure: carry-forward, explicit-send honored, malformed/missing no-ops) + `TestSavePreservesAgentState` in `test_routes.py` (3: install survives a canvas save, attachment survives, an explicitly-sent `dataflow.agents: []` clears the lockfile). `pytest test_agents/` → 108 passed at commit time.

## 5. Consequences and Later Extensions

- Exposed the orphan problem it created: preserved attachments now outlived deleted nodes → the prune step (`prune_orphaned_attachments`, `BL-P4-20260720-08`) runs right after `preserve_agent_state` in the same save path.
- `_AGENT_SPEC_KEYS` has since grown with each new backend-owned section: `agentDefaults` (memo `dev/23`) — and the mechanism transparently protects fields later added to attachment records (intent, `dev/19`; conversation titles, `dev/25`).
- Session transcripts (memo `dev/20`) deliberately live **outside** the spec, so they never depend on this merge.

## 6. Traceability

- `BL-P4-20260720-07` (this work), `BL-P4-20260720-08` (the prune follow-on); `DEC-040` (FS-backed spec state); `RISK-STATE-001` realized → mitigated; `REQ-STATE-002`, `REQ-ATTACH-003`.
