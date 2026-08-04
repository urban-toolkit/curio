# Implementation Memo: Node Builder — the First P5 Composite (`node.build` + the delegation seam)

Date: 2026-07-30
Status: proposed
Feature slice: the first Phase-5 composite agent. `agent.node-builder` joins the roster with the
spec'd manifest surface (dev/15 §3.4), the first **graph-shape mutation** (`node.create`, reviewed),
and the first **real delegation** (a bounded, synchronous, depth-1 child run of
`agent.node-content-builder`, linked by `parentExecutionId`).
Design sources: `dev/15` (authoritative composite spec: capabilities `node.build` +
`dataset.fetch.author`, `delegatesTo`, orchestration invariants, `REQ-ORCH-001`), `dev/16`
(package-recommendation — not yet built, see deviations), `DEC-045`/`dev/41` (bounded tool loop,
digest-pinned proposals, apply-endpoint-only mutation), `DEC-044`/`dev/40` (ledger reserve→settle per
execution), `dev/37` (execution records + pins), `dev/38`/`dev/44` (grounded inputs + ephemeral
context), `DEC-006`/`REQ-REVIEW-001` (review-before-apply is structural), `DEC-017`/`REQ-PERM-001`
(server-allowlisted tools; declarations grant nothing), `ADR-AG-007` (domain-owned tool
implementations), `docs/06:65-74` (reviewable node preview before any graph mutation).

**Binding node-creation policy (owner updates, 2026-07-30/31): reuse first, create only as a
justified fallback.**
1. Node Builder first scans the existing node registry and **reuses** a suitable type whenever
   possible — built-in templates capable of executing/containing the required code, and custom
   templates from any package **within the permitted scope** (the project's package lockfile plus
   the seeded `curio.builtin@<major>`).
2. A **new custom node type may be created only when no existing built-in or scoped custom
   template can adequately fulfill the task** — as a reviewed proposal carrying the model's
   written justification (which templates were considered and why each is inadequate), applied
   through the **existing package factory** (`packages/factory.py`, the same build+install path
   the palette's Save-as-template flow uses). The human review is the adequacy gate; the runtime
   never auto-creates.
3. Future (non-normative, recorded for the program): the **Package Recommendation Agent** may use
   Node Builder to assemble innovative, self-contained node packages — combining newly created
   nodes with existing ones where that yields a coherent, reusable solution. That composition is
   a later memo (dev/16's runtime slice); nothing here may block it, and the factory-backed
   creation path below is exactly the seam it will reuse.

New decision required: **DEC-046** — delegation runtime disposition (§3.4): the first delegation
slice is **direct provider-port code** — a single-level, synchronous, bounded child run sharing the
parent's loop-round budget — not a LangChain/LangGraph executor. `DEC-007`'s adapter adoption
(deferred at `DEC-045` to "P5 multi-agent delegation") is **narrowed to the genuine revisit point:
Dataflow Builder** — multi-child parallel orchestration with plan/evaluate cycles is graph-executor
territory; one synchronous child call is not. The seam is preserved: all resolution + child-run
mechanics live in one new module (`delegation.py`) behind one function, so a later adapter swap is
contained. Register in the dev/03 table + 2.1 ledger with the docs commit.

## 1. Problem Statement

The product roster ships thirteen migrated prompt agents but none of the three composites
(`dev/15`). Node Builder is the entry composite: it is the smallest (one delegate that already
exists in the runtime — Node Content Builder), it unblocks Dataset Finder (which hands external
picks to Node Builder rather than authoring fetch code itself), and it forces the two P5 mechanisms
every later composite needs:

1. **Graph-shape mutation.** The runtime's only mutation is `node.content.write` (replace one
   existing node's content). Nothing can *create* a node. "Add a visualization of X" ends as text
   the user re-types by hand — the concept's core authoring loop (docs/06: a reviewable node preview
   the user applies) has no mechanism.
2. **Delegation.** `delegatesTo` is parsed and validated in the manifest (`manifest.py:274-286`) but
   nothing consumes it: no capability resolution, no child execution, no `parentExecutionId`, no
   missing-specialist handling. dev/15's invariants (current-project-only resolution, no
   auto-install, independent re-authorization per level) have no code.
