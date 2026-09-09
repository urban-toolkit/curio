# dev/113 — The `connection` attach target: Node Builder on an existing edge, inserting a reviewed node between its endpoints

**Status: IMPLEMENTED (2026-08-27) — commits `c9a2307c` (1, backend contract/mint/apply/re-target + 6 route tests), `8dad35a7` (2, drop-on-edge + hover store + EdgeAgentBadges + targetLabel + panel), `819f5f48` (3, composer connection branch + insert card + provider precedence + tests), `91aeb141` (4, docs). `DEC-071` minted; backlog `BL-P5-20260827-47`. Deviation from §3.2: inserting into an INTERACTION connection is refused plainly (no node can be a data-pool for one half and a visualization for the other) rather than "keeping the kind". Built in a dedicated worktree after the shared tree was switched to another branch mid-implementation. Owner live re-test pending.**

Date: 2026-08-27
Branch / tree: `feat/agentscatalog` @ `d4bf71ce`. Line numbers pinned to that commit.
Origin: dev/15 §5 ("Node Builder attaches to the canvas or a selected connection"; `compatibleTargets` includes `{kind: "connection"}`), deferred at dev/48 §3.1 (`builtin.py:172-174`: *"connection" target — deferred (no UI)*), restated in the `BL-P5-20260818-30` follow-up line and dev/104 §1.4, recorded as DEFERRED on 2026-08-27 (`d4bf71ce`); the owner now asked for the memo. **Supersedes that deferral record on approval.**
Decisions taken by the owner ("take your recommendations", 2026-08-27): (1) the target is dev/15's **existing edge** — the legacy node-widget *handle-side* suggestions (`styles.tsx:437-451`, `generateConnectionSuggestions` → raw `llmRequest`) are a different concept, stay untouched, and are NOT this memo; (2) **Node Builder only** declares the kind (Connection Builder stays `node`); (3) attach gesture = **drop-on-edge hit-test**, parity with drop-on-node; (4) render surface = an **edge-midpoint badge**; (5) apply semantics = a **new reviewed proposal kind `node.insert`** (edge split), digest-pinned per DEC-049, validated by dev/112's topology helper; (6) ordering: dev/112 first.
Family: dev/43 (drawer) → dev/48 (Node Builder composite, `node.create`) → dev/50 (`compatibleTargets[].requires`) → dev/52/59/62 (bridge, reviewed removals) → dev/44/111 (grounded context) → dev/67-3 (fan-in) → dev/108 (panel presentation) → **dev/112** (acyclicity + edge kind — prerequisite).
Design decisions consumed: DEC-040 (attachments live in the spec beside nodes/edges), DEC-042 (panel header), DEC-047 (depth-1 children never mint), DEC-049 (destructive ops digest-pinned, reviewed by name), DEC-051, DEC-070 (dev/112, proposed). **New decision proposed: DEC-071** — *a connection attachment targets an existing edge id; its one mutation is the reviewed `node.insert` (remove the edge, add the node, add two edges of the original kind) validated as one plan against the saved spec.*
Backlog: `BL-P5-20260827-NN` at closure; the entry-30 follow-up line and the 3.1 remainders block flip from DEFERRED to the closing entry.

---

## 1. Problem Statement

**Current behavior.** The backend attachment layer already accepts `connection` targets: `attachments.py:19` (`_TARGET_KINDS`), `validate_target` requires an existing **edge id** (`:70`), orphan pruning drops attachments whose edge is gone (`:129`), tested (`test_attachments.py:38-40`, `test_prune_attachments.py:29-30`). Everything above it is missing:
- No built-in declares the kind. Node Builder is `targets=("canvas",)` (`builtin.py:174`); `attach_agent` therefore 400s any connection attach (`services.py:835`: *"this agent attaches to canvas, not connection"*).
- The frontend types the kind (`agentsApi.ts:72, 528`) but never produces it: drop-to-attach hit-tests nodes, else canvas (`MainCanvas.tsx:322-325`, `pickNodeAtPoint` in `utils/agentDropAttach.ts`); there is no edge hit-test, `onEdgeClick`, or edge context menu.
- No render surface: node attachments render in `NodeAgentBadges.tsx:16-17` (`kind === "node"`), canvas ones in `AgentDock`; a connection attachment would exist only in the ‹ › cycle.
- The grounded-context composer has no `connection` branch in `targetContext` (`agentRunContext.ts:142-157`) and `connectionSide` has no producer (dev/44).
- No apply can "insert between": `node.create` (`tools.py:225-240`) adds a free-standing node; `dataflow.plan.write` could remove-and-add, but Node Builder does not hold that tool and the result would not be atomic with the edge removal.

