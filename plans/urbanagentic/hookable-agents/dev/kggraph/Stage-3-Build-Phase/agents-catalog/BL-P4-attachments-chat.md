# Build Log — P4: Attachments & Chat

Child log for Phase 4 (see `../3.1-Agents-Catalog-Build-Log.md`). Entries follow the
Build Entry Template and are append-only.

---

## BL-P4-20260720-01: Attachment model + backend API (Feature 6, slice a)

- Date / author: 2026-07-20 / Karla
- Status: verified
- Requirements: `REQ-ATTACH-003` (private attachment from a same-project template; `attachmentId` + concurrency revision, no SemVer/publish), `REQ-STATE-002` (project isolation)
- Design decisions/artifacts: `DEC-031` (attachment identity = `attachmentId` + optimistic `revision`, no version lifecycle), `DEC-040` (FS-backed — attachments live in the project graph spec); `SRC-MEMO-LIFECYCLE-012`
- Tasks: `TASK-P4-attach-api`
- Risks/questions: `RISK-ATTACH-001` (attachment mistaken for a versioned artifact), `RISK-LIFECYCLE-002` (no auto-chaining — attach requires an already-installed template)
- Design-to-code decision or deviation: attachments are records in `spec["dataflow"]["agentAttachments"]` (sibling of `nodes`/`edges`/`packages`/`agents`), mirroring the lockfile approach. A pure `attachments.py` (validate + append/remove on the spec dict; ids passed in so it stays testable) + a service that generates `attachmentId`/`sessionId` (uuid) and enforces "template must be installed in this project" (no auto-install). Attach targets a node/canvas/connection; node/connection targets must reference an existing node/edge in the spec.
- Files/modules changed: `app/agents/attachments.py` (new), `app/agents/services.py` (attach/detach/list + `_attachment_card`), `app/agents/routes.py` (GET/POST/DELETE attachments), `docs/AGENTS.md`
- Tests added/updated: `tests/test_agents/test_attachments.py` (pure, ~10) + `TestAttachments` in `test_routes.py` (4)
- Verification evidence: `pytest test_agents/` → 102 passed. Attach canvas → list → detach round-trip; attach without install → 400 (no auto-install); node target with non-existent id → 400; missing target → 400. Route ordering verified (static `/attachments` wins over `/<coord>`).
- Commit/PR: `COMMIT-93cbb17`

---

## BL-P4-20260720-02: Execute an attached agent via the provider port (Feature 6, slice c)

- Date / author: 2026-07-20 / Karla
- Status: verified
- Requirements: `REQ-RUNTIME` (provider-neutral execution), `REQ-AGENT-001` (an attached agent completes its workflow)
- Design decisions/artifacts: `SRC-BLUEPRINT-005`; reuse of the Feature-4 provider port (`agents/providers.py`) + Feature-2a `_resolve_llm_config` (aiconn default)
- Tasks: `TASK-P4-run`
- Risks/questions: `RISK-PROMPT-001` (prompt asset resolution), `RISK-EGRESS-001` (dispatch to the resolved provider)
- Design-to-code decision or deviation: `run_attachment` resolves the attachment's source instruction prompt — built-in from `utk_curio/llm-prompts/` (`builtin.read_instruction_text`), else the definition's `prompts.instruction` asset in the store/published dir — sends it as the system turn + the caller's `message` as the user turn, and dispatches through `run_chat_completion`. The route lazy-imports `_resolve_llm_config` from the main api routes to build the `ProviderConfig` (no import cycle; verified via `create_app()`). This is where built-in execution first becomes real; store/published defs without a materialized prompt asset return 422 (prompt-byte materialization on install remains a follow-up).
- Files/modules changed: `app/agents/builtin.py` (`read_instruction_text`), `app/agents/services.py` (`run_attachment` + `_resolve_instruction_text`), `app/agents/routes.py` (`.../run`), `docs/AGENTS.md`
- Tests added/updated: `TestRun` in `test_routes.py` (3)
- Verification evidence: `pytest test_agents/` → 105 passed; `create_app()` OK (no import cycle). Verified the dispatch sends the built-in's instruction as `system` + the message as `user`; unknown attachment → 404; empty message → 400 (provider port mocked).
- Commit/PR: `COMMIT-e5ee213`
- Follow-up work: persistent chat sessions/history; frontend drop-to-attach + dock tile + chat UI (slice b); prompt-byte materialization for store/published defs.

---

## BL-P4-20260720-03: Frontend drop-to-attach + attachments hook (Feature 6, slice b-1)

