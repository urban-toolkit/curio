# dev/126 — Node-attached dataset discovery: the Dataset Finder is a Dataflow Builder dependency, attached to the data-loading node it resolves

**Status: IMPLEMENTED (2026-09-10) on `imp/agentcatalog` — `DEC-080` minted,
`BL-P5-20260910-60`. Nine commits: `32235ebd` (this memo), `3506446e` (one attach helper,
one node-compatibility predicate, one remedy sentence), `650536d8` (`DEC-080` + the
declaration), `e9a6c2ac` (both apply paths attach and say so), `943ad114`
(`dataset_resolution.py`), `3599b35c` (resolution initiates discovery), `4a30196f` (the
selection endpoint + the surfaces), `68fa2fd9` (the three instructions),
`1156e62b` (docs + ledgers) and `6b6d27f9` (the ledgers repointed to the hashes the
trailer strip renumbered). The plan's commit 7 split in two: the prompt edits move the Dataflow
Builder's byte pin, which belongs with the edit rather than with the docs. Every line number
below was read on `573451df`.**

**Hashes renumbered 2026-09-10 (owner request):** every commit of this phase and of dev/125
was rewritten to drop the `Co-Authored-By` trailer, message-only — the trees are byte-identical
(`git diff` between the old and new tips is empty). The hashes above and in
`BL-P5-20260910-60` are the current ones; a note elsewhere quoting `a6437932`…`e3ad9192`, or
`e4367765` for this memo's base, is naming the same commits before that rewrite.

**Suites: `tests/test_agents` 2236 passed (2189 before); `tests/test_projects` +
`tests/test_datasets` 769; jest 2390 across 205 suites; `tsc --noEmit` clean.**

**Six things changed from the plan while building — each recorded in §12.** The
load-bearing one: the memo's single pre-round discovery check would have fired on every
project with a non-empty Data Catalog, which is every shipped install, so discovery is
initiated in TWO stages instead of one. F3 records the strict variant, which is one
predicate away.

Date: 2026-09-10
Branch / tree: `imp/agentcatalog` @ `573451df` (clean but for the untracked `plans/…/results`,
`knowledge-graph/` and one computed-dataset directory).
Origin: owner request — "The dataset finder must always be initiated when resolving a
data-loading node, and it should be attached directly to that node. It should be modified to
function as a node-attachable agent, which would automatically link to the data-loading node
whenever a dataflow plan is applied. The flow currently occurring in this project:
`http://localhost:8080/dataflow/667a4b6c-519d-4924-904a-af8d6bc2939a` must not happen. The
dataset finder should be treated as a DFB agent dependency, similar to how the node content
builder operates. Additionally, the node builder should always be attached to a node when a
dataflow plan is being applied."
Family: dev/50 (Dataset Finder, the two-lane card, `node_requires=("data-loading",)`) →
dev/52 (the plan lane) → dev/71 (auto-attach on the per-node apply) → dev/72 (the delegation
home) → dev/106 (`DEC-068`, the required-delegate closure) → dev/114 (`DEC-072`, source
grounding + the tool-less discovery delegate) → dev/115/118 (`DEC-073`/`DEC-075`, Solve) →
dev/116 (connection keys) → **dev/126 (this memo)**.
Design decisions consumed: `DEC-006` (nothing mutates without review), `DEC-040`
(graph-backed state), `DEC-046` (the tool-less delegate seam), `DEC-047` (the user-mediated
external hand-off), `DEC-053` (the egress chokepoint), `DEC-063` (an instruction must be
executable on every path its agent runs on), `DEC-068` (the required-delegate closure),
`DEC-072` (source grounding), `DEC-073`/`DEC-075` (Solve), `DEC-079` (evaluation runs the
normal lifecycle), `REQ-ORCH-001` (the orchestrator never installs silently).

---

## 0. The investigation answer, first

**The reported flow is reproducible from disk, and it is four separate defects, not one.** The
project the owner names is on this machine:
`.curio/users/31/projects/667a4b6c-519d-4924-904a-af8d6bc2939a/spec.trill.json`. Its dataflow
has **zero nodes and zero edges**. Its lockfile holds three agents, and its single attachment
is the Dataflow Builder on the **canvas**, carrying an `activeProposal` of tool
`project.install`, coord `agent.dataset-finder@1.0.0`, summary *"Install Dataset Finder in
this project"*, status `applied`.

The session file (`agent-sessions/7c300d0dd6584954b3a8026c7433eda2.json`, five turns) shows
the whole flow:

1. **user** — "Our goal is plan and build a entire dataflow to compare chicago
   neighborhoods… find datasets about population density, community areas boundaries and
   fetch them…"
2. **agent** — "Since I do not have the dataset IDs yet, I will start by delegating the
   discovery process", plus a `proposal` part and a `suggestedPrompts` part. **No plan was
   proposed.** The proposal is the install.
3. **agent** — "Applied: `agent.dataset-finder@1.0.0` installed in this project."
4. **user** — "I have installed the Dataset Finder, please find the Chicago datasets now."
5. **agent** — empty.

So the user's goal cost two extra clicks, one re-typed instruction and one wasted model turn,
and the canvas is still empty. The four causes:

- **The dependency is not declared.** `builtin.py:285` gives the Dataflow Builder exactly one
  `requires_agents` entry — `agent.node-content-builder`. The Dataset Finder is only a
  *preferred delegate* (`builtin.py:265`), so the first `dataset.discover` delegation resolves
  `not-installed` (`services.py:9371`) and mints the reviewed `project.install`
  (`_mint_project_install`, `services.py:8118`). That proposal is *correct behavior for an
  undeclared delegate*; the fault is the declaration.
- **The orchestrator blocks planning on dataset identity.** `orchestration_instruction.txt:19`
  says to "direct them to their Dataset Finder attachment (it owns discovery)" — an attachment
  that, in this flow, does not exist on any node, because no plan has been applied yet. Nothing
  in the procedure says *plan first, resolve sources at the node*. The model reasoned exactly
  as instructed and stalled.