**Expected behavior.** A user drags Node Builder from the palette onto an **edge**; the edge highlights; the attachment lands with target `{kind: "connection", targetId: <edgeId>}`; a badge appears at the edge midpoint; the chat header reads *Attached to connection "Temporal Feature Engineering" → "Pool Input Merge"*. The agent's context carries both endpoints and the edge (kind, handles). Its proposal is a reviewed **`node.insert`**: the card names the edge to be removed (DEC-049.2), the node to add, and the two replacement edges; Apply performs the three operations atomically on the saved spec (409 + stale on drift: edge gone, endpoints changed, or a cycle), then the bridge mirrors them on the canvas. The attachment survives the split by re-targeting to the **downstream** replacement edge (deterministic rule, §4). If the edge is deleted manually, the attachment is pruned as today.

**Why it matters.** dev/15's promised third hook has been un-deliverable since dev/48; the "hooks" pills in the drawer (`AgentsCatalogDrawer.tsx:282`) and `docs/AGENTS.md:3, 38, 90, 178, 192` all advertise `connection`. With dev/112's topology helper, the substantive risk of the feature (an insert creating an invalid graph) is handled by an existing validator instead of new logic.

## 2. Scope

**Included**
- Backend: `builtin.py` Node Builder `targets=("canvas","connection")`; `tools.py` new `node.insert` contract (mutate, Node Builder only); `services.py` — mint (`_mint_node_insert`), apply (edge removal + node + two edges via the dev/59 removal path and the dev/112 helper), `_attachment_card` target label for edges, run-time `targetContext` **server** parity where a delegate reads it (dev/67-6 `node_context` is node-scoped; a connection target passes both endpoints through the same composer — see §3.4); orphan prune unchanged.
- Frontend: `utils/agentDropAttach.ts` `pickEdgeAtPoint` (distance to the rendered path) used AFTER the node hit-test; `MainCanvas.tsx` drop branch + edge hover highlight during agent drag; `components/edges/{UniDirectionalEdge,BiDirectionalEdge}.tsx` render an `EdgeAgentBadges` at the label position (`EdgeLabelRenderer`); `AgentChatPanel` header target line; `agentRunContext.ts` `targetContext`/`connectionSide` connection branches; `useAgentCanvasMutations.ts` `node-inserted` mutation (remove edge → insert node → add two edges, one batch); `AgentReviewCard.tsx` insert card; `agentsApi.ts` types.
- Tests: backend `test_builtin.py` (Node Builder targets), `test_routes.py` (`TestNodeInsert`), `test_attachments.py` (re-target rule); frontend `agentDropAttach.test.ts`, `EdgeAgentBadges.test.tsx`, `agentRunContext.test.ts`, `useAgentCanvasMutations.test.tsx`, `AgentReviewCard.test.tsx`.
- Docs: `docs/AGENTS.md` (hooks table, attach row, Node Builder paragraph), DEC-071, BL-P5 closing entry, `node_build_instruction.txt` (connection-target paragraph; sha-pinned roster update).

**Must be checked but not changed**
- `attachments.validate_target`/prune — already correct for edges.
- dev/112's `_data_cycle` helper and interaction-edge materialization — consumed, not modified.
- `node.create` — unchanged; canvas-target Node Builder behavior is byte-identical.
- The manual edge path (`onConnect`, `hasCycle`) — untouched.

**Out of scope (explicitly)**
- Connection Builder / the legacy handle-side suggestions and every `llmRequest` caller (owner instruction).
- An edge context menu (gesture (3) chose drop-on-edge; a menu can be added later without touching the data model).
- Attaching other agents to edges (Node Explainer on an edge, etc.) — the roster stays as is; the mechanism is generic so a later one-line `targets` change suffices.
- Multi-edge selection targets.

## 3. Recommended Implementation Approach

**3.1 Roster + contract.** `agent.node-builder`: `targets=("canvas","connection")`, `tools += ("node.insert",)`. `node.insert` contract text: *"Propose inserting ONE new node into the connection this agent is attached to: the connection is removed and replaced by <source> → new node → <target>, keeping the original connection's kind. Params: `{nodeType, content?, title?, goal?, appearance?}` (same as node.create). Only valid when attached to a connection. The user reviews the proposal; nothing changes without approval."* The target edge id is NOT a parameter — it comes from the attachment record (the agent cannot aim at another edge; DEC-047-style least privilege).