- Date / author: 2026-07-20 / Karla
- Status: verified
- Requirements: `REQ-ATTACH-003`, `REQ-A11Y`
- Design decisions/artifacts: reuse of the Feature-5b `agentsApi`/`apiFetch`; the palette drag payload (`application/curio-agent`); `MainCanvas.handleDrop` seam
- Tasks: `TASK-P4-frontend-drop`
- Risks/questions: `RISK-STATE-001` (dock vs spec divergence), `RISK-UX-001`
- Design-to-code decision or deviation: add attachment methods to `agentsApi` (list/attach/detach/run) + a self-contained `useAgentAttachments(projectId)` hook (list + attach/detach/run + `curio:agent-dock-refresh` sync). Wire `MainCanvas.handleDrop`: when the drop carries `application/curio-agent`, attach the coord to the canvas (via a small callback) and stop — a minimal branch alongside the existing dataset/reactflow branches, no restructuring.
- Files/modules changed: `src/api/agentsApi.ts` (attachment types + methods), `src/utils/agentsPaletteEvents.ts` (`readAgentDragCoord` + dock event), `src/components/agents/attach/useAgentAttachments.ts` (new), `src/components/MainCanvas.tsx` (drop branch + `projectId`)
- Tests added/updated: `agentsApi.test.ts` (+4 attachment methods), `useAgentAttachments.test.ts` (6)
- Verification evidence: `npx jest` → 19 pass (13 api + 6 hook); `tsc --noEmit` clean on all touched files including `MainCanvas`.
- Commit/PR: `COMMIT-aac8672`
- Follow-up work: dock tile + chat panel (slice b-2); node-target drop (attach to the node under the cursor) — this slice attaches to the canvas.

---

## BL-P4-20260720-04: Attachment dock + chat panel (Feature 6, slice b-2)

- Date / author: 2026-07-20 / Karla
- Status: verified
- Requirements: `REQ-CHAT` (unified chat for an attached agent), `REQ-A11Y`, `REQ-AGENT-001`
- Design decisions/artifacts: reuse of `useAgentAttachments` (slice b-1) + the run endpoint (`BL-P4-…-02`); `SRC-CHAT-008`
- Tasks: `TASK-P4-dock-chat`
- Risks/questions: `RISK-UX-001` (dock/chat focus), `RISK-STATE-001`
- Design-to-code decision or deviation: split into presentational `AgentDock` (tiles; select/detach) + `AgentChatPanel` (one-turn-per-send over `onSend`, in-memory history, error turn) + a thin `AgentDockOverlay` container wiring `useAgentAttachments` and mounted once on the canvas in `MainCanvas` (hidden in shared view). Chat is stateless single-turn per send (persistent sessions deferred). Node-target drop still deferred (palette drop attaches to canvas).
- Files/modules changed: `src/components/agents/attach/{AgentDock.tsx,AgentDock.module.css,AgentChatPanel.tsx,AgentDockOverlay.tsx}` (new), `src/components/MainCanvas.tsx` (mount), `docs/AGENTS.md`
- Tests added/updated: `src/tests/attach/{AgentChatPanel.test.tsx (4),AgentDock.test.tsx (3)}`
- Verification evidence: `npx jest` agents frontend → 138 passed (10 suites, no regressions in existing catalog specs). `tsc --noEmit` clean on all touched files including `MainCanvas`.
- Commit/PR: `COMMIT-09f204c`
- Follow-up work: persistent chat sessions/history; node-target drop; prompt-byte materialization so store/published defs run; ~~Node Explainer tab removal (`DEC-033`)~~ *(cancelled by `DEC-041` — see `BL-P4-20260721-11`; the tab stays)*.

---

## BL-P4-20260720-05: Prompt-byte materialization on install (Feature 6, slice d)

- Date / author: 2026-07-20 / Karla
- Status: verified
- Requirements: `REQ-PROMPT-001` (installed agent is self-contained with digest-verified prompt assets), `REQ-AGENT-001` (any installed agent runs)
- Design decisions/artifacts: `DEC-040` (FS-backed), `DEC-030` (imported-only publish); `SRC-MEMO-PROMPT-006`
- Tasks: `TASK-P4-materialize`
- Risks/questions: `RISK-PROMPT-001` (prompt asset containment), `RISK-PUBLISH-001` (a materialized built-in must not become publishable)
- Design-to-code decision or deviation: on Install (and Import), materialize the definition's bytes into the user store `.curio/users/<key>/agents/<id>@<version>/` (`manifest.json` + `prompts/`), copying a built-in's instruction from `llm-prompts/`. `_resolve_instruction_text` already reads store-first, so any installed agent then runs from its own on-disk bytes rather than the legacy prompt dir. **Knock-on:** `publishable`/`publish_agent` switch from "store-backed" to `provenance.trust == "imported"`, so a materialized built-in (trust `built-in`) stays non-publishable (`DEC-030`).
- Files/modules changed: `app/agents/storage.py` (`write_definition`), `app/agents/builtin.py` (`get_builtin_spec`), `app/agents/services.py` (`_materialize_builtin` on install/import; `_resolve_instruction_text` store-first; trust-based `publishable`/`publish_agent`), `tests/test_agents/test_routes.py`, `docs/AGENTS.md`
- Tests added/updated: `TestMaterialize` (2: install materializes manifest+prompt on disk; a materialized built-in stays non-publishable) + `_write_def` trust → `imported`
- Verification evidence: `pytest test_agents/` → 107 passed. Verified: after installing a built-in, `<store>/<coord>/{manifest.json,prompts/<file>}` exist; `_resolve_instruction_text` reads the store copy (equals the seeded `llm-prompts` text, so `TestRun` still matches); publishable/publish gated on `trust==imported`.
- Commit/PR: `COMMIT-07b69c8`
- Follow-up work: node-target drop; persistent chat sessions; ~~Node Explainer tab removal (`DEC-033`)~~ *(cancelled by `DEC-041` — see `BL-P4-20260721-11`; the tab stays)*; a def with no prompt asset returns 422 (owned imports get prompts via upload-import, v2).