3. **A latent apply/canvas clobber defect (found during this memo's audit, must be fixed here).**
   `apply_proposal` mutates only the **saved** spec; nothing pushes the applied content into the
   live ReactFlow canvas (no event, no listener — verified: `applyProposal` in
   `AgentAttachmentsProvider.tsx:251-267` only rehydrates the transcript). The next canvas save
   posts the **live** graph (with the node's *old* content) and `preserve_agent_state` preserves
   only agent sections — silently overwriting the applied mutation. For `node.create` the same gap
   would be fatal on day one: a node existing only in the saved spec is *deleted* by the next save.
   Both mutations therefore need a live-canvas applier bridge.

**Expected behavior.** Node Builder is installable/attachable like any built-in; attached to the
canvas, a request like "create a transformation node that computes X" yields (optionally) a
delegated content-generation child run, then a **reviewable node-creation proposal** (type +
content preview). Apply — and only apply — inserts the node into the saved spec *and* the live
canvas in the same action. A missing delegate yields a reviewed `Install in project` proposal,
never a silent install or a dead end.

## 2. Scope

**Backend (`utk_curio/backend/app/agents/`)**
- `builtin.py`: `BuiltinAgentSpec` gains `delegates_to` and `review_policy` fields (defaults keep
  all thirteen existing manifests byte-identical); new roster entry `agent.node-builder`; net-new
  instruction asset `llm-prompts/node_build_instruction.txt` (+ existing `default_preamble.txt`),
  so `read_prompt_text`/materialization heal work unchanged.
- `tools.py`: registry entries `node.create` and `node.template.create` (both mutate); nodeType
  and template-draft validation delegate to thin helpers over the existing packages domain
  (`ADR-AG-007`) — no allowlist or template knowledge of their own.
- `services.py`: `_mint_proposal` grows a per-tool dispatch (`node.content.write` → existing branch;
  `node.create` → new branch; `project.install` → delegation's missing-specialist branch);
  `apply_proposal` grows the matching apply dispatch; the run loop handles a `delegateRequest` part
  alongside `toolRequest`; execution records gain `delegations` (additive, like `toolCalls`).
- `delegation.py` (new): capability resolution over `delegatesTo` ∩ current-project templates +
  the bounded child run (DEC-046).
- `content.py`: `delegateRequest` model-emitted part (grammar, bounds, exclusivity — mirror of
  `toolRequest`); `make_proposal_part` accommodates the two new proposal shapes; the tail
  instruction names delegation only when the manifest has resolvable delegates.
- SSE vocabulary: `delegate_requested` / `delegate_started` / `delegate_result` (skip-tolerant
  clients ignore them, same posture as every event added since dev/37).

**Frontend (`utk_curio/frontend/urban-workflows/src/`)**
- `api/agentsApi.ts`: proposal part / apply-response types (`createdNode`, `project.install` and
  `node.create` proposal kinds); stream-event tolerance for the three delegate events.
- `components/agents/content/AgentReviewCard.tsx`: render the two new proposal kinds (node-create
  preview = type + content; install = agent name + project).
- `components/agents/attach/`: the **canvas applier bridge** — apply responses carrying a mutation
  payload dispatch a window event (`utils/agentCanvasEvents.ts`, new, mirroring
  `agentsPaletteEvents.ts`); a listener hook mounted where ReactFlow is reachable
  (`AgentDockOverlay` already has `useReactFlow` + `useFlowContext`) inserts the created node via
  `FlowProvider.addNode` or updates the live node's content for `node.content.write` — closing
  defect §1.3 for both tools. Transient delegate-activity lines in the chat (same rendering path
  as tool-activity lines).
- Palette/catalog: nothing — the roster addition appears automatically.

**Explicitly out of scope**
- Dataflow Builder and Dataset Finder (each is its own memo; Dataset Finder next per the program
  order, T4 provider profiles first).
- Nested delegation (child runs are structurally tool-less and delegation-less in v1 — depth-1).
- `connection` attachment targets for Node Builder (backend validates them; **no frontend
  connection-drop UI exists** — v1 roster declares `canvas` only; recorded as a deviation from
  dev/15 §3.4 to revisit with a connection-attach UI).
- `agent.package-recommendation` in `delegatesTo` (specified in dev/16 but absent from the runtime
  roster — listing it would mint unsatisfiable install proposals; add it to `delegatesTo` when
  dev/16 ships; deviation recorded).
- `settingsDefaults` profile families (`mutation-proposal` etc.) — profile families are not yet a
  runtime concept; Node Builder rides the existing three-scope policy system like every built-in.
- Edge/connection creation by the agent (`node.create` creates an unconnected node; connections
  remain Connection Builder / user territory until a consumer defines reviewed edge semantics).
- **Unreviewed or non-factory node-type creation** (owner policy above): `node.create`
  instantiates registered templates only; the creation fallback (`node.template.create`, §3.2b)
  is reviewed, justification-carrying, and executes solely through the existing package factory —
  no parallel template-registration path, no registry writes from the agents module.
- Package *assembly* (multi-node reusable packages, the Package Recommendation composition) —
  future memo per the policy note above.

## 3. Recommended Implementation Approach

### 3.1 Roster entry (manifest surface per dev/15, minus recorded deviations)

```python
BuiltinAgentSpec(
    "agent.node-builder", "Node Builder", "node",
    "Create computation, transform, visualization, or data-fetch nodes as reviewable proposals; "
    "delegates content generation to Node Content Builder.",
    "node_build_instruction.txt",
    ("node.build", "dataset.fetch.author"), ("authoring",),
    targets=("canvas",),                       # dev/15 also names "connection" — deferred (no UI)
    reads=("nodeIntent", "targetContext", "externalSelection"),
    tools=("dataflow.read", "node.create", "node.template.create"),
    delegates_to=("agent.node-content-builder", "agent.execution-subtask-planner"),
    review_policy="review-before-apply",
)
```

`build_builtin_manifest` passes `delegatesTo` and `runtime.reviewPolicy` through (defaults:
`()` / `"report-only"` keep the thirteen existing manifests **byte-identical** — regression-tested).
The net-new instruction (dev/15 §3.3: no migrated source) is authored in `llm-prompts/` beside the
migration assets so `PROMPT_SOURCE_DIR` resolution, upload-independence, and the
`_materialize_builtin` heal all work unchanged. It teaches the reuse-first procedure: pick a nodeType **only from the available-templates list the
runtime appends at run time** (§3.2 — the prompt bytes never bake in template ids, so newly
installed packages need no prompt edit); delegate content generation via `delegateRequest` when
content is nontrivial; then emit ONE `node.create` toolRequest; **only when no listed template can
adequately hold the task**, fall back to `node.template.create` with a written justification
naming the templates considered (§3.2b); never claim a node or type exists before the user
applies; never invent a type id.

### 3.2 `node.create` — the first graph-shape mutation (existing node types only)

Tool contract (mutate): params `{"nodeType": <canonical template id>, "content": <str>,
"goal"?: <str>}`. `nodeType` is a canonical `<packageId>/<templateId>` (the same identifiers the
canvas already uses — `constants.ts` `NodeType` values are exactly these strings), validated
against the **existing package registry**, never a hardcoded list:

- A new thin read helper in the packages domain (`ADR-AG-007`; e.g.
  `packages.services.available_template_ids(user_key, project_id)`) enumerates the canonical
  template ids of the seeded `curio.builtin@<major>` package plus every package in the project's
  package lockfile (`get_project_lockfile`), reading `TemplateManifest` entries the domain already
  parses (`packages/manifest.py:150`). The agents module consumes this helper; it owns no template
  knowledge of its own.
- Minting refuses a `nodeType` outside that set, and refuses `content` for a template that is not
  content-authorable (`has_code`/`has_grammar` false) — reuse over invention, fail-closed.
- So the model picks only real, currently-available types, the run's tail instruction lists the
  available templates (id + label + one-line description from the manifest, bounded) when
  `node.create` is granted — composed server-side at run time from the same helper, so it is never
  stale and never hallucination-fed.

A `dataset.fetch.author` outcome is an ordinary `curio.builtin/data-loading` node whose content is
the fetch code — an existing template instantiated, not a new node kind (dev/15: Node Builder owns
the executable fetch node). Only when no available template fits does the agent fall back to
§3.2b — never to an invented type id.

### 3.2b `node.template.create` — the justified creation fallback (factory-backed, reviewed)

Tool contract (mutate): params `{"justification": <str>, "template": {label, description, engine,
editor, inputPorts, outputPorts, content}}`. The tail instruction states the order of operations
explicitly: request this **only after** `node.create`'s available-templates list has been
considered, and the justification must name the closest existing templates and why each is
inadequate — the runtime cannot judge adequacy, so the **review card is the adequacy gate**: it
renders the justification verbatim above the template definition, and the user's Apply is the
policy decision.

**Minting**: validate the draft against the same constraints the palette Save-as flow enforces
(engine ∈ {python, javascript}, editor/ports shapes per `TemplateManifest.from_json`, content
bounds); refuse a label/slug that collides with an available template (that is reuse territory —
the refusal text says so). Summary: "Create a new custom node type · \<label\>".

**Apply** (one explicit review covering both stated effects, printed on the card): drive the
**existing factory** — build a single-template draft-package envelope using the same conventions
as `palettePackageFactoryDraft.ts` (`buildFactoryInstallEnvelope`; server-side equivalent over
`build_packageage_archive` + the factory install service), install it to the user store **and the
project's package lockfile**, then insert the first instance node into the saved spec (server-
minted id + placement, exactly §3.2's apply). Response carries `createdTemplate` + `createdNode`;
the canvas bridge (§3.3) additionally registers the new descriptor client-side through the
existing package-registry bootstrap refresh (`registry/packageRegistryBootstrap.ts` — the same
pulse the Save-as flow triggers) before inserting the node, so `UniversalNode` resolves it without
a reload. Factory validation failures surface as refusal results at mint or as a 409 with the
factory's verbatim error at apply — never a half-registered package (the factory's atomic staging
already guarantees this).

**Proposal minting** (`_mint_proposal` dispatch branch): validate nodeType via the helper as above,
content non-empty and ≤ `PROPOSAL_CONTENT_MAX_CHARS`, spec exists. Summary: "Create a new
\<label\> node". **Revision basis for a creation**: there is no target whose drift can corrupt —
the node id is generated server-side **at apply time** (collision-impossible), so the proposal pins
no content digest; `REQ-REVIEW-001` is satisfied by the unchanged structural gate (mint-only loop,
authenticated apply endpoint, explicit user action). State this reasoning in code where the digest
would otherwise be.

**Apply** (`apply_proposal` dispatch branch): under the spec write path — **re-validate the
template against the helper** (a package uninstalled between mint and apply → 409, proposal
`stale`, card explains — the creation analogue of dev/41's digest drift), generate the node id,
compute a placement to the right of the current node extent, append
`{id, type: nodeType, content, goal, x, y}` to `dataflow.nodes`, mark `applied`, append the result
card turn ("Applied: node created · \<id\>"), and return the **`createdNode` payload** in the apply
response for the frontend bridge. `mutation_applied` semantics identical to dev/41.

### 3.3 The apply→canvas bridge (fixes the §1.3 clobber for both mutations)

New `utils/agentCanvasEvents.ts` (typed mirror of `agentsPaletteEvents.ts`):
`notifyAgentCanvasMutation({kind: "node-created", node} | {kind: "node-content-applied", nodeId,
content})`. `AgentAttachmentsProvider.applyProposal` reads the apply response and dispatches it. A
listener hook (`useAgentCanvasMutations`, mounted in `AgentDockOverlay`, which already holds
`useReactFlow` + `useFlowContext`) applies it to the live canvas: `node-created` →
`FlowProvider.addNode` with `CURIO_UNIVERSAL_NODE_TYPE`, `data.nodeType` = the canonical template
id, `data.code` = content, `data.goal`, position from the payload — rendered by the existing
`UniversalNode` + client `nodeRegistry` descriptor lookup, which is guaranteed to resolve because
validation ran against the same project package set (no new node component, no registry writes); `node-content-applied` → update the
matching live node's `data.code`. Saved spec and live canvas now agree the moment apply succeeds —
the next canvas save re-posts the same state instead of clobbering it. The `node.content.write`
half is a **bug fix to shipped dev/41 behavior** and gets its own regression test.

### 3.4 Delegation (DEC-046 — the P5 seam)

**Model surface.** A new exclusive tail part `delegateRequest`
`{"capability": "node.content.generate", "inputs": {...}}` — parsed in `content.py` with the same
grammar posture as `toolRequest` (one per reply, bounded params, alongside-text tolerated,
runtime-emitted parts unspoofable). A delegate round consumes a round from the same
`MAX_TOOL_ROUNDS` budget — one shared bound, no second knob.

**Resolution** (`delegation.py`, pure): walk the parent manifest's `delegatesTo` **in order**
(dev/15: order = preference; deterministic selection) and return the first entry that (a) is
installed as a template in the **current project** (`project_agents` lockfile — the same source of
truth dev/47 standardized on) and (b) declares the requested capability. A `delegatesTo` entry
visible in the catalog but **not installed** → missing specialist: mint a reviewed
`project.install` proposal (tool `project.install`, payload = coord + project; its apply branch
calls the existing `install_in_project` service — reviewed install, `REQ-ORCH-001`, no
auto-chaining) and return a synthetic result telling the model the specialist awaits the user's
review. Unresolvable capability → plain refusal result the model recovers from. Resolution never
consults other projects' templates.

**Child run** (`delegation.run_delegate`): synchronous, single provider call, composed from the
**delegate's own** preamble + instruction + the parent-supplied `inputs` framed as one bounded
untrusted context message (the dev/44 framing pattern). Structurally fail-closed: the child's
system content includes **no tail instruction**, and its reply is **not** parsed for
`toolRequest`/`delegateRequest` — depth-1 by construction, so dev/15's cycle detection is satisfied
structurally rather than by bookkeeping. The child gets its **own execution record** — own pins,
own ledger reserve→settle under the **child agent's** effective policy (correct quota/budget
attribution; `attachmentKey` = the parent's attachment for per-attachment attribution), own
`executionId`, plus `parentExecutionId` = the parent run's id (dev/15 §4). The child record rides
the parent turn's execution record under `delegations: [...]` (additive, exactly like
`toolCalls`). The child's reply text returns to the parent loop framed as untrusted data
(`[delegate result] agent.node-content-builder (node.content.generate): ...`). A child failure —
provider error, child quota 429, missing prompt — is a framed result the parent recovers from,
never a parent-run error; completed parent work is preserved (dev/15 §4 partial-failure posture).

**Events.** `delegate_requested` (capability + resolved coord) → `delegate_started` →
`delegate_result` (status + duration), streamed between the parent's rounds; the non-streaming path
records the same facts in `delegations`.

**Why not LangChain here (DEC-046).** One synchronous child call under server-authoritative
resolution, independent policy admission, and a mandatory review pause is ~200 lines of direct
code; expressing it as a LangChain/LangGraph executor adds a dependency and an abstraction layer
while *removing* structural guarantees (depth-1, no-nested-tools) that would become configuration.
Dataflow Builder — parallel children, plan/evaluate cycles, resumable partial failure — is where a
graph executor pays; that memo re-opens `DEC-007` with this slice's usage data in hand.

## 4. Data and State Handling

- **Source of truth.** The roster manifest (validated through `parse_agent_manifest`, so
  `delegatesTo`/`reviewPolicy` can never drift from the contract); the project lockfile for both
  installed-state (dev/47) and delegation resolution — one truth, two consumers. Proposals live
  where dev/41 put them (turn part + `activeProposal` mirror); the apply response is the only
  carrier of `createdNode` (the bridge never re-derives it).
- **Execution records.** Parent: `pins.tools` includes `node.create`; `delegations` lists child
  records `{executionId, coord, capability, status, durationMs, usage, costUsd}`. Child: full
  record with `parentExecutionId`. Ledger: two independent reserve→settle pairs keyed by each
  execution id — aggregates and budget gates need no schema change (`DEC-044` keyed-by-execution
  design absorbs this).
- **Loading/empty/error/success.** Delegate activity renders as transient system lines (exact
  tool-activity pattern: live during the run, gone on rehydrate — durable truth is the execution
  record). Proposals render/persist exactly as dev/41 cards. Apply success updates saved spec +
  live canvas in one user action; apply failure (409/404) leaves the canvas untouched.
- **Race safety.** Node creation cannot go stale (id minted at apply). Install proposals re-check
  at apply (already-installed → idempotent success path with a result card, not an error). The
  canvas bridge is idempotent per proposalId (a re-fired event must not double-insert — guard by
  node id existence in the live graph).

## 5. UI and UX Requirements

- **Attach/run.** Node Builder appears in the Global Catalog, installs/imports like any built-in,
  and drags onto the **canvas** (dock tile, DEC-042 chat). Grounded context (dev/44) already gives
  it the live graph on every send — no new wiring.
- **Review cards.** `node.create`: title "Create a new \<label\> node", the content as the
  plain-text preview (existing SafeAgentContent path), Apply/Dismiss system controls unchanged.
  `project.install`: title "Install \<Agent Name\> in this project", one-line rationale (which
  capability needed it), Apply = the reviewed install. `node.template.create`: title "Create a new
  custom node type · \<label\>", the **justification rendered verbatim first** (it is what the
  user is judging), then the template definition (engine, editor, ports) and content preview, and
  an explicit two-effects line ("registers the node type in this project + adds the first node").
  Applied/stale/dismissed/superseded chips identical to dev/41.
- **After apply.** The created node appears immediately on the canvas at the computed position —
  no reload, no flicker, selected state untouched; the transcript shows the result card. Same-turn
  consistency for `node.content.write` (live editor shows the applied content).
- **Delegate lines.** "Delegating to Node Content Builder…" → "· done (1.2s)" transient lines in
  the chat, aria-live polite like tool lines.
- **No new action patterns**: no per-row buttons, no bespoke card buttons beyond the sanctioned
  Apply/Dismiss review controls, no publish/share surface (D-0 = B).

## 6. Edge Cases

- Delegate installed but its prompt not materialized → the existing heal path runs; still failing →
  framed child error, parent recovers.
- `delegateRequest` for a capability not in `delegatesTo`, or from an agent with no `delegatesTo` →
  refusal result; no resolution against the wider catalog ever happens.
- Missing specialist proposal applied twice / template already installed → idempotent success.
- Round budget exhausted before the model emits `node.create` → final-round suffix already forces a
  text answer ("no further tool calls"); the model reports what it would create.
- `node.create` with an id-spoofing param (`"id"` in params) → ignored; ids are server-minted at
  apply only. nodeType not in the project's available template set (or content on a
  non-authorable template) → refusal result. Content at the bound → accepted; over → refused.