- **A whole-plan Apply attaches nothing.** Of the two apply paths, only the per-node one
  attaches an agent: `apply_plan_node` calls `_attach_node_builder` at `services.py:1910`
  (`_attach_node_builder` itself at `:1805`). `_apply_dataflow_plan` (`:2999`) — the path the
  review card's Apply button uses — touches attachments only to *prune* orphans (`:3110`). A
  plan applied as a whole therefore yields nodes with no agent; dev/72's `_delegation_home`
  later creates Node Builder attachments **lazily** (`:8198`), so which nodes have an agent
  depends on which delegations happened to run.
- **Nothing initiates discovery when a data-loading node is resolved.** Solve hard-invokes
  `node.content.generate`; with no grounded source the content builder declines and the
  decline is terminal (`services.py:6296`-`6323`, `kind = "source-missing"`, `break`). The
  failure text then tells the *user* to do by hand what the runtime could do itself —
  *"resolve the source with Dataset Finder (attach it to this node) or give the path"* — a
  string that exists in **three** copies (`:4170`, `:4199`, `:4649`).

A fifth, supporting fact: even when `dataset.discover` *is* delegated for a node, its work
homes at that node's **Node Builder** attachment (`_delegation_home`, `:8188`-`:8201`), and the
candidates part is minted on the **parent's** turn (`_mint_candidates_from_delegate`, `:7972`).
No code path in the tree ever creates a Dataset Finder attachment on a node — even though
dev/50 already declared the agent node-compatible with `node_requires=("data-loading",)`
(`builtin.py:243`). The agent the owner is asking for is 90% built and 0% reachable.

---

## 1. Problem Statement

### Current behavior

**D1 — the Dataset Finder is an optional delegate of an orchestrator that cannot work without
it.** `builtin.py:247`-`:290`: the Dataflow Builder lists twelve preferred delegates including
`agent.dataset-finder` and `agent.node-builder`, but declares only
`requires_agents=("agent.node-content-builder",)`. A fresh install of the Dataflow Builder
therefore lands two of the three agents its own procedure depends on, and the third arrives
only after the model discovers its absence mid-conversation, mints an install proposal, and the
user clicks Apply and re-asks. `install_in_project` (`:533`) already installs a whole closure
in one spec write; nothing about the mechanism is missing — only the declaration.

**D2 — the plan is hostage to dataset identity.** The orchestration instruction never tells the
agent that a data-loading node may be planned with an honest intent and resolved later, and
step 6 points at an attachment that does not exist before the first Apply. Observed
consequence, verbatim from the live session: *"Since I do not have the dataset IDs yet, I will
start by delegating the discovery process"* — the plan the user asked for was never proposed.