**3.2 Mint.** `_mint_node_insert(user_key, project_id, attachment, params)`: resolve the attachment's edge in the saved spec (missing → refused, *"the connection this agent was attached to no longer exists"*); validate `nodeType` exactly as `node.create` does (available templates, canonicalization per dev/93); compose the equivalent plan `{nodes:[{ref:"ins", nodeType, …}], edges:[{from: src, to: "ins"}, {from: "ins", to: dst, toHandle: <original targetHandle if merge slot>, kind: <original kind>}], removeEdges:[edgeId]}` and run it through dev/112's mint validators (fan-in, acyclicity, interaction compatibility). Two consequences fall out for free: inserting into an **interaction** edge requires the new node to be interaction-capable or the mint refuses with the dev/112 message; inserting into a merge-slot edge preserves the slot. The proposal stores `baseEdgeDigest` (id + source + target + handles + kind) for DEC-049 drift detection and a `removals` block naming the edge.

**3.3 Apply.** Reuse the whole-plan apply path (`services.py ~2860-3060`) on the composed plan — one spec write, the dev/59 cascade bookkeeping, the dev/112 re-check → `_mark_stale` 409 on drift. After the write, **re-target the attachment** to the downstream replacement edge (`ins → dst`) and bump its `revision`; return `{createdNodes, createdEdges, removedEdgeIds, retargetedTo}` so the bridge and the panel update without a reload. Rationale for downstream: the user's mental model is "the agent sits where the data enters the target"; the rule is deterministic and documented in the card copy (*"After apply, this agent stays attached to the new connection into <target>"*).

**3.4 Grounded context.** `agentRunContext.ts`: `targetContext` on a connection target → `"Target connection: " + JSON({edgeId, kind, source:{id,type,goal,content-length}, target:{…}, sourceHandle, targetHandle})` — the same bounded snapshot shape as the node branch, twice, plus the edge; `connectionSide` → not applicable (this is an edge, not a side) — remains omitted, honesty note updated in dev/44's audit table. `nodeIntent` stays user-message-driven. The server-side `node_context.compose_node_context` is node-scoped and untouched; the Node Content Builder delegation for the inserted node happens after apply on the real node id, exactly as canvas-target Node Builder does today.

**3.5 Frontend gesture + surface.** `pickEdgeAtPoint(edges, nodes, flowPos, tolerance=12px)`: reuse ReactFlow's rendered path geometry via `getBezierPath`/`getSmoothStepPath` inputs already used by the edge components; nearest edge within tolerance wins; nodes win over edges (hit-test order node → edge → canvas). During an agent drag, the hovered edge gets a `data.agentDropHover` flag the edge components render as a thicker stroke (parity with the node drop affordance). `EdgeAgentBadges` mirrors `NodeAgentBadges` (`kind === "connection" && targetId === edgeId`), positioned via `EdgeLabelRenderer` at `labelX/labelY`; click → `openChat`. Both edge components mount it (Uni + Bi).

**3.6 Panel + card.** `AgentChatPanel` target line: `Attached to connection "<source title>" → "<target title>"` (titles via the existing display-name helper; fallback to ids). `AgentReviewCard` `node.insert` card: header `Insert "<title>" into <source> → <target>`, a DEC-049.2 removals line for the connection, the two new connections listed, kind badge for interaction.

## 4. Data and State Handling

- Source of truth: the saved spec — attachment target (`agentAttachments[].target.targetId` = edge id), edge set, node set. The frontend never invents edge ids; it hit-tests the live edges, which carry spec ids.
- Attach ordering: like node targets (`attachAgentOnDrop` saves the project first so the edge exists server-side — `MainCanvas.tsx:326-329` comment), the edge must be persisted before attach; the helper already does this.
- Re-target after apply: server-owned, atomic with the spec write; the client applies `retargetedTo` to its attachment list (revision-checked) — no refetch flicker.
- Orphaning: manual edge deletion → prune (existing); the badge disappears with the edge because it is rendered by the edge component.
- Drift: mint stores the edge digest; apply compares; any change → 409 + stale, the card shows the existing stale state.
- No new client state beyond the hover flag on the dragged-over edge.

## 5. UI and UX Requirements

- Drop affordance on edges during agent drag (stroke + cursor), toast `Agent attached to the connection.`
- Badge at edge midpoint, same avatar component (`AgentAvatarBadge`), keyboard-focusable, `aria-label="Open chat with <agent> attached to connection <source> → <target>"`.
- Panel header target line as above; ‹ › cycling includes connection attachments (already does).
- Card copy names all three operations and the re-target rule.
- Reduced motion: badge has no animation beyond the existing avatar styles.

## 6. Edge Cases