- Package providing the proposed template uninstalled between mint and apply → apply re-validation
  409s, proposal `stale`. Package installed mid-conversation → next run's tail lists it (composed
  fresh per run).
- `node.template.create` whose label/slug collides with an available template → refusal steering
  to reuse; collides with an existing store package id → the factory's collision handling
  verbatim (409 at apply, proposal `stale`). Malformed ports/engine → factory-shaped refusal at
  mint. Factory build fails at apply → 409 with the verbatim error, nothing half-registered,
  no node inserted (the two effects are one transaction: template first, node only on success).
- Justification empty or missing → mint refuses (`the review needs your reasoning — state which
  existing templates you considered and why they don't fit`).
- Apply with the project deleted mid-review → existing 404 path. Two pending proposals → newest
  supersedes (unchanged).
- Canvas bridge fires but the node id already exists live (double event, hot reload) → no-op.
- Child run exhausts the child agent's daily quota → framed 429-shaped result; the parent's
  reservation settles normally; nothing about the parent is charged for the child.
- Old client / new server: unknown `delegate_*` events and proposal kinds degrade to the generic
  card shell, informational only (same tolerance contract as T2).
- The user asks Node Builder to *modify* an existing node → it has no `node.content.write` grant;
  the instruction routes it to say the Node Content Builder attachment owns that (or delegate
  content generation and propose a *new* node when that is what was asked).