**D3 — auto-attach exists on the path almost nobody uses.** `apply_plan_node` (the Simulation
Mode per-node apply, `:1838`) attaches the Node Builder; `_apply_dataflow_plan` (the whole-plan
apply, `:2999`) does not. Both create nodes from the same plan, in the same review, on the same
proposal. Two paths, two behaviors, and the difference is invisible to the user. `_attach_node_builder`
is also silently best-effort by contract (`:1807`-`:1809`, "Skips (returning None) when the
template is not installed"), so a node can end up agent-less with nothing said anywhere.

**D4 — resolution never initiates discovery.** For a data-loading node with no grounded
source, every Solve path ends in one of two failures — `ungrounded-source` (the gate refused a
fabricated path or unverified URL) or `source-missing` (the content builder declined) — whose
remedy text asks the user to attach the Dataset Finder manually and re-drive it. The runtime
holds every piece needed to do this itself: a tool-less discovery delegate whose catalog input
and reply schema it already supplies (`_dataset_discover_inputs`, `:8025`), a runtime-minted
two-lane candidates part with real verification verdicts (`_mint_candidates_from_delegate`,
`:7972`), and a declared node-compatible agent to own the conversation.

**D5 — a data-loading node has no place for discovery to live.** `_delegation_home` (`:8172`)
homes *all* node-scoped delegated work at the node's Node Builder attachment. Discovery
candidates for node X therefore appear in the chat of the agent that writes X's code, and the
Dataset Finder — the agent that owns discovery, that the failure text tells the user to attach,
and whose manifest already restricts it to `data-loading` nodes — is never attached to anything
by any code path.

### Expected behavior

- **R1** Installing the Dataflow Builder installs the Dataset Finder, the Node Builder and the
  Node Content Builder, in one write, at the user's click — and a `project.install` proposal for
  one of its own required agents never appears in a Dataflow Builder conversation again.
- **R2** Applying a dataflow plan attaches, to every node the apply creates: the **Node
  Builder** always, and the **Dataset Finder** additionally when the node's canonical type is a
  `data-loading` one. Both apply paths behave identically, and the apply *reports* what it
  attached instead of silently returning `None`.
- **R3** Resolving a data-loading node whose source is not already grounded **initiates
  discovery** — the runtime delegates `dataset.discover` itself, the candidates land in that
  node's Dataset Finder chat, and the node's Solve outcome is `pending — awaiting your dataset
  selection`, never `failed`. A node whose source *is* already grounded skips discovery and
  says so in the trail.
- **R4** A confirmed selection is a **recorded fact** on the node's Dataset Finder attachment,
  derived from the runtime's own persisted candidate rows — so the next Solve of that node knows
  the source without asking the model what the user picked.

### Why it matters

Correctness and truthfulness first: the current end state of a data-loading node is a failure
message naming a remedy the product will not take, and a chat that says *"I will delegate
discovery"* while proposing an install. Usability second: the owner's four-step detour is the
first thing every new dataflow hits, because data loading is the first step of every dataflow.
Consistency third: two plan-apply paths disagree about whether nodes get agents, and one
remedy sentence exists in three places.

---

## 2. Scope

### In scope

Backend (`utk_curio/backend/app/agents/`):

- `builtin.py` — `requires_agents` on the Dataflow Builder (`+agent.dataset-finder`,
  `+agent.node-builder`) and on the Node Builder (`+agent.dataset-finder`).
- `services.py` — the closure repair at the point of use; ONE `_attach_plan_node_agents`
  helper called by `apply_plan_node` (`:1910`) and `_apply_dataflow_plan` (`:2999`); the
  discovery initiation in `_verified_content_rounds` (`:6130`) and its two Solve callers; the
  `_delegation_home` capability table (`:8172`); the three copies of the remedy sentence
  (`:4170`, `:4199`, `:4649`) collapsed into one helper beside `_source_missing_remedy`
  (`:5859`).
- `attachments.py` — the pure node-compatibility predicate extracted from `attach_agent`
  (`:816`-`:838`), plus the `datasetSelection` record accessors.
- a new `dataset_resolution.py` — the node source state machine, the selection record, and the
  discovery initiation (kept out of `services.py`, which is already 10 151 lines).
- `routes.py` — the selection endpoint.
- `_apply_dataset_install` (`:3264`) — stamps a catalog pick resolved once its install lands.

Prompts (`utk_curio/llm-prompts/`): `orchestration_instruction.txt` (plan-first + where
sources resolve), `node_build_instruction.txt:12` (ladder rung (c) — the runtime initiates
discovery), `discovery_instruction.txt` (the node-attached posture).

Frontend (`utk_curio/frontend/urban-workflows/src/`): `agentsApi.ts` (the selection call, the
`attachedAgents` and awaiting-selection payloads), `AgentAttachmentsProvider.tsx` (the
selection action), `AgentDatasetCandidatesCard.tsx` (Confirm records the selection, then keeps
its existing prompt behavior), `AgentBuilderStrip.tsx` (the awaiting-selection reason + an
**Open Dataset Finder** action through `ctx.openChat`).

Docs / ledgers: `docs/AGENT-CATALOG.md` (roster requirements, the node-attached discovery
lane, the resolution copy), `docs/USAGE.md` (the data-loading walkthrough), dev/03 (`DEC-080`
row), dev/00 (the index row), `BL-P5-first-release-orchestration.md`
(`BL-P5-20260910-60`), this memo's status.

Tests: `test_builtin.py`, `test_manifest.py`, `test_delegation.py`, `test_routes.py`,
`test_attachments.py`, `test_source_grounding.py`, a new `test_dataset_resolution.py`; jest
`AgentBuilderStrip.test.tsx`, `AgentDatasetCandidatesCard.test.tsx`,
`AgentAttachmentsProvider` tests; one dev/121 harness fixture for the plan-first flow.

### Out of scope (unless the requested behavior forces it)

- `_apply_node_create` (`:3722`) and the dev/113 `node.insert` path — a node created by a
  Node Builder proposal attaches nothing today, and the owner's instruction is about **plan**
  apply. Recorded as **F1**.
- `agent.dataset-finder`'s own `requires_agents` — its external-lane hand-off to the Node
  Builder stays user-mediated (`DEC-047`), so no server path of the Dataset Finder invokes
  `node.build`; the criterion `DEC-068` sets is not met. (In a Dataflow-Builder project the
  Node Builder is present anyway, by R1.)
- The two-lane card's grammar, the reviewed `dataset.install` lane, the catalog search tool,
  and the `DEC-047` hand-off mechanics beyond the routing copy.
- Retiring `_mint_project_install` — it stays the right answer for a *non-required* delegate.
- Any change to `review_policy`, to the grounding gate's verdicts, or to Solve's waves,
  budgets and deadlines.
- Attachment of agents to non-`data-loading` nodes beyond the Node Builder.

### Related code paths that must be checked

`project_agents.preserve_agent_state` and `projects/services.py:655` (attachments are a
backend-owned section — the selection record is safe from a canvas save);
`concurrency.assert_save_keeps_server_work` (dev/124 — the apply's extra attachment write must
not look like loss); `attachments.prune_orphaned_attachments` (`:184` — a deleted node takes
both its agents and the selection record with it); `delegation.required_by` (`:274` — uninstall
refusals grow); `packages_services.canonical_template_id` and
`source_grounding.is_data_loading_type` (`:641`) — the ONE type test; the evaluation service
(dev/123) which installs the Dataflow Builder "with its required closure" and will now install
four agents per run.

---

## 3. Recommended Implementation Approach

### A. Declare the dependencies (one place, no new mechanism)

```python
# builtin.py — agent.dataflow-builder
requires_agents=("agent.node-content-builder", "agent.dataset-finder", "agent.node-builder"),
# builtin.py — agent.node-builder
requires_agents=("agent.dataset-finder",),
```

`DEC-068`'s criterion is *"the subset of `delegates_to` a SERVER code path of this agent
invokes without model choice"* (`builtin.py:84`-`:88`). After §D that is exactly true of the
Dataset Finder for both agents: the resolution path delegates `dataset.discover` itself. The
Node Builder is required by the Dataflow Builder because §C makes every plan-created node carry
one — a server path, at the user's Apply, with no model choice.

Nothing else is needed: `manifest.py:296`-`:314` already enforces `requiresAgents ⊆ delegatesTo`
(satisfied by all three edges), `delegation.required_closure` (`delegation.py:245`-`:270`) is
cycle-safe and depth-bounded — which matters here, because the Dataset Finder's own
`delegates_to` names the Node Builder — and `install_in_project` (`:533`) resolves the closure
before writing, refuses with 409 when a member is visible nowhere, materializes every member and
writes once. The drawer's disclosure (`_requires_agents_rows`, `:131`) then reads **Add to
dataflow (+3 required)** with the three names, and `uninstall_from_project` refuses removing any
of the three while the Dataflow Builder is installed, naming the dependent.

### B. Repair an incomplete closure at the point of use — `DEC-080`

R1 fixes new installs. The owner's project already has the Dataflow Builder installed under the
old declaration, and so does every existing project: a declaration change alone leaves them
mid-flow forever.

**Proposed `DEC-080` — a declared hard dependency is repaired where the user acts on the
dependent, never by the model.** When a run, an attach, a plan apply or a Solve touches an
installed agent whose transitive `requiresAgents` closure is not fully present in the project's
lockfile, the runtime completes the closure through the single existing install path
(`install_in_project`) and discloses it in the transcript — *"Added Dataset Finder — required by
Dataflow Builder."* Bounded to `requiresAgents` members (never a preferred delegate), refusing
before writing when a member is visible nowhere, idempotent, and never a model decision.

This does not weaken `REQ-ORCH-001`. That requirement forbids the *orchestrator* installing
agents by its own choice; a required-closure repair is the deterministic content of an Install
click the user already made — `DEC-068` is what made an install *mean* "this agent and what it
declares it cannot work without". The alternative — keep minting `project.install` for a
*required* member in legacy projects — was considered and rejected: it is precisely the flow
the owner says must not happen, and it would make behavior depend on when the project was
created.

Implementation: `project_agents.ensure_required_closure(user_key, project_id, coord) ->
list[str]` (the coords added), called from `_prepare_run` (before the first model call),
`attach_agent`, both plan applies and both Solve entry points. In
`_resolve_delegate_request` (`:9370`), a `not-installed` resolution for a capability whose
provider is a **required** member of the parent's manifest repairs and retries once; a
non-required delegate keeps `_mint_project_install` unchanged.

### C. One auto-attach helper, on both apply paths, reported honestly

```python
# services.py
_PLAN_NODE_AGENTS = (
    ("agent.node-builder", None),                 # every created node
    ("agent.dataset-finder", "data-loading"),     # data-loading nodes only
)

def _attach_plan_node_agents(user_key, spec, node_id, node_type) -> dict:
    """Attach the plan-node agents to a created node: Node Builder always,
    Dataset Finder for a data-loading node. Idempotent; returns
    {"attached": [{agentId, attachmentId}], "skipped": [{agentId, reason}]}."""
```

- Selection of *which* agents is a declaration (the tuple above), not a branch per call site.
- The `data-loading` test is `source_grounding.is_data_loading_type(packages_services.canonical_template_id(node_type))`
  (`source_grounding.py:641`) — the same predicate the grounding gate and the content loop use.
  No fourth copy of suffix normalization.
- Manifest compatibility is checked through a pure predicate **extracted** from `attach_agent`
  (`:816`-`:838`) into `attachments.node_target_matches(manifest, node_type) -> bool`;
  `attach_agent` then calls it too, so the drawer path and the automatic path can never disagree
  about what "attaches to `data-loading` nodes" means.
- `_attach_node_builder` (`:1805`) becomes a thin call into the helper, and dev/72's
  `_delegation_home` keeps using it (`:8198`).
- `_apply_dataflow_plan` calls the helper for every entry of `created_nodes`, **before** its
  single `write_spec` — one write, as today.
- Both applies return `attachedAgents: [{nodeId, agentId, attachmentId}]` and both applied-turn
  cards gain a line — *"agents attached: Node Builder ×4, Dataset Finder ×2"* — and, when
  something was skipped, the reason. `apply_plan_node` keeps `attachedAgentId` for compatibility
  (`test_routes.py:6456` pins it) with the new field beside it.

### D. Resolution initiates discovery — one lane, in the shared loop

A new module `utk_curio/backend/app/agents/dataset_resolution.py` owns the state and the
initiation, so `services.py` grows call sites rather than policy:

```python
STATES = ("resolved", "unresolved", "candidates-pending", "awaiting-install")

def node_source_state(spec, node_id, *, grounding) -> dict     # pure over the spec
def record_selection(spec, attachment_id, picks) -> dict       # pure; picks already resolved
def initiate(user_key, project_id, spec, node, *, config, run_delegate, parent) -> dict
```

- `node_source_state` reads the node's Dataset Finder attachment record (§E) first: a confirmed
  selection ⇒ `resolved`; a minted-but-unanswered candidates part ⇒ `candidates-pending`; an
  applied-selection whose catalog dataset is not installed yet ⇒ `awaiting-install`. With no
  record it consults the grounding evidence the loop already built — a user-typed path, a
  `curio_dataset_path("<id>")` for an installed catalog id, a URL verified in this
  conversation, or an explicit synthetic request (`source_grounding.synthetic_requested`) ⇒
  `resolved`; otherwise `unresolved`.
- `initiate` is called for `unresolved` only. It ensures the node's Dataset Finder attachment
  (§C's helper — the same code, so the same compatibility rule), delegates `dataset.discover`
  through the existing traced seam (`_run_delegate_traced`, `:8234`) with the enrichment
  `_enriched_delegate_inputs`/`_dataset_discover_inputs` (`:9319`, `:8025`) already supplies,
  mints the part with `_mint_candidates_from_delegate` (`:7972`) — runtime-dropped ungrounded
  catalog rows, `DEC-053` verdicts on external rows — appends it as an agent turn on the
  **Dataset Finder attachment's** session, and stores `candidates-pending` on that record.
  Returns `{"status": "awaiting", "attachmentId": …, "candidates": n}`.
- `_verified_content_rounds` (`:6130`) gains an injected `resolve_source` callable, consulted
  once before round 0 **for data-loading nodes only**. `awaiting` returns the loop outcome
  `{"verdict": "awaiting-source", "evidence": {"kind": "awaiting-selection", "remedy":
  {"kind": "dataset-selection", "attachmentId": …, "nodeId": …}}, "rounds": 0}` — no generation
  round spent, no sandbox call, nothing written. `resolved` proceeds exactly as today, and the
  trail records *"discovery skipped — `<literal>` already grounds this node"* so the "always
  initiated" rule is auditable rather than assumed.
- Both Solve callers map `awaiting-source` to node status **`pending`** with reason *"awaiting
  your dataset selection — Dataset Finder proposed N candidates on this node"* plus the remedy
  payload. `pending` is right and already understood everywhere: the strip's Retry re-runs
  pending nodes, downstream nodes stay `pending` with `upstreamEmpty`, and nothing is recorded
  as a failure of content that was never generated.
- `_delegation_home` (`:8172`) gains ONE declaration — `_HOME_AGENT_BY_CAPABILITY =
  {"dataset.discover": "agent.dataset-finder", "dataset.select": "agent.dataset-finder"}` —
  consulted before the Node Builder default, so discovery work homes at the node's Dataset
  Finder on the chat path too (a Dataflow Builder or Node Builder chat that delegates discovery
  for node X). Every other capability keeps dev/72's behavior byte-for-byte.
- The three copies of the remedy sentence (`:4170`, `:4199`, `:4649`) become one
  `_ungrounded_remedy(attachment_id | None)` beside `_source_missing_remedy` (`:5859`), and it
  now names the node's Dataset Finder attachment when one exists.

### E. A selection is a recorded fact, not a model claim

Candidate rows carry no ids (`content._parse_candidate_row`, `:332`-`:373`), and today the
card's Confirm button only composes a prompt (`composeConfirmationPrompt`,
`AgentDatasetCandidatesCard.tsx:26`). Add one endpoint:

`POST /api/agents/projects/<pid>/attachments/<aid>/dataset-selection`
`{"picks": [{"lane": "catalog", "key": "<datasetId>"}, {"lane": "external", "key": "<url>"}]}`

- The server resolves each pick against the **latest persisted `datasetCandidates` part** in
  that attachment's session; an unmatched key is a 422 naming it. The client sends keys only —
  never a name, path or URL of its own — so a selection can never introduce a source the runtime
  did not itself propose and probe.
- External picks are re-probed through `verify.verify_external_source`, and the stored record
  keeps the verdict. A pick that is now unreachable is recorded as such and does **not** become
  `resolved` (the card says so).
- The record lives on the attachment (`datasetSelection: {status, picks[], recordedAt,
  verifiedUrls{}, installProposalId?}`) with the usual `revision` bump. Attachments are a
  backend-owned section (`projects/services.py:655`), so a canvas save cannot wipe it, and
  `prune_orphaned_attachments` deletes it with the node.
- The card's Confirm calls the endpoint **and then** sends the existing composed prompt, so the
  catalog lane still reaches the reviewed `dataset.install` and the external lane still reaches
  the `DEC-047` hand-off. `_apply_dataset_install` (`:3264`) stamps `awaiting-install` →
  `resolved` for the pick it installs.
- The recorded selection is what §D reads, and what rides into content generation as
  `sourceGrounding.confirmedSource` — the content builder is *handed* the confirmed row instead
  of being told a URL was verified sometime earlier.

### F. Instruction copy (three files, one paragraph each)

- `orchestration_instruction.txt` — a new step 2d: **plan first, never block on dataset
  identity.** A data-loading node is planned with an honest intent naming the data it needs;
  when the plan is applied, each data-loading node gets its own Dataset Finder and each node
  its Node Builder, and the source is resolved at the node (Solve initiates discovery there).
  Step 6's "direct them to their Dataset Finder attachment" becomes true only after an apply,
  and says so.
- `node_build_instruction.txt:12` — rung (c) becomes: for a data-loading node the runtime
  initiates discovery itself and shows the user candidates; build from a **confirmed** row
  (`confirmedSource` in `sourceGrounding`), never from a URL you chose.
- `discovery_instruction.txt` — the node-attached posture: when attached to a node, the mission
  is that node's intent, the candidates resolve that node's source, and the external hand-off
  names that node's own Node Builder.

This is `DEC-063` applied: after §C every instruction sentence about "your Dataset Finder
attachment" is executable on the path the agent actually runs on.

---

## 4. Data and State Handling

| Datum | Source of truth | Written by | Read by |
| --- | --- | --- | --- |
| Which agents a project has | `spec.dataflow.agents` (lockfile) | `install_in_project` only | resolution, palette, drawer |
| Which agents a node has | `spec.dataflow.agentAttachments` | `attach_agent`, `_attach_plan_node_agents` | dock, badges, Solve, `_delegation_home` |
| A node's dataset selection | `datasetSelection` on that node's Dataset Finder attachment | the selection endpoint, `_apply_dataset_install` | `node_source_state`, content inputs |
| Candidate rows + verdicts | the persisted `datasetCandidates` part in the Dataset Finder session | `_mint_candidates_from_delegate` | the card, the selection resolver |
| A node's solve status | `builderSession.nodeRuns` (+ the run's `results`) | the Solve paths | the strip, Retry |
| Whether a source is grounded | derived, never stored | — | the gate, `node_source_state` |

