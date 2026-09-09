# Implementation Memo: P2 Runtime Maturation — T2b: Executing Tools + Review-Before-Apply

Date: 2026-07-28
Status: implemented 2026-07-28 (`BL-P2-20260728-08`, `DEC-045`; commits `ffef3b9a`, `c580aeaa`, `f812b4f4`, `fc815f3e`)
Feature slice: v2 runtime maturation, tranche 2b (the follow-up dev/39 §1 and `BL-P2-20260728-07` explicitly deferred: "the first executing tool + the review-before-apply application flow + the `tool_requested`/`tool_result`/`review_required` event vocabulary")
Design sources: `DEC-006`/`REQ-REVIEW-001` (review-before-apply gates every graph/data mutation; "no graph/data mutation occurs without an explicit, **revision-safe** review action"), `DEC-017`/`REQ-PERM-001` (server-allowlisted typed tools; declarations grant nothing), `ADR-AG-007` (domain tools remain domain-owned; agent infrastructure wraps them as authorized typed references), `ADR-AG-006` + dev/03:344 (the normalized event vocabulary: `tool_requested`, `tool_started`, `tool_result`, `review_required`, `mutation_applied` — adopted here by exactly those names), `dev/05` blueprint (`AgentReviewCard` planned component :513/:995 — the sanctioned system review surface; step 9 :356 "pause at `review_required` for any mutation; apply only an authorized, revision-checked proposal"), `RISK-SEC-001` (unsafe tool invocation → allowlists + review gates), `REQ-SEC-002` (tool output is untrusted rich content), memo `dev/38` (the grounded `inputs.reads` mapping that names the first read-tool consumers), memos `dev/37`/`dev/39` (the envelope + tail protocol + empty registry this fills)
New decision required: **`DEC-045`** — the bounded tool-execution loop + digest-pinned proposal/apply flow below (`DEC-044` is reserved by the pending dev/40 T3 memo), **including the LangChain disposition**: the runtime remains the direct provider-port implementation; `DEC-007`'s "LangChain as the initial runtime" adoption is explicitly deferred to the genuine revisit point — P5 multi-agent delegation (`delegatesTo`, the Dataflow Builder orchestrator) — because a two-round parse→execute→re-prompt loop under server-authoritative grants and a mandatory review pause is smaller and safer as direct code than as a constrained agent executor. Recorded here per tracking rule 10 (deviations link an approving decision). Registered in the dev/03 table + 2.1 ledger with the docs commit.
Sequencing: independent of T3 (dev/40) — tool calls integrate with whichever accounting layer exists at implementation time (advisory counters today, ledger settlement if T3 lands first; §4.6).

## 1. Position in the Maturation Program

Dev/39 shipped tool *contracts* with a deliberately empty registry: "the first real tool arrives with its first consumer". This memo names those consumers and ships the tools — without waiting for the P5 composites, because real consumers already exist in the built-in roster:

- **Read tools**: the dev/38 mapping grounds every built-in's `inputs.reads` in what its legacy call site passed — yet attachment chat sends only the conversation. `agent.debug-agent`, `agent.dataflow-explainer`, and `agent.workflow-suggester` declare `dataflowContext`; `agent.node-explainer` declares `nodeContext`. Today they answer **blind**. Two read tools — `dataflow.read` and `node.read` — let them ask for the context their manifests already declare.
- **The first mutating consumer**: `agent.node-content-builder` (`node.content.generate`, a node-target built-in) generates node content its legacy flow wrote into the node. Attached to a node, its chat can *propose* content — and `node.content.write` (mutate) with the review-before-apply flow is how a proposal becomes the node's content. This is the smallest genuine mutation in the product: one node's `content` field, no graph-shape changes.

**LangChain checkpoint (the standing dev/37 question — decision point was "first executing tool", i.e. now).** Recommendation: **still no.** The loop below is parse → execute → re-prompt, bounded at two rounds, over the existing provider port — tens of lines with full control over grants, bounds, and events. LangChain's agent executor would replace exactly that code with a heavy dependency whose loop we would immediately have to constrain back to this shape (server-authoritative grants, review pauses, typed events). Adopt only if a future tranche needs multi-agent delegation (`delegatesTo`, P5 orchestration) — the port seam is unchanged either way.