## 7. Testing Strategy

Backend (`utk_curio/backend`, pytest):
- **Roster/manifest**: node-builder manifest validates; `delegatesTo`/`reviewPolicy` round-trip;
  thirteen existing manifests byte-identical (regression); net-new prompt asset resolves +
  materializes; catalog/import/install/attach lifecycle for the new coord.
- **content.py**: `delegateRequest` grammar (exclusivity, bounds, one-per-reply, spoofed
  runtime parts rejected); tail instruction mentions delegation only with resolvable delegates.
- **delegation.py**: order-deterministic resolution; current-project-only (installed elsewhere →
  missing); missing → `project.install` proposal + synthetic result, **never** an install call
  (`REQ-ORCH-001` by name); unresolvable → refusal; child run composes the delegate's own prompts,
  no tail instruction in the child system content, child reply never parsed for requests (depth-1
  structural test); child execution record pins + `parentExecutionId` + own ledger pair
  (attribution: child coord policy, parent attachmentKey); child failure → framed result, parent
  completes.
- **packages helper**: `available_template_ids` returns `curio.builtin` + lockfile-package
  templates only (a package installed to the store but not the project is absent); authorability
  flags surfaced; bounded output.
- **node.create**: mint validates via the helper — never a hardcoded list (assert no template-id
  constant exists in the agents module); refusals for unknown template / non-authorable content;
  bounds, no digest, summary → `review_required`; apply re-validates (uninstalled package → 409 +
  `stale`), inserts under the lock with server-minted id + placement, result card,
  `mutation_applied`, response carries `createdNode`; params-id spoof ignored; injection
  resistance re-run (no text path reaches apply — the dev/41 test extended to the new tools);
  grant-time tail lists available templates (and changes when the lockfile changes);
  `project.install` apply = reviewed install, idempotent second apply; dismiss paths.