Derived values are computed, not cached: `node_source_state` is a pure function of the spec plus
the loop's grounding context, so a source the user grounds by other means (typing a path,
installing the dataset from the Data Catalog drawer) makes discovery skip without any state
being invalidated.

**Loading / empty / error / success.** Discovery initiation is one delegated model call inside a
detached job that already streams progress; it emits a `dataset_discovery` event so the strip can
say *"asking Dataset Finder for candidates…"* instead of stalling silently. An empty catalog and
an empty delegate reply are already distinguished and reported honestly by
`_mint_candidates_from_delegate` (`no-candidates`), which becomes a **`pending`** node with
*"Dataset Finder found no candidates — give a path or URL"*, not a failure of content. A
delegate/provider error is `pending` with the reason; the run is retryable.

**No duplicated state, no races.**

- Every spec mutation goes through `projects_storage.write_spec` under the spec lock, and each
  apply keeps its single write: the new attachments are added to the same `spec` dict the apply
  already writes.
- Discovery is initiated at most once per node per unresolved state: `candidates-pending` is
  written in the same spec write as the minted turn, and a second Solve in the same batch or a
  concurrent per-node Solve reads it and reports `pending` without spending a model call.
- A selection recorded while a Solve is in flight cannot half-apply: the record is written under
  the lock, and the in-flight node was already `awaiting` (it generates nothing), so the next
  Retry reads `resolved`.