---

## BL-P4-20260720-06: Node-target drop (Feature 6, slice e)

- Date / author: 2026-07-20 / Karla
- Status: verified
- Requirements: `REQ-ATTACH-003` (attach to a compatible target), `REQ-DOCK`
- Design decisions/artifacts: reuse of React Flow's `data-id` node DOM attribute + the existing attachment backend (node targets already supported/validated)
- Tasks: `TASK-P4-node-drop`
- Risks/questions: `RISK-UX-001`; attach validates the node against the *saved* spec (unsaved node → 400).
- Design-to-code decision or deviation: a pure `resolveAgentDropTarget(eventTarget)` helper walks up the drop target's DOM to `.react-flow__node[data-id]` → `{kind:"node", targetId}`, else `{kind:"canvas"}` (guards a non-Element target so it never throws). `MainCanvas.handleDrop` uses it so dropping an agent on a node attaches to that node (toast names the target). No backend change — node targets were already supported/validated (`BL-P4-…-01`). Node existence is validated server-side against the saved spec, so dropping on a not-yet-saved node surfaces the backend error (save-first caveat, documented).
- Files/modules changed: `src/utils/agentsPaletteEvents.ts` (`resolveAgentDropTarget` + `AgentDropTarget`), `src/components/MainCanvas.tsx` (resolve node/canvas target + toast), `docs/AGENTS.md`
- Tests added/updated: `src/tests/palette/agentDropTarget.test.ts` (6: node wrapper, node descendant, off-node canvas, wrapper without id, null target, non-Element target)
- Verification evidence: `npx jest src/tests/palette src/tests/attach src/tests/api src/tests/hook` → 47 passed (6 suites, no regressions); the new suite → 6 passed; `tsc --noEmit` clean on all touched files including `MainCanvas`.
- Commit/PR: `COMMIT-c7f57b4`
- Follow-up work: persistent chat sessions; ~~Node Explainer tab removal (`DEC-033`)~~ *(cancelled by `DEC-041` — see `BL-P4-20260721-11`; the tab stays)*; optional save-before-attach so a freshly-added (unsaved) node can be a drop target without a 400.

---

## BL-P4-20260720-07: Preserve agents/attachments across canvas saves (bugfix; filed as memo `dev/29`)

- Date / author: 2026-07-20 / Karla
- Status: verified
- Requirements: `REQ-STATE-002` (project isolation/durability), `REQ-ATTACH-003`
- Design decisions/artifacts: `DEC-040` (FS-backed — agent state lives in the project spec); the existing `update_project` spec-write-lock merge pattern
- Tasks: `TASK-P4-persist-fix`
- Risks/questions: `RISK-STATE-001` (client snapshot clobbers backend-written spec) — realized: installed agents vanished on refresh.
- Root cause: `saveCurrentProject` builds the spec via `TrillGenerator.generateTrill` (nodes/edges/packages/datasets) and omits `dataflow.agents` + `dataflow.agentAttachments`; `update_project` wrote it verbatim, so any canvas save after an install wiped the backend-owned agent sections. Packages survive only because the client tracks + re-serializes them.
- Design-to-code decision or deviation: added pure `project_agents.preserve_agent_state(effective, existing)` — carries each agent section forward from the on-disk spec **only when the client omits it** (an explicitly-sent list, even `[]`, is honored so a future client can manage them). Wired into `update_project` inside the `spec_write_lock`, guarded by `data.spec is not None`. No frontend change — agents stay backend-owned (avoids the frontend-snapshot race the datasets code warns about).
- Files/modules changed: `app/agents/project_agents.py` (`preserve_agent_state`), `app/projects/services.py` (`update_project` wiring)
- Tests added/updated: `test_preserve_agent_state.py` (5 pure) + `TestSavePreservesAgentState` in `test_routes.py` (3: install survives save, attachment survives save, explicit list honored)
- Verification evidence: `pytest test_agents/` → 108 passed (8 new). Verified install→PUT /projects (spec w/o agents)→GET still lists the agent; attach→save→attachment persists; `dataflow.agents:[]` in the sent spec clears the lockfile.
- Commit/PR: `COMMIT-ecb7d43` (helper+unit), `COMMIT-4fe0438` (wiring+regression)
- Follow-up work: prune attachments whose target node was deleted on the canvas; persistent chat sessions; ~~Node Explainer tab removal (`DEC-033`)~~ *(cancelled by `DEC-041` — see `BL-P4-20260721-11`; the tab stays)*.

---

## BL-P4-20260720-08: Prune orphaned attachments on node/edge delete (filed as memo `dev/32`)