- **node.template.create**: mint validates draft shape via the packages domain + refuses
  missing/empty justification and reuse-territory collisions; apply drives the real factory
  (build + store install + project lockfile + first node insertion, transactional — template
  registered and node inserted together or neither); factory failure → 409 verbatim + `stale`;
  reuse-first ordering asserted in the tail instruction text; the created type is instantiable by
  a plain `node.create` in the next run (round-trip test).
- **Loop**: delegate round consumes the shared round budget; SSE ordering
  `delegate_requested/started/result` (stream test).

Frontend (`npx jest` via the curio-feat conda env):
- Review card renders both new kinds (+ chips); apply wiring passes `createdNode` to the bridge.
- `agentCanvasEvents` unit tests; `useAgentCanvasMutations`: node-created → `addNode` with
  canonical type mapping; node-content-applied → live `data.code` update; double-event no-op.
- **Regression (the §1.3 defect)**: applied `node.content.write` updates the live node so a
  subsequent save posts the applied content.
- Delegate transient lines render and clear on finalize; stream parser tolerates the new events.
- Full suites green (backend ~405+ agents tests, frontend 617+); rule-9 share suite re-run
  (delegations carry no agent-private data into shares).

## 8. Acceptance Criteria

- [ ] `agent.node-builder` is browsable, importable, installable, attachable (canvas), and runnable
      with the net-new instruction + preamble; the thirteen prior manifests are byte-identical.
