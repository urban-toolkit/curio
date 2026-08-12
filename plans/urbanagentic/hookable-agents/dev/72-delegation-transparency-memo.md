# Implementation Memo 72: Delegation Transparency — Every Delegated Task Lives in Its Agent's Chat, Linked from the Parent

Date: 2026-08-12
Status: implemented 2026-08-12 — COMMIT-bdf8d52d (backend: delegation part +
homes + traced delegates + Solve/validate trace + proposal home migration),
COMMIT-9c9f4f96 (frontend: delegation entry + icon-notch links + row chip
links). Verification: backend 1161 passed (8 skipped), frontend 784 passed,
tsc clean. BL-P5-20260812-16. Recorded deviations: (1) Solve workers resolve
homes FIND-ONLY (`home_create=False`) — worker threads must never write the
spec, so a missing node agent during a threaded solve falls back to the
builder home instead of creating one; (2) the service-level home attach
bypasses the attach ROUTE's target-compatibility checks by design (the route
contract is unchanged; homes are runtime placements); (3) the stream's
review_required emitter learned to skip non-proposal minted parts (delegation
parts now ride `minted`).

## 1. Problem Statement

Delegated work is invisible and unattributable today:

- **DEC-046 children are ghosts.** `delegation.run_delegate` executes a bare
  child run — no attachment, no session, no transcript. The child's existence
  is a `delegations` entry on the PARENT's execution record and a transient
  `delegate_result` stream line. The Node Researcher can verify a dataset,
  the NCB can generate content — and neither leaves a trace in any chat the
  user can open.
- **The Solve lifecycle bypasses the node's own agent.** dev/71 auto-attaches
  a Node Builder to every plan-created node, but it stays dormant: the whole
  Solve trace (generation rounds, dependency checks, execution status,
  validation verdicts, warnings/errors, self-corrections, outcome) lands in
  the DATAFLOW BUILDER's transcript. The agent responsible for the node never
  hears about its own node.
- **Content proposals contend for one slot.** Every validate/propose mint
  lands on the builder attachment's single `activeProposal`, superseding each
  other (the recorded 67-6 limitation) and forcing the 67-9 parking dance.
  The natural home — the node's own agent — exists since dev/71 and is unused.
- **No way to jump to the worker.** A delegation entry in the parent's chat
  offers no link to whoever did the work.

Expected (owner): every delegated task creates/activates the responsible
agent instance; its task, progress, diagnostics, tool/research activity,
retries, and result live in THAT agent's transcript, concise and structured;
the parent summarizes and LINKS — a compact icon of the delegated agent
notched into the task title, click-to-open — consistently for the Node
Builder, Dataset Finder, Node Researcher, connection agents, and every future
delegate.

## Expected Behavior (user-visible walkthrough)

1. When any agent delegates (the Dataflow Builder asks the researcher to
   verify a URL, the Node Builder asks the NCB for content, Solve fills a
   node), the parent's transcript shows a compact **delegation entry**: the
   task title with the delegated agent's ICON notched into its corner, a
   one-line status (running → ok/failed), and a one-line outcome summary.