## 2. Problem Statement

- Agents whose manifests declare context reads answer without context: Node Explainer attached to a node cannot see the node (dev/38 declared the need; nothing supplies it). The manifest contract is currently a promise the runtime doesn't keep.
- The tool substrate is inert: `pins.tools` can only ever pin `[]`, `resolve_grants` has nothing to grant, and the mutate-ungrantable rule has never been exercised against a real mutation path.
- The concept's core loop — *the agent proposes; the user confirms; nothing happens silently* (`docs/08` invariants, `REQ-REVIEW-001`) — has no mechanism. Node Content Builder can only paste content into chat for the user to copy by hand; the legacy surface it replaced could apply.
- The normalized event vocabulary (`ADR-AG-006`) stops at `content`: a client cannot see that a tool ran, what it returned, or that a mutation awaits review.

## 3. Scope

**Included**

- Backend: tail-contract additions (`toolRequest` model-emitted part; `proposal` runtime-emitted part) in `app/agents/content.py`; the bounded read-tool execution loop in `services` with SSE `tool_requested`/`tool_started`/`tool_result` events and `toolCalls` on the execution record; registry entries `dataflow.read`, `node.read` (read) and `node.content.write` (mutate) with domain-owned implementations (`ADR-AG-007`); roster `tools` declarations for the grounded built-ins; proposal persistence + `review_required` + apply/dismiss endpoints with digest-pinned revision safety; a result turn + `mutation_applied` on apply.
- Frontend: `AgentReviewCard` (the blueprint's planned system review surface — Apply/Dismiss as **system review controls**, the explicitly sanctioned exception to "no agent action buttons"); tool-activity system lines in the transcript; apply/dismiss wiring incl. stale/conflict states; types and stream-event tolerance.
- Tests throughout, including the injection-resistance test (the model can never trigger an apply) and grant-boundary tests.

**Out of scope (owners)**: multi-agent delegation and composite orchestration (P5, `dev/15`); any tool beyond the three named (each future tool arrives with its consumer, per dev/39's rule); graph-shape mutations — node/edge creation or deletion (`workflow.suggest` proposals stay report-only text until a P5 consumer defines their apply semantics); tool-call *policy* fields on the settings screens (the per-run bound is a runtime constant until someone needs to tune it); leases/interruption recovery (`DEC-021`, background execution); prompt-time `inputs.reads` injection (this memo's read tools are the pull-based alternative; if prompt-time push is still wanted later it remains its own memo, now with usage data to justify it).

## 4. Design

### 4.1 Tail contract additions (`content.py`, still `curio.v1`)

Two new part types, one per direction:

- **`toolRequest`** (model-emitted, parsed from the tail): `{"toolRequest": {"tool": "dataflow.read", "params": {...}}}` — at most **one** per reply; `params` an object ≤ 1 KB; tool id must match the capability grammar. A reply carrying a `toolRequest` may also carry text (shown as a normal delta-streamed message) but no other parts (a request turn is a request turn — suggested prompts alongside it are dropped at validation).
- **`proposal`** (runtime-emitted only — **never** accepted from the model's tail; a model-emitted `proposal` invalidates the block, fail-open): `{type: "proposal", proposalId, tool, summary, preview, pins: {nodeId, contentSha256, specDigestBasis}, status: "pending"}` — persisted on the agent turn like any content part, and mirrored into the attachment record's single `activeProposal` slot (newest supersedes; clear-conversation discards).

The tail instruction becomes grant-aware: runs with granted tools get an appended paragraph enumerating exactly the granted ids with one-line usage descriptions from the registry; runs with none keep today's instruction byte-identical (regression-pinned).

### 4.2 The execution loop (read tools only, bounded)

```text
call model → reply carries toolRequest(read tool, granted)?
  → emit tool_requested {tool} → execute server-side → emit tool_started/tool_result {tool, status}
  → append {role:"tool"-style message} to the provider context → call model again
  → at most MAX_TOOL_ROUNDS = 2, then the model must answer with what it has
```

- Only **granted read** tools execute. A request for an ungranted/unknown tool gets a synthetic tool result stating the refusal (the model can recover in its final answer); a request for a granted **mutate** tool never executes — it becomes a proposal (§4.4).
- Tool results are untrusted data: bounded (≤ 32 KB, truncated with an explicit marker), passed to the model as context, never executed, and rendered in the transcript only as a system line ("`dataflow.read` · ok"), never as rich content. The loop cap bounds injection amplification (`RISK-SEC-001`); a tool result cannot request tools (only model replies are parsed).
- Bookkeeping: each round's provider call uses a fresh usage sink, **summed** into the execution record's `usage` and counted into the daily counters per call (T1's wiring gains the sum — today's single-sink overwrite would under-report a 2-round run). The execution record gains `toolCalls: [{tool, status, durationMs}]` (additive). Intermediate request-turn text is folded into the final visible reply's transcript turn — one persisted agent turn per exchange, as today; the tool exchange itself is context, not transcript (memo 12: the transcript is the *run* history; `toolCalls` on the execution record is the tool history).
- SSE ordering: `execution` → (deltas …) → `tool_requested` → `tool_started` → `tool_result` → (deltas …) → [`content`] → `done`. All additive; old clients skip them (both-direction tests as in T1/T2).

### 4.3 The three contracts (registry entries + domain-owned implementations)

| Tool | Effect | Params | Implementation (stays in its domain, `ADR-AG-007`) | Grounding consumer |
|---|---|---|---|---|
| `dataflow.read` | read | `{}` | The project's **saved** spec via `projects_storage.read_spec`, passed through `strip_agent_state` (agent-private sections never enter model context — the rule-9 posture applies to tool output too), truncated at the size bound | debug-agent, dataflow-explainer, workflow-suggester (declared `dataflowContext`) |
| `node.read` | read | `{nodeId?}` (defaults to the attachment's node target) | That node's entry from the saved spec (id, type, content, goal, in/out) | node-explainer (`nodeContext`), node-content-builder |
| `node.content.write` | mutate | `{nodeId, content}` | Sets one node's `content` in the saved spec via read-modify-`write_spec` under the project's existing spec lock — **only ever invoked by the apply endpoint**, never by the loop | node-content-builder (`node.content.generate`) |

Roster changes (`builtin.py`): `BuiltinAgentSpec` gains `tools`; the four consumers above declare exactly the rows shown (all optional — a missing grant degrades to today's blind behavior, never a 422). Grant policy update in `tools.resolve_grants`: mutate contracts become grantable **for proposal purposes only** — the loop still refuses to execute them; execution authority lives solely in the apply endpoint (the `DEC-006` gate is structural, not a policy flag).

### 4.4 Review-before-apply (`REQ-REVIEW-001`, revision-safe)

- A granted mutate `toolRequest` becomes a **proposal**: the runtime validates params (node exists, is the attachment's target or explicitly named, content non-empty and bounded), pins `contentSha256` of the node's *current* content (the revision-safety basis — no global spec revision exists, so drift detection is per-target digest), persists the `proposal` part + the attachment's `activeProposal`, emits `review_required` {proposalId, tool, summary} before `done`, and answers the model loop with "proposed, awaiting user review" so the final text reads honestly.
- **Apply** is an explicit user action on a system review surface, not a chat turn and not a model decision: `POST /projects/<pid>/attachments/<aid>/proposals/<proposalId>/apply`. The endpoint re-reads the spec, verifies the pinned digest (mismatch → 409 "the node changed since this was proposed" and the proposal marks `stale`), executes `node.content.write` under the spec lock, marks the proposal `applied`, appends an agent turn carrying a `result` **card** ("Applied: node content updated · <nodeId>") so the transcript logs the mutation (docs/08: results are logged as a result card), and returns the updated proposal. `DELETE .../proposals/<proposalId>` dismisses. Owner-auth like every attachment route.
- **The model cannot apply**: no tail content, tool result, or prompt text reaches the apply path — only the authenticated endpoint does. This is the injection-resistance property, tested by name.
- Concept compliance: `docs/08` bans **agent workflow** action buttons; Apply/Dismiss on the review card are generic **system review controls** — the same family as the `InstallPermissionsDialog` flow `DEC-035` mandates for package installs, and exactly the blueprint's planned `AgentReviewCard`. Suggested prompts remain how the agent steers conversation; review controls are how the *system* gates mutation.

### 4.5 Frontend

- `AgentReviewCard` (`components/agents/content/`): the docs/03 card shell + the proposal summary, a white inner panel with the content **preview** (plain text — `REQ-SEC-002`: proposed content is model output; it renders inert), and the Apply/Dismiss system controls with busy/`stale`/conflict states. Rendered from the `proposal` part; `status` ≠ `pending` renders the card inert with its outcome label ("Applied" / "Dismissed" / "Superseded" / "The node changed — propose again").
- Tool activity: `tool_requested`/`tool_result` render as transient system lines in the live transcript ("`dataflow.read` …" → "· ok"); they are not persisted turns (they're on the execution record) and vanish on rehydrate — matching the persistence rule.
- Provider/API: `applyProposal`/`dismissProposal` client calls; `activeProposal` on the attachment card; refresh-after-apply so the transcript's result turn and the card's `applied` state arrive together. Stream parser: two new event names (skip-tolerant as always).

### 4.6 Accounting integration

Tool calls are provider-call-shaped work: each loop round records its own usage (T1 counters today; a T3 ledger settles the summed run as one reservation with per-round usage in the settle entry if dev/40 lands first). The apply endpoint consumes **no** quota (deterministic, no provider work). A per-run tool bound is a constant (`MAX_TOOL_ROUNDS = 2`); surfacing it as policy waits for demand (`REQ-QUOTA-001`'s tool quotas note this as the eventual home).

## 5. Data and State Handling

- The transcript stays the single history: proposals ride agent turns; the mutation's outcome is a persisted result-card turn; tool exchanges live on the execution record (`toolCalls`), not as turns.
- `activeProposal` (attachment record) is a mirror for fast lookup + supersede semantics, never a second source of truth — apply/dismiss update both the turn part (by proposalId) and the mirror; hydration rebuilds the card from turns alone if the mirror is missing (old records).
- Digest pinning is the only revision mechanism added — no new global revision counter; conflicts surface as 409 + `stale`, recoverable by re-proposing.
- Privacy: `dataflow.read` output passes `strip_agent_state`; proposals/params contain node ids and content only (project-owned data the owner already sees); nothing new crosses the share surface (rule-9 suite re-run).
- No migrations: every new key (turn `proposal` part, `execution.toolCalls`, attachment `activeProposal`, manifest/roster `tools`) is additive; absent ≡ none.

## 6. Edge Cases

- Ungranted/unknown tool requested: synthetic refusal result, loop continues, final answer degrades gracefully — never a 500, never silent.
- Malformed `toolRequest` (bad grammar, oversized params, >1 per reply): whole tail invalid → fail-open to text (T2's rule, unchanged).
- Round cap hit while the model still wants tools: last call is made with an appended "answer with what you have" note; the reply is final.
- Tool execution raises (missing spec, unreadable node): `tool_result` `{status: "error"}` + synthetic error text to the model; the run itself does not fail.
- Node deleted / content changed between proposal and apply: digest mismatch → 409, proposal → `stale`, card explains; re-propose is a normal next turn.
- Two proposals in one conversation: newest supersedes (`superseded` status on the old part); apply of a superseded/dismissed/stale proposal → 409.
- Clear conversation / detach: proposal parts go with their turns; the mirror clears; a pending proposal cannot be applied after its transcript is gone.
- Canvas-target attachment proposing node content with no `nodeId`: validation refuses at proposal creation (the model gets the refusal as a tool result).
- Streaming disconnect mid-loop: completion-time persistence (nothing persisted, no proposal created — consistent since the proposal is minted at completion with the turn).
- Old client / new server and inverse: new events skipped; `proposal` parts render as the generic card shell on a T2-only client (informational, no apply — safe degradation); apply endpoints 404 on old servers.
- Stateless legacy attachment (no session): proposals need a transcript to live on — proposal creation is refused with a synthetic tool result (the same no-session fallback posture as T1's recordless response).

## 7. Testing Strategy

Backend — content: `toolRequest` parsing (grammar, one-per-reply, params bound, alongside-text rule), model-emitted `proposal` rejected. Loop (`test_routes.py`): granted read tool executes with correct SSE ordering and `toolCalls`/summed-usage on the execution record; ungranted/unknown/mutate requests never execute; round cap; tool-error path; grant-aware instruction (and byte-identical instruction when no grants — regression). Tools: `dataflow.read` strips agent state (share-grade assertion) and truncates; `node.read` target defaulting. Review flow: proposal minted with pinned digest + `review_required`; apply happy path (spec mutated under lock, result-card turn appended, `mutation_applied`); digest-drift 409 + `stale`; superseded/dismissed/stale apply 409s; **injection resistance** — a model reply/tool result/user message claiming approval changes nothing without the endpoint; owner-auth 404s; apply consumes no quota. Rule-9 share suite re-run.
Frontend: review card states (pending/busy/applied/dismissed/stale/superseded), preview renders inert (hostile fixture), Apply/Dismiss wiring + 409 handling, tool system lines from stream events, event-name tolerance, `AgentReviewCard` absent for old turns; all suites green.

## 8. Acceptance Criteria

- [x] Node Explainer / Debug / Dataflow Explainer / Workflow Suggester attachments can pull their declared context via granted read tools: the loop executes at most 2 rounds, events stream in the normalized order, and the execution record carries `toolCalls` + summed usage.
- [x] Node Content Builder can propose node content; the proposal renders as the review card with a plain-text preview; **only** the authenticated apply endpoint mutates the spec, digest-checked, logging a result-card turn — a drifted node yields 409/`stale`, and no model/tool/user *text* can trigger an apply (tested by name).
- [x] Grants remain server-authoritative: ungranted and unknown requests never execute; mutate tools never execute in the loop even when granted; tool results are bounded, stripped of agent-private data, and rendered only as system lines.
- [x] Runs without granted tools are byte-identical to T2 (instruction, envelope, behavior — regression-pinned); all new keys/events are additive and skip-tolerant both directions.
- [x] LangChain remains uninstalled (decision recorded: bounded loop over the port; revisit at P5 delegation); no new dependencies.

## 9. Recommended Commit Breakdown

1. `feat(agents): tail contract — toolRequest part + runtime-only proposal part, grant-aware instruction, with tests`.
2. `feat(agents): read-tool execution loop — dataflow.read/node.read contracts + domain impls, SSE tool events, toolCalls + summed usage on execution records, roster declarations, with tests`.
3. `feat(agents): review-before-apply — proposal persistence + pinned digests, apply/dismiss endpoints executing node.content.write under the spec lock, result-card turn + mutation_applied, with tests`.
4. `feat(agents): frontend — AgentReviewCard + tool system lines + apply/dismiss wiring and stale states, with tests`.
5. Docs + ledgers: build-log entry `BL-P2-2026…-09` (or -08 if T3 hasn't landed); register **`DEC-045`**; update the P2 phase row + dev/39's T2b follow-up line; `docs/AGENTS.md`; memo status flip.

## 10. Engineering Quality Checklist

- Execution authority is structural: read tools execute only inside the loop, mutations only inside the apply endpoint — no flag anywhere whose flip would let the model mutate (`DEC-006` by construction).
- Every tool implementation lives in its domain and is reached through one typed contract (`ADR-AG-007`); the registry gains exactly three entries, each with a named consumer.
- Fail-open for model content, fail-closed for authority — the T2 split, extended: malformed requests degrade to text; ungranted requests refuse loudly to the model, invisibly to the user.
- One loop, one bound, one instruction builder — no per-agent forks; grant-less runs are provably unchanged.
- The transcript remains the single history; execution records absorb the tool detail; the proposal mirror is rebuildable from turns.
- Event names match dev/03:344 exactly — no invented vocabulary to reconcile later.