- [ ] Asking for a new node yields a reviewable `node.create` proposal; **only** the authenticated
      apply endpoint mutates; apply inserts the node into the saved spec **and** the live canvas in
      one action, with a result-card turn; the id is server-minted at apply.
- [ ] **Reuse-first is enforced end-to-end**: `node.create` instantiates only registered templates
      available to the project (registry-validated at mint *and* apply, no template-id constant in
      the agents module); `node.template.create` is the sole creation path — reviewed, refused
      without a written justification, executed only through the existing package factory; the
      frontend renders both outcomes through the existing `UniversalNode`/`nodeRegistry` path (the
      new-type case via the same registry-bootstrap refresh the Save-as flow uses).
- [ ] Applied `node.content.write` content now reaches the live canvas too, and a subsequent canvas
      save no longer clobbers either mutation (regression-tested).
- [ ] A `delegateRequest` for `node.content.generate` runs Node Content Builder as a depth-1 child:
      own execution record + ledger pair + policy admission, `parentExecutionId` link, framed
      untrusted result, `delegate_*` events; a child failure never fails the parent run.
- [ ] A missing installed delegate yields a reviewed `Install in project` proposal; nothing
      auto-imports/installs/attaches/runs (`REQ-ORCH-001`); resolution is current-project-only and
      deterministic by `delegatesTo` order.