2. **Clicking the icon opens the delegated agent's chat** — where the full
   story lives as a normal conversation: a framed task turn ("Delegated by
   Dataflow Builder: verify https://…"), then the agent's result turn with a
   structured trace card — what it checked/generated, evidence or verdicts,
   warnings and errors, retries — plus its execution record (model, usage).
3. **Solving a node writes the node's own story into its attached Node
   Builder**: the task turn, then one consolidated trace card — dependency
   check, per-round generation → execution → verdict (with the traceback tail
   on failures), self-correction attempts, final outcome — and the **content
   proposal itself now lives in that chat**: the review card with Apply is in
   the node's agent, where its node's work belongs. The plan row's "Content
   review pending" chip carries the same icon-link straight to it.
4. Failures stay attributable: a failed verification is a red entry in the
   researcher's chat; a failed generation round is in the node's Node Builder
   with its traceback; the parent shows the honest one-line summary and the
   link — never the dump.
5. Transcripts stay concise: one task turn + one result turn per delegated
   task (the trace card carries the structure); streaming progress still
   narrates live in the parent as today.
6. This is uniform: Node Builder, Dataset Finder, Node Researcher,
   connection/planning delegates, and any future agent get the same
   entry + icon-link + owned-transcript treatment automatically.

## 2. Scope

In scope (backend):
- **Delegation homes** — `_delegation_home(spec, coord, capability, inputs,
  parent_target)` in services.py: find-or-create the attachment where the
  delegated work lives. Node-scoped work (`node.content.generate`,
  `inputs.nodeId` present) → the target node's `agent.node-builder`
  attachment (dev/71's; best-effort created via `_attach_node_builder` when
  missing); everything else → an existing attachment of the DELEGATE's agent
  id (canvas-scoped preferred), else a new canvas attachment of the resolved
  coord. Creation is best-effort — a failed home never fails the delegation.
- **Traced delegation** — `_run_delegate_traced(...)`: wraps
  `delegation.run_delegate` (the DEC-046 seam stays pure): appends the framed
  task turn to the home session, runs the child, appends the result turn
  (bounded reply text + a structured trace card: capability, verdict/status,
  verification evidence lines when present, duration) with the child's
  execution record; returns the home attachment id alongside the existing
  tuple. Both loop call sites (blocking + stream) and the Solve worker use it.
- **A typed `delegation` content part** (content.py, runtime-emitted like
  proposals): `{type: "delegation", capability, coord, name, attachmentId,
  status, summary}` — bounded; persisted on the PARENT's turn so the entry
  and its link survive rehydration. The stream's `delegate_result` event
  gains `attachmentId`/`name` for the live render.
- **The Solve/validate trace owns its node** — `validate_node_stream` and
  propose-mode Solve: (a) write the consolidated trace turn (task + rounds
  card) to the node's Node Builder attachment (fallback: parent turn only,
  when no home exists); (b) **mint the content proposal ON the node's Node
  Builder attachment** when present (fallback: the parent attachment as
  today) — per-node proposals stop superseding each other and the review
  lives with the responsible agent. `nodeProposals[ref]` becomes
  `{proposalId, attachmentId}`; the 67-9 driver's approve action and the
  67-6 content-apply ledger advance resolve through it (the ledger lives on
  the BUILDER's session — the apply path receives the builder attachment id
  for the ledger update even when the proposal lives on the node agent).
- Roster note: none — this is runtime plumbing; DEC-046 invariants
  (depth-1, tool-less children, reply-never-parsed) are untouched.

In scope (frontend):
- **`AgentDelegationEntry`** renderer for the new part: task title with the
  delegated agent's category icon as a compact notched badge (the approved
  concept style — overlapping the title's corner), status tint, one-line
  summary; click → `ctx.openChat(attachmentId)`. Used in the transcript and
  as the transient stream line's final form.
- Plan row chips ("Content review pending" / "Failed — Solve retries") gain
  the same icon-link to the node's Node Builder chat when
  `nodeProposals[ref].attachmentId` is known.
- The dock/badge listing already shows the node-target attachments; no new
  surfaces.

Out of scope: multi-level delegation (children stay depth-1); streaming the
child's own tokens into its transcript live (the durable turns are written at
task/result boundaries; live progress keeps narrating in the parent); rich
per-tool traces for tool-less children beyond the injected verification
evidence; changing DEC-046 admission/ledger semantics; icon asset design
beyond the existing category icon set.

## 3. Recommended Implementation Approach

- **One wrapper, every call site.** `_run_delegate_traced` is the single
  choke point: home resolution → task turn → `run_delegate` → result turn →
  `(status, text, child, home_attachment_id)`. The loop sites build the
  parent's `delegation` part from its return; the Solve worker passes the
  node id so the home is the node's agent.
