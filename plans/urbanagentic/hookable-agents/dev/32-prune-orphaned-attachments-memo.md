# Implementation Memo: Prune Orphaned Attachments on Canvas Save

Date: 2026-07-20 (retroactive record, filed 2026-07-27 — specified conversationally as the direct follow-on to the preserve step; the durable evidence until now was build-log entry `BL-P4-20260720-08`)
Status: **implemented** (commits `0840f18` helper + unit tests, `c17328e` wiring + regression test)

## 1. Problem Statement

`preserve_agent_state` (memo `dev/29`) made a new failure mode visible: because attachments are now carried forward across canvas saves, an attachment bound to a **deleted node** outlives its target — a ghost instance pointing at nothing, still occupying the dock/badges.

## 2. Decision

Prune clearly-orphaned attachments server-side during the same save that deletes their target, conservatively: only a `node`/`connection` attachment whose `targetId` is absent from the saved spec's node/edge set is removed. Canvas attachments, valid targets, and **malformed records are kept** (never guess about a record we can't interpret).

## 3. As-Built Implementation

- Pure `attachments.prune_orphaned_attachments(spec)` (reusing `_node_ids`/`_edge_ids`; mirrors the datasets code's `_prune_sink_node_dataset_refs` pattern), returning the removed records.
- Wired into `update_project` inside the write lock, **immediately after** `preserve_agent_state` — so the carried-forward list is pruned against the *new* node set — guarded by `data.spec is not None`.
- Backend-owned; the dock reflects the prune on the next refresh (which memo `dev/33` then made automatic on save).
- Returning the removed records proved load-bearing later: the session-transcript GC (memo `dev/20`) deletes each pruned attachment's transcript file from the same return value.

## 4. Verification

`test_prune_attachments.py` (4 pure) + `TestPruneAttachmentsOnDelete` (attach-to-node → save without the node → pruned; canvas attachment survives). `pytest test_agents/` → 113 passed at commit time.

## 5. Traceability

- `BL-P4-20260720-08`; follows `dev/29`; consumed by `dev/20` (session GC) and `dev/33` (dock refresh); `REQ-ATTACH-003`, `REQ-STATE-002`.