- [ ] DEC-046 recorded (dev/03 table + 2.1); deviations from dev/15 recorded in §2 (connection
      target deferred; package-recommendation delegate deferred; profile families not a runtime
      concept yet).
- [ ] No new sharing surface; injection-resistance and rule-9 suites pass.

## 9. Recommended Commit Breakdown

1. `Roster + manifest surface: delegates_to/review_policy fields, agent.node-builder entry, net-new instruction asset, with byte-parity regression tests`
2. `node.create: registry contract + packages-domain availability helper + proposal mint/apply dispatch + createdNode payload, with tests (dev/48)`
3. `Delegation seam: delegateRequest part, delegation.py resolution + depth-1 child run, project.install proposal, ledger/record wiring, SSE events, with tests (DEC-046)`
4. `node.template.create: justified creation fallback over the existing package factory (mint validation, transactional apply, round-trip), with tests`
5. `Frontend: apply→canvas bridge (node-created + node-content-applied regression fix), review-card kinds incl. the justification-first template card, registry-bootstrap refresh, delegate activity lines, with tests`
6. `Docs + ledgers: dev/48 implemented, DEC-046 in dev/03 + 2.1, BL-P5 entry, docs/AGENTS.md`

## 10. Engineering Quality Checklist

- [ ] Mutation authority remains structural: mint-only loop, apply-endpoint-only execution — no
      flag anywhere whose flip lets the model mutate or install.