- Drop exactly on a node that overlaps an edge → node wins (documented order).
- Edge deleted while the chat is open → the attachment is pruned on the next spec write; the panel shows the existing "attachment gone" state (dev/108 keeps the header pinned during exit).
- Edge endpoints changed (reconnected) between mint and apply → digest mismatch → 409 + stale.
- Inserting into an interaction edge with a non-interaction-capable node → dev/112 compatibility refusal at mint.
- Inserting into a merge-slot edge → the downstream edge keeps `toHandle=in_N`; fan-in unchanged; validated by `_validate_plan_fanin`.
- Two connection attachments on the same edge → both re-target to the downstream edge after either applies (rule applied to all attachments whose target is the removed edge).
- Agent attached to the canvas AND asked to "insert between A and B" → `node.insert` refused (*"attach this agent to the connection first"*); the agent is told so via the corrective message.
- Self-loop or duplicate edge after insert — impossible by construction (new node has fresh id; both new edges have distinct endpoints).
- Large graphs: hit-test is O(edges) per drop event only (not per drag frame) — hover highlight throttled to the drag-over event.

## 7. Testing Strategy

**Backend.** `test_builtin.py`: Node Builder targets include `connection`; `node.insert` in its tools; no other built-in gains it. `TestNodeInsert` (`test_routes.py`): mint on a data edge → plan shape (two edges, removal, kind preserved); merge-slot edge preserves `toHandle`; interaction edge + non-capable node → refused; edge missing → refused; apply → spec has node + two edges, old edge gone, attachment re-targeted downstream, revision bumped; drift (edge re-wired) → 409 + stale; canvas-target Node Builder calling `node.insert` → refused; injection: `params.edgeId` ignored. `test_attachments.py`: re-target rule for two attachments on one edge.

**Frontend.** `agentDropAttach.test.ts`: node beats edge; edge within tolerance; nothing → canvas. `EdgeAgentBadges.test.tsx`: renders only connection attachments for its edge; click opens chat. `agentRunContext.test.ts`: `targetContext` connection branch (both endpoints + edge), `connectionSide` still omitted. `useAgentCanvasMutations.test.tsx`: `node-inserted` batch = remove edge, add node, add two edges (handles + kind). `AgentReviewCard.test.tsx`: insert card copy incl. removal line. `AgentChatPanel.test.tsx`: header target line for connections.

**Gates.** Backend `pytest tests/test_agents` green; frontend full jest green; dev/108 overlay tests untouched.

## 8. Acceptance Criteria

1. Dragging Node Builder onto an edge attaches it with `{kind:"connection", targetId:<edgeId>}`; other agents dropped on an edge get the existing 400 message surfaced as a toast.
2. A badge renders at the edge midpoint; clicking opens the chat; the header names both endpoint titles.
3. Sending a message composes `Target connection:` context with both endpoints and the edge kind/handles.
4. A `node.insert` proposal card names the removed connection, the new node, and the two new connections; Apply performs all three atomically; the canvas mirrors them without reload; the attachment now sits on the new downstream edge.
5. Inserting into an interaction edge or a merge-slot edge preserves kind/slot; invalid results are refused at mint with dev/112's messages.
6. Manual edge deletion prunes the attachment and removes the badge.
7. Canvas-target Node Builder behavior and `node.create` are byte-identical to today (existing tests unmodified).
8. `docs/AGENTS.md` and the drawer's hooks pills are now true for `connection`.

## 9. Recommended Commit Breakdown

- **Commit 1 — backend contract + mint.** Roster targets/tools, `node.insert` contract, `_mint_node_insert` on the dev/112 validators, tests (mint cases).
- **Commit 2 — backend apply + re-target.** Apply path reuse, re-target rule, response shape, drift tests, `_attachment_card` label.
- **Commit 3 — frontend attach gesture + badge.** `pickEdgeAtPoint`, drop branch, hover affordance, `EdgeAgentBadges` in both edge components, panel header line, tests.
- **Commit 4 — frontend context + apply bridge + card.** Composer branches, `node-inserted` mutation, insert card, tests.
- **Commit 5 — contract copy + docs.** `node_build_instruction.txt` (sha pin), `docs/AGENTS.md`, DEC-071, BL-P5 closing entry (flip the DEFERRED record), memo status.

## 10. Engineering Quality Checklist

- [ ] No second topology validator: `node.insert` composes a plan and reuses dev/112's mint/apply validators.
- [ ] Edge id comes from the attachment, never from model params.
- [ ] Badge/hit-test logic mirrors the node equivalents (shared avatar component, same drop helper module).
- [ ] Re-target rule server-owned, deterministic, tested for multiple attachments.
- [ ] Drift → existing stale lane; no new status.
- [ ] Canvas-target Node Builder byte-identical (pinned).
- [ ] Legacy connection-suggestion code and `llmRequest` callers untouched (owner instruction).
- [ ] a11y labels on badge and card; reduced-motion respected.