- Date / author: 2026-07-20 / Karla
- Status: verified
- Requirements: `REQ-ATTACH-003`, `REQ-STATE-002`
- Design decisions/artifacts: reuse of `attachments._node_ids`/`_edge_ids`; mirrors `_prune_sink_node_dataset_refs`; follows the `BL-P4-…-07` preserve step
- Tasks: `TASK-P4-prune-attach`
- Risks/questions: made visible by `-07` (preserved attachments now outlive their node); conservative — only clearly-orphaned node/connection targets pruned.
- Design-to-code decision or deviation: pure `attachments.prune_orphaned_attachments(spec)` drops node/connection attachments whose `targetId` is absent from the node/edge set; keeps canvas + valid + malformed. Wired into `update_project` inside the write lock, right after `preserve_agent_state` (so it prunes the carried-forward list against the new node set), guarded by `data.spec is not None`. Backend-owned; dock reflects it on next refresh/reload.
- Files/modules changed: `app/agents/attachments.py` (`prune_orphaned_attachments`), `app/projects/services.py` (`update_project` wiring)
- Tests added/updated: `test_prune_attachments.py` (4 pure) + `TestPruneAttachmentsOnDelete` in `test_routes.py` (1: node attachment pruned on delete, canvas survives)
- Verification evidence: `pytest test_agents/` → 113 passed (5 new). Verified attach-to-node → save spec without the node → attachment pruned; canvas attachment survives the same save.
- Commit/PR: `COMMIT-0840f18` (helper+unit), `COMMIT-c17328e` (wiring+regression)
- Follow-up work: persistent chat sessions; ~~Node Explainer tab removal (`DEC-033`)~~ *(cancelled by `DEC-041` — see `BL-P4-20260721-11`; the tab stays)*; save-before-attach for node-target drop on unsaved nodes.

---

## BL-P4-20260720-09: Refresh dock on save + save-before-attach for node drops (filed as memo `dev/33`)