- **Task turns are framed user-role turns** ("[Delegated by <parent name>]
  <task summary>") so the delegated agent's chat reads as a real
  conversation and later standalone chats keep the context; result turns are
  agent-role with the bounded reply and the trace card. One of each per task.
- **The validate loop writes ONE consolidated trace** at the end (rounds,
  per-round verdicts with error tails, dependency/execution facts from the
  validation evidence) rather than a turn per round — concise by contract.
- **Proposal home migration is additive**: `_mint_node_content_write` gains
  an explicit `home_attachment_id` parameter (defaults to the caller's
  attachment — classic behavior); validate/propose pass the node agent's id
  when it exists. `apply_proposal` already works per attachment; the driver
  reads `{proposalId, attachmentId}` from `nodeProposals`. The 67-9 parking
  mechanism stays (plans still park behind OTHER proposals on the builder),
  but per-node content reviews stop contending entirely.
- **The part is the link.** The parent's turn carries the `delegation` part;
  rehydration re-renders entry + icon-link with no extra fetches (the
  attachment id is in the part; a stale id — detached agent — falls back to
  a plain entry).

## 4. Data and State Handling

- New durable data: the child-home transcript turns (ordinary session files)
  and the `delegation` parts on parent turns. No new stores.
- `nodeProposals[ref]` shape change `{proposalId, attachmentId}` — additive
  read (old string values tolerated as builder-homed).
- Concurrency: each home attachment has its own session file; Solve workers
  write distinct homes — no contention. The builder's ledger updates stay on
  the builder's spec record (single write path as today).
- Homes are best-effort everywhere: no home → the delegation behaves exactly
  as today (parent-only), honestly noted in the part (`attachmentId: null`).

## 5. UI and UX Requirements

- The delegation entry: compact single line + icon notch; status coloring
  (running/ok/failed); never a wall of text — the details are one click away
  in the owning chat.
- The owning chat's trace card: structured lines (task, rounds, verdicts,
  evidence, outcome), the same result-card component family as Solve cards.
- Icon = the delegated agent's category icon in a small circular badge,
  overlapping the entry title's corner (approved concept style); accessible
  name "Open <agent name>'s chat".

## 6. Edge Cases

- Delegate resolved but its home creation fails → delegation proceeds,
  part carries `attachmentId: null`, entry renders without a link.
- Node's Node Builder attachment deleted mid-solve → fallback to parent-only
  trace; the content proposal falls back to the builder attachment.
- The same researcher attachment receives tasks from two parents → both
  task/result pairs append chronologically; framing names each parent.
- Rehydration after the delegated attachment was detached → plain entry, no
  dead link (existence checked at render via the attachments list).
- Classic (non-simulation) Solve: same trace/home behavior per node when the
  node has a Node Builder attachment; without one, behavior is unchanged.
- Guest/keyless runs: unchanged — turns are written regardless of provider.

## 7. Testing Strategy

- Backend: home resolution (node-scoped → node's builder; agent-scoped →
  existing/created canvas attachment; uninstalled/failed → None); traced
  delegation writes task+result turns with the trace card + execution record;
  parent turn carries the bounded `delegation` part; validate/propose mint on
  the node agent (fallback pinned) with `nodeProposals` shape + driver
  approve-through; ledger advance still lands on the builder session;
  concise-by-contract (exactly two turns per task).
- Frontend: delegation entry renders icon-link + status and opens the chat;
  stale-attachment fallback; plan-row chip link; stream `delegate_result`
  final form.
- Full suites green.

## 8. Acceptance Criteria

- [x] Every delegated task (researcher verify, NCB generation, Solve rounds)
      appears as a task+result conversation in the responsible agent's chat,
      with a structured trace card (rounds, verdicts, evidence, errors).
- [x] The parent transcript shows a compact delegation entry whose notched
      agent icon opens the delegated agent's chat — uniformly for every
      delegate, live and after reload.
- [x] A node's Solve lifecycle (trace AND content review) lives in its
      attached Node Builder; per-node content proposals no longer supersede
      each other on the builder.
- [x] Failures and self-corrections are visible in the owning chat and
      summarized honestly in the parent.

## 9. Recommended Commit Breakdown

1. Backend: delegation part type + `_delegation_home` + `_run_delegate_traced`
   + loop call sites + tests.
2. Backend: Solve/validate trace + proposal home migration + driver/ledger
   adjustments + tests.
3. Frontend: delegation entry renderer + icon-link + row chip links + stream
   final form + tests.
4. Docs: memo flip + BL-P5 entry.

## 10. Engineering Quality Checklist

- One traced-delegation choke point; DEC-046's seam and invariants untouched.
- Two turns per task — concise by contract, structure in the card.
- Homes and links are best-effort: no delegation ever fails over its trace.
- The part carries everything the UI needs; rehydration-safe, no N+1 fetches.