- [ ] Depth-1 delegation is structural (no child tail instruction, child output never parsed), not
      a counter.
- [ ] One source of truth per fact: agents lockfile (installed + delegation resolution), package
      registry/lockfile (creatable node types — via the packages-domain helper, no duplicate
      template knowledge), roster manifest (contract), apply response (`createdNode`), turn parts
      + mirror (proposals).
- [ ] No duplicated business logic: proposal/apply become a dispatch over existing machinery; the
      canvas bridge mirrors the palette-events utility; child runs reuse `_resolve_prompt_text`,
      policy, ledger, and record helpers.
- [ ] Existing manifests, grant-less runs, and T2 clients byte-/behavior-identical (regression
      tests named).
- [ ] Types explicit end-to-end (registry contract, part grammar, apply payload, TS event types).
- [ ] Accessibility: new card kinds and delegate lines follow the existing aria-live/labeling
      patterns.
- [ ] Reuse-first is structural, not just prompted: instantiation validates against the registry,
      creation is a distinct reviewed contract that cannot fire without a justification, and both
      execute only domain-owned packages code (factory + install services) — the agents module
      writes nothing to the registry itself.
- [ ] The LangChain seam is one module boundary (`delegation.py`), documented for the Dataflow
      Builder revisit (DEC-046); the factory-backed creation seam is likewise one contract, ready
      for the Package Recommendation composition to reuse.