- Date / author: 2026-07-20 / Karla
- Status: verified
- Requirements: `REQ-ATTACH-003`, `REQ-DOCK`, `RISK-UX-001`
- Design decisions/artifacts: reuse of the exposed `saveCurrentProject` (create-or-update) + `notifyAgentDockRefresh`; complements `-07`/`-08`
- Tasks: `TASK-P4-dock-refresh` (#5), `TASK-P4-save-before-attach` (#4)
- Design-to-code decision or deviation:
  - **#5:** `saveCurrentProject` fires `notifyAgentDockRefresh()` after a successful update save, so a deleted node's pruned attachment tile disappears without a reload (mirrors the dataset-catalog refresh on save). Fires on every update save — cheap, keeps the dock reconciled with any server-side spec change.
  - **#4:** new pure `utils/agentDropAttach.attachAgentOnDrop` — a node-target drop persists the graph first (so the freshly-added node is in the saved spec the backend validates), then attaches with the id from the save (also auto-creates a never-saved project); canvas targets skip the pre-save. Wired into `MainCanvas.handleDrop`, replacing the inline attach + upfront projectId guard.
- Files/modules changed: `hook/useWorkflowOperations.ts` (dock refresh on save), `utils/agentDropAttach.ts` (new), `components/MainCanvas.tsx` (wiring)
- Tests added/updated: `tests/hook/useWorkflowOperations.installSync.test.ts` (+1: dock refresh on update save), `tests/palette/agentDropAttach.test.ts` (6: node pre-save+order, never-saved id, id fallback, canvas skips save, no-id throws, save-failure propagates)
- Verification evidence: hook suite 16 passed; palette suites 22 passed; `tsc --noEmit` clean on all touched files.
- Commit/PR: `COMMIT-682cac1` (#5), `COMMIT-8dcd661` + `COMMIT-58974e1` (#4)
- Follow-up work: persistent chat sessions; ~~Node Explainer tab removal (`DEC-033`)~~ *(cancelled by `DEC-041` — see `BL-P4-20260721-11`; the tab stays)*.

---

## BL-P4-20260721-10: Attachment compatibility enforcement, canvas/node dock split, DnD reliability, badge tooltips (filed as memo `dev/34`)

- Date / author: 2026-07-21 / Karla
- Status: verified
- Requirements: `REQ-ATTACH-003` (attach only to a compatible target), `REQ-DOCK`, `REQ-A11Y`
- Design decisions/artifacts: approved dock/attachment concept (node agents glued to nodes, canvas agents in a top bar); `SRC-MEMO-LIFECYCLE-012` compatibility contract; built-in roster metadata
- Tasks: `TASK-P4-compat`, `TASK-P4-dock-split`, `TASK-P4-dnd-reliability`
- Risks/questions: `RISK-UX-001` (drop targeting/dock focus), `RISK-STATE-001` (single attachments source)
- Design-to-code decision or deviation:
  - **Compatibility (backend):** `attach_agent` rejects a target kind absent from the agent's `compatibleTargets`; `BuiltinAgentSpec` gains a multi-kind `targets` field (Chat/Debug are dual node+canvas); `_resolve_definition` prefers the built-in roster for built-in coordinates so evolved metadata beats a stale materialized copy (prompt bytes still resolve store-first).
  - **Dock split (frontend):** node agents render as `NodeAgentBadges` avatar chips glued to their node (inside `UniversalNode`); canvas agents cluster in the `AgentDock` bar; one shared `AgentAvatarBadge` (category-tinted chip, click=chat, hover=detach) and one `AgentAttachmentsProvider` feeding dock, badges, and chat selection.
  - **DnD reliability:** `dropEffect=copy` for agent drags plus coordinate hit-testing (`pickNodeAtPoint`) instead of DOM `closest`, so drops resolve to the node under the cursor or the canvas.
  - **Palette pills:** one pill per compatible target (Canvas/Node/Connection), so dual agents advertise both.
  - **Tooltip:** macOS-Dock-style hover/focus name label in the shared badge (aria-hidden; button keeps its aria-label), replacing the duplicating native `title`.
- Files/modules changed: backend `app/agents/{builtin.py,services.py}`; frontend `components/agents/attach/{AgentAttachmentsProvider.tsx,AgentAvatarBadge.tsx,AgentAvatarBadge.module.css,NodeAgentBadges.tsx,NodeAgentBadges.module.css,AgentDock.tsx,AgentDock.module.css,AgentDockOverlay.tsx}`, `components/{MainCanvas.tsx,UniversalNode.tsx}`, `menus/nodes/agentsPalette/AgentPaletteRow.{tsx,module.css}`, `utils/agentsPaletteEvents.ts`, `menus/top/UpMenu.tsx` (unused import)
- Tests added/updated: backend compatibility matrix + Chat/Debug dual + stale-materialization refresh in `test_routes.py`; frontend `NodeAgentBadges.test.tsx`, `AgentAvatarBadge.test.tsx`, `AgentPaletteRow.test.tsx`, updated `AgentDock.test.tsx`, `agentDropTarget.test.ts`, `AgentsPaletteDropdown.test.tsx`
- Verification evidence: backend `pytest test_agents/` and frontend `npx jest` suites green at each commit; `tsc --noEmit` clean on touched files.
- Commit/PR: `COMMIT-1abbd3c`, `COMMIT-f34b269`, `COMMIT-108dd7c`, `COMMIT-737d82f` (selected-agent blue focus border on the shared badge)
- Issues/regressions discovered: browser rejected agent drags without `dropEffect=copy`; DOM-`closest` drop targeting was brittle over React Flow internals — both fixed here.
- Follow-up work: persistent chat sessions.
- Remaining risks/questions: none new.

---

## BL-P4-20260721-11: Correction — Node Explainer tab removal permanently cancelled (`DEC-041`)

- Date / author: 2026-07-21 / Karla
- Status: verified (documentation correction; no code change)
- Requirements: `REQ-NODE-EXPLAIN-002` (retention — replaces retired `REQ-NODE-EXPLAIN-001`)
- Design decisions/artifacts: **`DEC-041`** (`../../18-node-explainer-tab-retention-memo.md`) supersedes `DEC-033`; `RISK-EXPLAIN-002` (reintroduction of the obsolete removal) replaces retired `RISK-EXPLAIN-001`
- Tasks: `TASK-P4-explainer-tab-removal` — **cancelled, will not be scheduled**
- Design-to-code decision or deviation: approved product decision — the built-in node Explanation tab (`NodeEditor.tsx` + `NodeExplanation.tsx`, including its direct prompt/provider path, cache, and `hasExplanation` flags) **remains part of the node UI permanently**. The attached Node Explainer agent (`agent.node-explainer`) coexists unchanged as an additional explanation surface; its attachment and chat behavior are not modified. No parity-migration or H-7 content-archival work is required (memo `17` §3.5 moot).
- Files/modules changed: none in code. Documentation: `dev/18` (new), `dev/00` index, `dev/02`/`dev/03`/`dev/12`/`dev/13`/`dev/14`/`dev/17` corrections, `2.1` design traceability, `3.1` build-log index (phase row, v1 cut, rules 20/21), and this log's prior follow-up lines (entries `-02`..`-09`) annotated as cancelled per rule 14 — history preserved, not erased.
- Tests added/updated: none required by this correction. Guardrail: a regression test asserting the Explanation tab renders is recommended when node-UI tests are next touched (`RISK-EXPLAIN-002` mitigation).
- Verification evidence: repo grep confirms `NodeEditor.tsx`/`NodeExplanation.tsx` untouched on this branch; no commit on `feat/hookable-agents` removes or hides the tab.
- Commit/PR: documentation-only (this planning-package update).
- Issues/regressions discovered: stale removal instructions remained in six follow-up lines here, the `3.1` index (phase row, v1 release cut, rule 21), and memos `02`/`03`/`12`/`13`/`14`/`17` + traceability `2.1`; all corrected under `DEC-041`.
- Resolution: `DEC-033` retired/superseded; the removal item is deleted from every pending-work and v1-gate list.
- Follow-up work: persistent chat sessions (the sole remaining P4 item).
- Remaining risks/questions: `RISK-EXPLAIN-002` — future documents must cite `DEC-041`; reopening removal requires an explicit new decision that names and supersedes `DEC-041`.

---

## BL-P4-20260721-12: Persistent chat sessions (memo dev/20)

- Date / author: 2026-07-21 / Karla
- Status: verified
- Requirements: `REQ-CHAT` (reopening resumes the session with its full transcript; the transcript is the run history), `REQ-STATE-002` (project privacy), `REQ-ATTACH-003`
- Design decisions/artifacts: `SRC-CHAT-008` (sessions semantics), `DEC-040` (FS-backed), `DEC-031` (session identity = the attachment); memo `dev/20`
- Tasks: `TASK-P4-sessions`
- Risks/questions: `RISK-STATE-001` (transcript vs server divergence), retention interim default (final durations `OQ-008`)
- Design-to-code decision or deviation: transcripts live in a private sidecar `.curio/users/<key>/projects/<pid>/agent-sessions/<sessionId>.json` — deliberately **outside** the spec so canvas saves and the share pipeline never carry conversation content (privacy by construction). `sessions.py` store (missing/corrupt ≡ empty; no migration); `run_attachment` sends the last 20 non-error turns as context and persists the exchange (provider failure → user turn + display-only error marker excluded from future context, 502); `GET`/`DELETE .../session` routes; GC on detach and on the canvas-save orphan-prune (`prune_orphaned_attachments` already returned the removed records). Frontend: `AgentAttachmentsProvider` holds the transcripts as a read-through cache (hydrate on open, cache on reopen, re-hydrate on reload; dropped on detach/project switch); `run`'s response contract unchanged.
- Files/modules changed: backend `app/agents/{sessions.py (new),services.py,routes.py}`, `app/projects/services.py`; frontend `api/agentsApi.ts`, `components/agents/attach/{AgentAttachmentsProvider.tsx,AgentDockOverlay.tsx}`; `docs/AGENTS.md`
- Tests added/updated: `test_sessions.py` (12), `TestSession` in `test_routes.py` (7 incl. detach/prune file GC + context-window + error-marker exclusion); frontend `AgentAttachmentsProvider.test.tsx` (6), `agentsApi.test.ts` (+2)
- Verification evidence: `pytest test_agents/` → 145 passed; `npx jest` full → 503 passed (50 suites); `tsc --noEmit` clean.
- Commit/PR: `COMMIT-f96d60b` (store), `COMMIT-906ad92` (run/routes/GC), `COMMIT-2d3478a` (provider hydration)
- Follow-up work: none for v1 — this closes the last deferred P4 item. (Streaming/SSE remains P2; retention durations remain `OQ-008`.)

---

## BL-P4-20260721-13: Chat concept restyle + close control + prompt-sourced editable intent (memo dev/19)

- Date / author: 2026-07-21 / Karla
- Status: verified
- Requirements: `REQ-CHAT`, `REQ-A11Y`, `REQ-PROMPT-001` (intent reflects the actual prompt source — no duplicated hardcoded value)
- Design decisions/artifacts: `docs/08` drawer anatomy (pinned editable INITIAL INTENT), `docs/03` "Chat feedback visual system", concept screens `03`/`06`; memo `dev/19`
- Tasks: `TASK-P4-chat-restyle`, `TASK-P4-intent`
- Risks/questions: `RISK-UX-001`; intent/prompt duplication avoided by resolving at read time
- Design-to-code decision or deviation: the attachment card gains `intent` = record override else `_resolve_instruction_text` (store-first prompt bytes) + `intentEdited`; `PATCH attachments/<id>` sets/clears the override (revision bump; empty → falls back to the prompt source); runs use the same value as the system turn, so the pinned intent is what runs. Panel restyled to the concept: white tinted-avatar header + "Attached to …" + session chip, clear labelled close (Escape too; close never detaches — transcripts survive via `-12`), clamped/expandable editable intent panel, `#f7f7f8` transcript with dark user bubbles / avatar-prefixed agent rows / soft error tones, pill input + circular ↑ send, 16px gutters, hairline `#ececee`, 12px radii; tints reuse `agentCategoryStyle`; styles moved to `AgentChatPanel.module.css`. Suggestions/behavior/preview/result cards and SUGGESTED PROMPTS chips deferred until the runtime emits structured content (no fabricated content).
- Files/modules changed: backend `app/agents/{attachments.py,services.py,routes.py}`; frontend `components/agents/attach/{AgentChatPanel.tsx,AgentChatPanel.module.css (new),AgentDock.module.css}`, `api/agentsApi.ts`; `docs/AGENTS.md`
- Tests added/updated: `TestSetIntent` (4 pure) + `TestIntent` in `test_routes.py` (4: card intent == prompt-file text read from the same file; PATCH persist/clear; validation/404; edited intent as system turn); frontend `AgentChatPanel.test.tsx` (11), `agentsApi.test.ts` (+1)
- Verification evidence: `pytest test_agents/` → 145 passed; `npx jest` full → 503 passed; `tsc --noEmit` clean. Attach/detach/dock/badges/palette suites unchanged and green.
- Commit/PR: `COMMIT-e3a4863` (set_intent), `COMMIT-906ad92` (card/PATCH/run), `COMMIT-2d3478a` (api/provider), `COMMIT-bd956c4` (restyle + close)
- Follow-up work: concept cards + suggested-prompt chips once the runtime emits structured content; header prev/next attachment navigation.
- **Amendment (`COMMIT-f1e6782`, filed as memo `dev/27`):** the transcript scrollbar was missing — `.messages` is a flex child and needed `min-height: 0` to shrink below its content (it was growing past the clipped panel). Same commit pins the view to the newest turn (scroll-to-bottom on turn changes/hydration) and caps the expanded intent block at 45% with its own scroll. Attach suites 28 passed; `tsc` clean.
- **Amendment (`COMMIT-c88193a`, product feedback — filed as memo `dev/26`):** the initial intent now renders as the conversation's **first message** (a plain user bubble at the top of the transcript, scrolling with it) instead of a pinned labeled section — still collapsed (4 lines) with show more/less and the edit pencil; the "edited" chip and the 45% cap are dropped with the pinned block. Attach suites 28 passed; `tsc` clean.

---

## BL-P4-20260721-14: DEC-042 header split — agent-view identity header + Pin-only roster header

- Date / author: 2026-07-21 / Karla
- Status: verified
- Requirements: `REQ-CHAT`, `REQ-A11Y`; previous/next attachment navigation (plan `dev/03` §scope)
- Design decisions/artifacts: **`DEC-042`** (`SRC-MEMO-HEADER-021`, `dev/21`); the regenerated concepts (`docs/05`, 2026-07-21) and the updated `docs/08` anatomy
- Tasks: `TASK-P4-header-split`
- Risks/questions: `RISK-UX-001` (drawer left with no dismissal after removing its ✕ — mitigated: backdrop/Escape gated by the pin)
- Design-to-code decision or deviation:
  - **Opened agent view** (`AgentChatPanel`): one dark two-line top header — ‹ › cycling arrows (all attachments in the dataflow, list order, no wrap, disabled at the ends; `AgentDockOverlay` supplies `index`/`total`/`onPrev`/`onNext` from the provider list), tinted bot + name + `idx / total`, Clear conversation + the preserved Close on line one; `Attached to <target>` + the session chip on line two. No Pin; no static `Agents Catalog` bar. Content below the header unchanged (intent-as-first-message, transcript, footer).
  - **Agents Roster drawer** (`AgentsCatalogDrawer` + provider): the static dark header keeps the **Pin only** (thumbtack, `aria-pressed`, rotate-on-active) with the orange bot title icon; the ✕ is removed. Pin semantics mirror the Data/Node catalog drawers: pinned blocks the backdrop-click and Escape dismissals; programmatic close (menu toggle) still works. Component props change `onClose` → `pinned`/`onPinToggle`.
- Files/modules changed: `components/agents/attach/{AgentChatPanel.tsx,AgentChatPanel.module.css,AgentDockOverlay.tsx}`, `components/agents/catalog/{AgentsCatalogDrawer.tsx,AgentsCatalogDrawer.module.css}`, `providers/AgentsCatalogDrawerProvider.tsx`
- Tests added/updated: `AgentChatPanel.test.tsx` (+2: cycling idx/total + prev/next, disabled ends), `AgentsCatalogDrawer.test.tsx` (+2: Pin-only header, pinned aria state; props migrated), `AgentsCatalogDrawerProvider.test.tsx` (backdrop-close unpinned, Escape unpinned, pinned blocks both then unpin restores)
- Verification evidence: `npx jest` full → 508 passed (50 suites); `tsc --noEmit` clean. Existing header assertions (name/target/session/Close/Escape) pass unchanged against the new markup.
- Commit/PR: `COMMIT-39760ab`
- Issues/regressions discovered: the panel was absolutely positioned inside the canvas container (which extends beneath the main top menu), so the new dark header's identity row rendered clipped under the menu — only line 2 was visible.
- Resolution (**Amendment `COMMIT-c4f2339`**, filed as memo `dev/28`): the panel renders via a portal to `<body>` as a full-height right drawer flush with the viewport top (`position: fixed`, z-index 1100 — above the top menu, below the roster drawer's backdrop), so the dark chat header sits at the top-bar level exactly as the concept shows; flush-drawer styling (left hairline + leftward shadow) replaces the floating rounded card. Attach suites 30 passed; `tsc` clean.
- Follow-up work: none for this decision — `dev/21` acceptance criteria met (concepts were regenerated in the same-day design pass).

---

## BL-P4-20260723-15: Conversation titles — auto-generated + click-to-rename (memo `dev/25`)

- Date / author: 2026-07-23 (implemented) / Karla — *entry filed retroactively 2026-07-27: this slice landed in a parallel session with its memo (`dev/25`) but without the build-log entry tracking rules 1/13 require; filed during the traceability sweep that also produced memos `dev/29`–`dev/34`.*
- Status: verified
- Requirements: `REQ-DOCK`/`REQ-CHAT` (distinguishable instances across tooltip/badges/header), `REQ-A11Y` (aria-labels updated with the composed title; keyboard-accessible inline rename), `REQ-STATE-002`
- Design decisions/artifacts: memo `dev/25` (binding as amended: clear-conversation clears **auto** titles only; a manual title always wins and survives clears); reuse of the `intent`/`intentEdited` pattern (`dev/19`), `preserve_agent_state` (`dev/29` — `title` rides in `agentAttachments` for free), the run-path structure (`dev/20`/`dev/22`)
- Tasks: `TASK-P4-conversation-titles`
- Risks/questions: title generation must never delay or fail the reply (best-effort, post-reply, failure-silent); model output treated as untrusted (sanitized plain text, ~40-char cap)
- Design-to-code decision or deviation: per memo — `title` + `titleEdited` stored on the attachment record (custom portion only; composition to `"<Template Name>: <Custom Title>"` happens at display time in one frontend helper, `attachmentDisplayName`); auto-generation is a second small non-streaming `run_chat_completion` (fixed 3–4-word-title prompt, small `max_output_tokens`) fired after the reply persists, only when the session had no prior user turn and `title is None and not titleEdited` (re-checked under the spec lock, so a mid-stream manual edit wins); the existing `PATCH …/attachments/<aid>` accepts `title` (trim/empty/cap validation, sets `titleEdited`, bumps `revision`); the chat-header title is the single-click (and Enter/Space) inline editor with the template-name prefix static; `sendMessage` reloads the listing only while the attachment is untitled; catalog drawer and settings modal stay template-name-only.
- Files/modules changed: backend `app/agents/{attachments.py (set_title + title cap),services.py (generation, precedence, clear-conversation rule, card fields),routes.py (PATCH title)}`; frontend `api/agentsApi.ts` (`title`/`titleEdited`, `updateAttachmentTitle`), `components/agents/attach/{attachmentDisplayName.ts (new),AgentAvatarBadge.tsx,AgentChatPanel.tsx,AgentAttachmentsProvider.tsx (saveTitle + conditional reload)}`
- Tests added/updated: backend `test_conversation_titles.py` (~408 lines: generation trigger/idempotence, sanitizer, precedence incl. manual-beats-auto races, clear-conversation rules, PATCH validation) + `test_routes.py` additions; frontend `attachmentDisplayName.test.ts`, badge/header/provider/api test additions
- Verification evidence (re-run 2026-07-27 during this filing): `pytest test_agents/` → 226 passed; `npx jest src/tests/{attach,api,catalog}` → 183 passed (12 suites).
- Commit/PR: `COMMIT-7d2c1e3` (backend storage/generation/PATCH), `COMMIT-0a764a0` (frontend display/rename/refresh)
- Issues/regressions discovered: none recorded.
- Follow-up work: optional "reset title" affordance to re-enable auto-generation after a manual rename (explicitly out of scope in `dev/25` §2).

---

## BL-P4-20260727-16: Share-surface regression suite + shared-payload sanitization (rule 9 evidence; memo `dev/35`)

- Date / author: 2026-07-27 / Karla
- Status: verified
- Requirements: `REQ-SHARE-001`/`REQ-SHARE-002` (no agent-private data as a new shared surface), `REQ-PRIVACY`
- Design decisions/artifacts: `DEC-032` (D-0 = B), memo `dev/12` §sharing, tracking rule 9 (this entry is the evidence it mandates); `_AGENT_SPEC_KEYS` single source (`dev/29`/`dev/30`)
- Tasks: `TASK-SHARE-regression`
- Risks/questions: `RISK-SHARE-001`/`RISK-SHARE-002` — **realized and fixed**: the unauthenticated shared route served the raw spec, exposing the lockfile, attachment intents/titles/session ids, and `agentDefaults`.
- Design-to-code decision or deviation: test-first — the suite was written against the live behavior and failed (proving the leak), then pure `project_agents.strip_agent_state` (sanitized copy over `_AGENT_SPEC_KEYS`, so future backend-owned sections are auto-excluded) was wired into `load_shared_project`; on-disk spec untouched, shared viewers keep the full non-agent graph. Sidecar stores (transcripts, account settings, quotas) were already un-exposed by construction (`DEC-040`, `dev/20`) — the suite locks the endpoint side with owner-only 404 checks.
- Files/modules changed: `app/agents/project_agents.py` (`strip_agent_state`), `app/projects/services.py` (`load_shared_project` sanitization)
- Tests added/updated: `test_share_regression.py` (5: strip unit + malformed tolerance, end-to-end no-sections/no-private-strings on the shared payload, disk non-mutation, owner-only attachments/session/defaults endpoints)
- Verification evidence: suite failed pre-fix (3 failures demonstrating the leak), 5 passed post-fix; full backend `pytest tests --ignore=tests/test_frontend` → 734 passed (existing share tests unaffected).
- Commit/PR: `COMMIT-6fe7133`
- Follow-up work: none — the rule-9 evidence gap flagged in the `2.1` status pass is closed.