- Applying a plan writes attachments the client has never seen. dev/124's rule refuses **loss**
  (a stale basis plus a dropped node/edge or blanked content), and attachments are carried
  forward by `preserve_agent_state`, so an added attachment neither trips the refusal nor
  survives at the client's expense.
- Deleting the node prunes both attachments, both sessions and the selection record
  (`prune_orphaned_attachments`, `:184`; `detach_agent`'s session deletion for the manual path).

---

## 5. UI and UX Requirements

- **On the node.** `NodeAgentBadges` already renders one badge per attachment with
  `ctx.openChat`; a data-loading node created by a plan apply shows **two** badges (Node
  Builder, Dataset Finder) as soon as the apply's `state.reload()` completes
  (`AgentAttachmentsProvider.tsx:487`) — no new bridge event, no layout shift beyond the badge
  row that already exists.
- **The applied-plan card** names what was attached, in the same truthful register as dev/112's
  removals line: `+6 nodes · +5 connections · agents attached: Node Builder ×6, Dataset Finder ×2`.
- **The Solve strip.** An awaiting-selection node is `pending` (existing pill, existing
  counter), and its reason row reads *"awaiting your dataset selection — Dataset Finder proposed
  3 candidates"* with an **Open Dataset Finder** button that calls `ctx.openChat(attachmentId)`.
  Modelled exactly on dev/116's `AddKeyAction` — the one rendering of a remedy — so a remedy
  payload has one home per kind, not one per surface.
- **The candidates card** gains a recorded-selection state: Confirm posts the selection, the
  chosen rows show a `selected` marker with the verdict chip they already carry
  (`VerificationChip`), and the composed prompt is sent exactly as today. A pick the re-probe
  found unreachable is marked and *not* selectable as resolved, with one honest line saying why.
- **Copy that must not lie.** Nothing says "installed", "selected" or "resolved" before its
  write returns; the closure-repair line names the dependent (*"Added Dataset Finder — required
  by Dataflow Builder"*); a skipped discovery says which literal already grounds the node.
- **Accessibility.** The Open Dataset Finder button is a real `<button>` whose accessible name
  includes the node's title; activating it moves focus into the chat panel (the dev/108 slide
  hook already owns focus on open); the reason row is `aria-live="polite"` so a status change
  from *running* to *awaiting selection* is announced once; the card's selection controls keep
  their existing labelled checkboxes and gain `aria-describedby` for the verdict chip.

---

## 6. Edge Cases

1. **Dataset Finder visible nowhere** (a stripped deployment): `install_in_project` refuses with
   409 before writing; the closure repair surfaces that as one honest line and the Dataflow
   Builder keeps working with the `project.install` proposal as the fallback lane.
2. **Legacy project, Dataflow Builder attached, closure incomplete** — the owner's project:
   repaired at the next run, disclosed, no proposal.
3. **Node Builder uninstalled by a user** while the Dataflow Builder is installed: refused by
   `required_by` (`delegation.py:274`) with the dependent named — a behavior change users must
   be told about in `docs/AGENT-CATALOG.md`.
4. **A plan node whose type is data-loading but versioned** (`pkg/data-loading@2`) or legacy
   (`DATA_LOADING`): canonicalised by the shared predicate, so the Dataset Finder attaches.
5. **A plan re-applied per-node then as a whole** (mixed flow, already supported by
   `already_applied`): attachment is idempotent — the helper returns the existing id.
6. **The plan creates 25 data-loading nodes**: 25 Dataset Finder attachments, one spec write;
   discovery is initiated only for the nodes Solve actually resolves, and Solve's own bounds
   (waves, deadline, `_HEAD_FIRST_KINDS` budgets) are untouched.
7. **Two Solves racing on one node** (batch + per-node): the second reads
   `candidates-pending` and reports `pending` without a model call.
8. **The user picks nothing** and re-presses Solve: `candidates-pending` → `pending` with the
   same reason and the same card (no second delegation, no duplicate candidates turn).
9. **The user picks a catalog row that is not installed**: `awaiting-install`; the reviewed
   install lands, `_apply_dataset_install` stamps `resolved`, Retry solves the node.
10. **A recorded external pick that has gone unreachable** by the time Solve runs: the loop
    re-probes as it always does; the gate refuses, the round fails with `ungrounded-source`, and
    the remedy names the node's Dataset Finder — a *new* discovery is initiated only after the
    selection is cleared, never silently.
11. **A malformed or absent `datasetCandidates` part** when a selection arrives: 422 naming the
    key; nothing recorded.
12. **A selection posted to an attachment of another agent**, or to a canvas attachment: 400 —
    the record lives only on a Dataset Finder node attachment.
13. **The node is deleted while candidates are pending**: pruned with the node; a later
    selection 404s.
14. **A data-loading node the user filled in by hand** (content already grounded): `resolved`,
    discovery skipped, trail line recorded — the per-node Solve's `start_from_current` path is
    unchanged.
15. **Synthetic data explicitly requested** in the goal: `resolved`, no discovery — the
    `synthetic_requested` evidence already exists.
16. **An evaluation run** (dev/123): installs four agents instead of two and now applies plans
    that attach agents; the marker-scoped automated approval covers the same proposal kinds —
    the selection endpoint is **not** one of them, so an evaluation whose fixture needs an
    external source ends at `pending — awaiting selection`, honestly, and its score reflects
    that.
17. **Non-data-loading nodes**: exactly one attachment (Node Builder), as before.
18. **`agentAttachments` malformed on disk**: the pure accessors already tolerate it (`:36`);
    the helper skips with a reason instead of raising inside an apply.

---

## 7. Testing Strategy

**Unit — roster and closure** (`test_builtin.py`, `test_manifest.py`, `test_delegation.py`):
the three new `requiresAgents` edges are present and each is a subset of `delegatesTo`;
`required_closure("agent.dataflow-builder")` = the three coords, deterministic order, with the
Dataset Finder ↔ Node Builder cycle traversed once; `required_by` names the Dataflow Builder for
each member.

**Unit — the attach helper** (new `test_dataset_resolution.py`, `test_attachments.py`):
`node_target_matches` accepts `pkg/data-loading`, `pkg/data-loading@2`, `DATA_LOADING` and
rejects `pkg/vis-vega`; the helper attaches Node Builder always and Dataset Finder only for
data-loading; idempotent on a second call; reports a skip with a reason when a template is
absent; never raises.

**Unit — the state machine**: each of the four states from a hand-built spec; `resolved` for a
user-typed path, an installed catalog id, a verified URL, an explicit synthetic request;
`unresolved` for a bare goal; the skip line recorded in the trail.

**Unit — the selection resolver**: keys resolve against the persisted part; an unknown key
422s; an external pick is re-probed and its verdict stored; a client-supplied URL that is not a
candidate is rejected.

**Integration — routes** (`test_routes.py`): (a) installing the Dataflow Builder in a fresh
project lands four coords in one write; (b) a Dataflow Builder run in a project missing the
Dataset Finder repairs the closure, discloses it, and mints **no** `project.install` — the
regression test named for session `7c300d0d`; (c) a whole-plan apply returns `attachedAgents`
and the spec holds a Node Builder on every created node plus a Dataset Finder on each
data-loading one; (d) the per-node apply keeps `attachedAgentId` (`test_routes.py:6456`);
(e) Solve on an unresolved data-loading node yields `pending` with the awaiting-selection
remedy, a candidates turn in the Dataset Finder session, and **no** `source-missing`;
(f) selection → install → Retry solves the node; (g) uninstalling the Node Builder while the
Dataflow Builder is installed is a 409 naming it.

**Frontend (jest)**: the strip renders the awaiting-selection reason and its button, and the
click calls `openChat` with the payload's attachment id; the card's Confirm posts the picks then
sends the composed prompt (both, in order); an unreachable re-probed pick renders its chip and
its refusal line; the badge row shows two agents for a plan-created data-loading node;
`tsc --noEmit` clean.

**Harness (dev/121)**: one fixture asserting the plan-first flow — a Chicago-shaped prompt whose
expected first proposal is a `dataflowPlan` (not a `project.install`), scored through the
production path. This is the mechanised form of the owner's report.

**Required before the change is complete**: the roster/closure tests, the attach-helper tests,
the state-machine tests, routes (b), (c) and (e), the strip and card jest tests, plus a live
re-test in the owner's project — the flow from a bare goal to an applied plan with two
attachments per data-loading node and candidates awaiting selection, with no install proposal
anywhere in the transcript.

---

## 8. Acceptance Criteria

1. Installing the Dataflow Builder in a fresh project installs the Node Content Builder, the
   Dataset Finder and the Node Builder in ONE spec write, disclosed in the drawer as
   **+3 required** before the click.
2. In the owner's project, a bare planning goal produces a `dataflowPlan` proposal as the first
   proposal of the conversation; no `project.install` proposal for a required agent appears in
   any Dataflow Builder transcript, ever.
3. A closure repaired at the point of use is stated in the transcript, names the dependent, and
   installs only `requiresAgents` members.
4. Applying a plan as a whole attaches a Node Builder to **every** created node and a Dataset
   Finder to **every** created data-loading node; applying the same plan node-by-node produces
   the identical attachment set.
5. The apply result and the applied-plan card name what was attached, and name anything that
   could not be attached with its reason. No apply ever fails because of an attachment.
6. Solving an unresolved data-loading node initiates discovery without being asked: candidates
   appear in that node's Dataset Finder chat, the node is **pending** with *"awaiting your
   dataset selection"*, no content is generated, nothing is written, and the message
   `source-missing` no longer ends that path.
7. The strip's awaiting-selection row opens that node's Dataset Finder chat in one click, and
   the button's accessible name identifies the node.
8. Confirming a selection records it server-side from the runtime's own rows; a key the runtime
   never proposed is refused; an external pick's verdict is re-probed and stored.
9. A catalog pick that needed installing resolves the node once its reviewed install applies;
   Retry then solves the node with the confirmed source in `sourceGrounding`.
10. A data-loading node whose source is already grounded skips discovery and records why in the
    trail — the "always initiated" rule is auditable, and re-solving a working node costs no
    extra model call.
11. Deleting a node removes both attachments, both transcripts and the selection record.
12. `tests/test_agents`, `tests/test_projects`, `tests/test_packages`, the full jest suite and
    `tsc --noEmit` are green, with only the pre-existing unrelated failures dev/121/124/125
    already recorded.

---

## 9. Recommended Commit Breakdown

1. **Shared logic, with tests** — `attachments.node_target_matches` extracted from
   `attach_agent`, `_attach_plan_node_agents` (+ `_attach_node_builder` re-pointed), and the one
   `_ungrounded_remedy` helper replacing the three copies. No behavior change on the per-node
   path; new tests.
2. **The declaration + the closure repair (`DEC-080`)** — `requires_agents` on the two agents,
   `ensure_required_closure`, its call sites, the required-delegate retry in
   `_resolve_delegate_request`, the disclosure line; roster, closure and route tests including
   the session-`7c300d0d` regression.
3. **Plan apply attaches both agents** — `_apply_dataflow_plan` calls the helper, both applies
   return `attachedAgents`, the applied cards say so; route tests for both paths.
4. **`dataset_resolution.py`** — the state machine, the selection record accessors and
   `initiate`; the `_delegation_home` capability table; unit tests. No caller yet.
5. **Resolution initiates discovery** — `resolve_source` in `_verified_content_rounds`, the
   `awaiting-source` verdict, both Solve callers mapping it to `pending` with the remedy, the
   discovery event; route and loop tests.
6. **The selection endpoint + frontend** — the route and resolver, `agentsApi`, the provider
   action, the card's Confirm, the strip's reason and Open Dataset Finder action; jest.
7. **Prompts, docs and ledgers** — the three instruction paragraphs, `docs/AGENT-CATALOG.md`,
   `docs/USAGE.md`, the dev/121 fixture, then a separate tracking commit for dev/03 (`DEC-080`),
   dev/00, `BL-P5-20260910-60` and this memo's status.

---

## 10. Engineering Quality Checklist

- **No duplicated business logic.** One attach helper for both apply paths and dev/72's home;
  one node-compatibility predicate for the drawer and the automatic path; one data-loading
  predicate (`is_data_loading_type`); one remedy sentence where there were three; one install
  path (`install_in_project`) for installs and repairs alike.
- **Centralized.** Resolution policy lives in `dataset_resolution.py`; the discovery-home rule
  is a table, not a branch; the candidate mint stays `_mint_candidates_from_delegate`; the reply
  schema stays `content.CANDIDATES_INSTRUCTION` (still one copy).
- **Types explicit.** New records typed and parsed at the boundary (`picks`, `datasetSelection`,
  `attachedAgents`), the loop's new verdict a declared literal, the frontend payloads added to
  `agentsApi.ts` rather than inferred.
- **Predictable state.** Every write under the spec lock, one write per apply, `candidates-pending`
  written with the turn that mints it, no cached derivations.
- **Consistent UI.** The remedy has one rendering (dev/116's pattern), the badge row is the
  existing one, the applied card's new line matches dev/112's truthful register.
- **Loading / empty / error / success** all named in §4 and mapped to `pending` rather than
  `failed` wherever nothing was attempted.
- **Accessibility** considered in §5 (real buttons, named by node, focus into the panel, one
  polite announcement).
- **Tests** cover the behavior, the regression the owner reported, and the edge cases in §6.
- **Conventions.** `requiresAgents ⊆ delegatesTo`; `DEC-006` review gates untouched; `DEC-047`
  hand-off still user-mediated; `REQ-ORCH-001` intact (no model-chosen install);
  backend-owned sections respected; no fallback path added — a member visible nowhere refuses
  loudly.
- **No new re-renders or flicker**: the attachment listing refresh already runs in both applies'
  `finally`; no new canvas bridge event.

---

## 11. Open questions and recorded follow-ups

- **F1** `_apply_node_create` (`:3722`) and dev/113's `node.insert` attach nothing. Should a
  node created directly by a Node Builder proposal also carry the plan-node agents? Deferred:
  the owner's instruction names plan apply, and the Node Builder that created it is already the
  home of that work.
- **F2** The Dataset Finder's external hand-off is a *suggested prompt* the user sends in the
  Dataset Finder's own chat; `suggestedPrompts` carries no target attachment
  (`content.py:182`). With both agents on the same node, the honest routing is "send this to
  this node's Node Builder". Needs a `target` on the part plus provider routing — its own small
  memo.
- **F3** "Always initiated" is implemented as *always, unless the node's source is already
  grounded* (§D), with the skip recorded. If the owner means literally always — a discovery
  round even for a node whose goal already names an installed catalog dataset — the skip
  condition is one predicate to remove, at the cost of a model call and a review gate per
  re-solve.
- **F4** Owner live re-test in project `667a4b6c` after commit 5, then again after commit 6 —
  the flow that must not happen is the acceptance test.
- **F5** `_mint_project_install` keeps its `not-installed` lane for non-required delegates; if
  §B's repair proves the better answer for those too, that is a separate decision (it would
  need a rule for what a *preferred* delegate may install, which `REQ-ORCH-001` currently
  forbids).

---

## 12. What changed while building

1. **Two stages of initiation, not one (§3D).** The memo's pre-round check treated "the
   project's Data Catalog holds datasets" as grounding for a first attempt. Reading it back
   through a real test environment showed what that means in practice: every shipped install
   seeds a catalog (13 datasets in the suite's own environment), so a single pre-round check
   would have skipped discovery essentially always. The implemented rule keeps both readings:
   nothing in the project could ground the node → discovery BEFORE the first round; the
   catalog might → the first attempt is generated against its rows and the round's own
   refusal or decline (`ungrounded-source`, `source-missing`) initiates discovery, with the
   attempt trail kept. The strict "always, even for a node the catalog can serve" variant is
   one predicate — recorded as **F3**, not chosen unilaterally.
2. **Grounding evidence is ranked (§4).** Not in the plan. Evidence about THIS node (a path
   or dataset id in its own intent, a URL verified for it, an explicit synthetic request)
   outranks a pending candidates card — a user who has since said what to load must not be
   stuck answering a card they overtook. Evidence about the PROJECT loses to a pending card,
   because re-generating against the whole catalog is not progress.
3. **"Awaiting your selection" is only ever said when something is selectable.** The memo
   mapped every unresolved outcome to `pending`. Implemented: discovery that finds nothing
   usable, or a specialist that cannot run, leaves the node its OWN honest outcome with the
   discovery attempt recorded as the reason it stays unresolved. This also preserved two
   harness tests whose contract is that a fabricated dataset id never reads as a success —
   a fabrication that ends "pending, waiting for you" would have scored 1.0.
4. **No second data-loading predicate (§3C).** The memo's `_PLAN_NODE_AGENTS` carried a
   `data-loading` marker per agent. Implemented as a bare list whose membership question is
   answered by the manifests themselves (`compatibleTargets[].requires`, through the one
   predicate extracted from `attach_agent`) — so the list cannot drift from the roster, and
   the drawer's attach and the automatic attach cannot disagree about where an agent may live.
5. **The skip record is informational, not `resolved`.** The memo's `mark_skipped` wrote
   `status: resolved`, which would have suppressed the post-failure stage forever. It writes
   `not-needed` with the literal instead, and re-recording the same literal writes nothing
   (no revision churn on every Solve).
6. **The Data Catalog is listed at the entry point.** `catalog.search` rides the request
   context and a detached Solve job has none — dev/123's field finding, applied rather than
   relearned: the rows are resolved beside dev/115's eager dataset-path resolution and handed
   to the discovery delegate, and a failed listing TELLS the delegate the catalog was
   unavailable instead of leaving it to imagine one. The initiation's spec writes are
   serialized under the project's own spec lock, because a batch resolves its nodes in a pool.

Six existing tests were re-framed rather than bent, each with its reason in its commit
message: three legacy-lockfile Solve tests and one apply test now use a blocker standing in
for the one state `DEC-080` cannot fix (a required agent visible nowhere), and two found
their content review in the orchestrator's chat only because the plan node had no agent of
its own — with the Node Builder required, dev/73's rule takes effect and they follow
`proposalAttachmentId`, which the events already carried.
