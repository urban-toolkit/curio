# Implementation Memo: Dataset Finder — the Second P5 Composite (`dataset.discover` + `dataset.select`, two lanes)

Date: 2026-08-04
Status: implemented 2026-08-04 — COMMIT-dc044c24 (roster + requires gating),
COMMIT-1f45fdcf (catalog.search + dataset.install), COMMIT-06f4bcac (datasetCandidates part +
card + review kind), DEC-047 handoff tests + docs in the closing commit. Verification: backend
`pytest tests --ignore=tests/test_frontend` → 971 passed; frontend `npx jest` → 641 passed
(59 suites); injection-resistance + rule-9 share suites included.
Feature slice: the second Phase-5 composite. `agent.dataset-finder` joins the roster with the
dev/15 §3.4 manifest surface, the docs/06 **two-lane suggestions card** (External sources / From
your Data Catalog), a `catalog.search` read tool over the existing datasets domain, a reviewed
`dataset.install` mutation reusing the existing dataset-only install flow, and the **user-mediated
Node Builder handoff** for external picks.
Design sources: `docs/06-dataset-finder-source-review.md` (authoritative product spec: two lanes,
candidate row contract, review-and-apply flow, no bespoke buttons, prompt-mediated confirmation),
`dev/15` §3.4 (manifest, capabilities, delegatesTo, two-lane contract), `dev/48`/`DEC-046`
(delegation seam, `project.install` proposal, apply→canvas bridge), `dev/41`/`DEC-045` (proposal/
apply machinery), `DEC-006`/`REQ-REVIEW-001` (review-before-apply structural), `DEC-017`/
`REQ-PERM-001` (server-allowlisted tools), `ADR-AG-007` (domain-owned implementations),
`REQ-SEC-002` (agent content untrusted; allowlist renderer), `dev/49` (DR-6: `web.search` stays
with the research-node track), dev/47 (lockfile truth), the existing datasets domain
(`app/datasets/application/listing.py` `list_catalog(q, fmt, origin, dataflow_id, …)`,
`mutations.install_dataset(dataflow_id, dataset_id)` — idempotent duplicate handling).

**Sequencing note (T4).** The program order listed T4 (provider profiles + secret store) before
Dataset Finder. v1 deliberately proceeds without it: the external lane performs **no external
HTTP and holds no credentials** — external candidates are model-proposed metadata grounded in the
mission/context, exactly as docs/06 frames them ("do not imply bundled connectors, credentials,
availability"); credential-profile *requirements* on a row are display metadata without secrets.
T4 becomes load-bearing when fetch nodes need credential profiles at run time (Node Builder
execution territory) and when a `web.search` tool lands (dev/49 DR-6) — neither is in this slice.

New decision required: **DEC-047 — the external handoff is user-mediated, never a child-minted
proposal.** dev/15 §3.2 sketched the external pick as a delegated `dataset.fetch.author` request
to Node Builder. Under `DEC-046`, a depth-1 child is structurally proposal-less (no tools, no
session, reply never parsed) — a child run **cannot** mint the reviewable fetch-node proposal the
flow needs, and weakening depth-1 to allow it would trade away the injection-resistance guarantee
for a shortcut. Instead, per docs/06's own confirmation model ("the agent writes a primary
suggested prompt into the editable chat input… the user reviews, edits, and submits"): a confirmed
external pick yields a **handoff card + suggested prompt addressed to the user's Node Builder
attachment**, whose run then produces the fetch-node `node.create` proposal with the full dev/48
review machinery (server-validated template, apply→canvas bridge). A missing Node Builder resolves
through the existing reviewed `project.install` proposal path. Batch/orchestrated handoffs are the
Dataflow Builder memo's DR-4 territory. Register in the dev/03 table + 2.1 ledger with the docs
commit.

## 1. Problem Statement

Configuring a data-loading step is entirely manual: the user must already know which external
source or catalog dataset fits, find it themselves, and either hand-author fetch code or open the
Data Catalog drawer and hunt. The plan's discovery agent (`agent.dataset-finder`, dev/15; product
spec docs/06) has no implementation:

1. **No discovery surface.** Nothing produces ranked dataset candidates from a mission + node
   context. The chat can only answer in prose; there is no typed two-lane candidates card, no
   multi-select, no lane-correct confirmation routing.
2. **No catalog grounding.** Agents cannot read the Data Catalog: no `catalog.search` contract
   exists, so any model answer about "your catalog" would be hallucinated rather than resolved
   from `list_catalog` (the same fail-closed grounding gap dev/48 closed for node templates).
3. **No reviewed dataset install.** The only agent mutations are node-shaped (dev/41/48). A
   catalog pick has no review-before-apply path into the existing dataset-only install flow —
   docs/06 requires exactly that, preserving its authorization/duplicate/error behavior.
4. **No external→Node Builder route.** The concept's core two-lane split (external picks become
   Node Builder fetch nodes; catalog picks become installs, never agent installs) has no
   mechanism connecting the two composites.

**Expected behavior.** Dataset Finder installs/attaches like any built-in (to a data-loading node
or the canvas). "Find datasets for heat vulnerability in Chicago" yields ONE suggestions card with
two labeled lanes of informational, multi-selectable rows (safe metadata only). Confirming catalog
picks routes through a reviewed `dataset.install` proposal applied by the existing installer
(idempotent duplicates); confirming external picks yields the DEC-047 handoff to the user's Node
Builder attachment. Nothing mutates without review; no agent is ever installed by a dataset pick.

## 2. Scope

**Backend (`utk_curio/backend/app/agents/`, thin helpers in `app/datasets/`)**
- `builtin.py`: roster entry `agent.dataset-finder` (net-new `discovery_instruction.txt` in
  `llm-prompts/`, dev/15 §3.3); `BuiltinAgentSpec` unchanged (dev/48 fields suffice).
- Attach-time **`requires` gating** (small, general): `compatibleTargets[].requires` finally gets
  runtime meaning — for a `node` target, every entry must match the node's canonical template id
  suffix (`data-loading` ⇒ `*/data-loading`). Empty `requires` = any node (all existing agents,
  behavior-identical). Dataset Finder declares `{kind: node, requires: ["data-loading"]}` +
  `{kind: canvas}` (canvas attach for mission-first discovery before any node exists — recorded
  deviation from dev/15's node-only table, consistent with docs/06's mission flow).
- `tools.py`: `catalog.search` (read) — thin wrapper over the datasets domain
  (`ADR-AG-007`): `list_catalog(q, fmt, origin, dataflow_id=project)` → bounded rows
  `{id, name, format, origin, installed, description≤bound}`; `dataset.install` (mutate) —
  proposal-only in the loop, executed solely by the apply endpoint.
- `services.py`: `_mint_dataset_install` (validates the dataset id against the same
  `list_catalog` truth — unknown id refused; already-installed short-circuits to an idempotent
  refusal steering the model to say so) and `_apply_dataset_install` (re-validates, then calls
  the existing `DatasetCatalogService.install_dataset(project_id, dataset_id)` — the dataset-only
  flow with its duplicate/authorization/error semantics; result card "Applied: dataset installed").
- `content.py`: new model-emitted part **`datasetCandidates`** — the two-lane card contract:
  `{lanes: {external: [...], catalog: [...]}}`, each row bounded per the docs/06 row contract
  (`name`, `sourceType ∈ {api, endpoint, portal, catalog, document, database}`, `provider?`,
  `url?` (scheme-allowlisted http/https at parse time), `format?`, `coverage?`, `fit?` (score +
  one-line rationale), `datasetId?` (catalog lane), `requirement?` (credential/permission note,
  no secrets)); ≤ 8 rows/lane, string bounds named in one place, one part per reply, coexists
  with `suggestedPrompts` (the confirmation prompt rides the same tail). Malformed → the whole
  block fails open to text (T2 rule).
- Grant-aware tail: with `catalog.search` granted the instruction directs grounding catalog-lane
  rows in tool results (never memory); the confirmation grammar (which selection produces which
  route) is part of the net-new instruction.

**Frontend (`utk_curio/frontend/urban-workflows/src/`)**
- `api/agentsApi.ts`: `AgentDatasetCandidatesPart` type; `dataset.install` proposal kind.
- `components/agents/content/AgentDatasetCandidatesCard.tsx` (new, rendered from the safe-content
  family): the docs/06 grouped two-lane surface — labeled lanes, keyboard-operable multi-select
  rows (checkbox semantics, label-not-color state), safe metadata via the existing sanitizer
  (URLs display-only, http/https only), catalog rows show installed-state chips; **no per-row
  action buttons**. Selection composes the confirmation prompt into the chat input (the existing
  suggested-prompt prefill path), editable before send.
- `AgentReviewCard`: `dataset.install` kind (effect line: "Applying installs only this dataset
  into the project's Data Catalog — no agent is installed."). External handoff card: reuses the
  generic `card` part + a suggested prompt addressed to Node Builder (DEC-047) — no new proposal
  kind, no new mutation.
- Palette/catalog/drawer: nothing — the roster addition appears automatically (dev/47 state sync).

**Explicitly out of scope**
- Any external HTTP, `web.search` tool, credentials, or provider profiles (T4 / dev/49 DR-6).
- Fetch-node authoring or any node mutation by Dataset Finder ("never authors fetch code" —
  Node Builder owns that end of the handoff, dev/48).
- Background execution (dev/15 `runtime.execution: background` — deferred with `DEC-021`
  interruption/leases; v1 runs foreground like every agent; recorded deviation).
- `geography`/`lineage` as first-class run inputs — v1 grounds them through catalog metadata in
  tool results + the dev/44 canvas context; a dedicated context extension waits for demand
  (recorded deviation from dev/15's reads list).
- Delegated discovery support (`workflow-suggester`, `keyword-binding` children) — declared in
  `delegatesTo` for resolution parity, exercised when a real consumer needs them; no new
  delegation mechanics beyond dev/48.
- Auto-install of a catalog dataset ("may auto-install when required and authorized", dev/15) —
  v1 keeps every install behind the reviewed proposal; relaxing to authorized auto-install is a
  later policy decision (recorded deviation, conservative direction).
- The Dataflow Builder orchestration of multi-pick batches (dev/49 DR-4).

## 3. Recommended Implementation Approach

### 3.1 Roster entry

```python
BuiltinAgentSpec(
    "agent.dataset-finder", "Dataset Finder", "data",
    "Discover and select datasets across external sources and the Data Catalog; "
    "hand external picks to Node Builder. Never authors fetch code.",
    "discovery_instruction.txt",
    ("dataset.discover", "dataset.select"), ("discovery", "selection"),
    targets=("node", "canvas"),          # node gated by requires; canvas = mission-first
    reads=("mission", "nodeContext", "catalog"),
    tools=("catalog.search", "dataset.install"),
    delegates_to=("agent.node-builder", "agent.workflow-suggester", "agent.keyword-binding-agent"),
    review_policy="review-before-apply",
)
```

`requires` rides the manifest (`compatibleTargets`), not the roster dataclass: `target_kinds()`
gains an optional per-kind requires mapping only if needed — otherwise a small
`target_requires: {"node": ("data-loading",)}` field with a byte-parity default (`{}`) for every
existing agent. The net-new instruction teaches: ground catalog rows ONLY in `catalog.search`
results; propose ≤ 8 candidates per lane with honest fit rationales; external rows are metadata,
never claims of an existing connector; after the user confirms, route catalog picks through ONE
`dataset.install` toolRequest per dataset and external picks through the Node Builder handoff
prompt; never install or imply installing an agent.

### 3.2 `catalog.search` (read) — grounding the catalog lane

Params `{"q"?: str, "format"?: str, "origin"?: str}` (all optional, bounded). Executes
`DatasetCatalogService.list_catalog(dataflow_id=project_id, q=…, fmt=…, origin=…)` under the
acting user and returns bounded rows (id, name, format, origin, installed, truncated
description) as framed untrusted context — same truncation/framing rules as every read tool.
The tool is how the model knows what "From your Data Catalog" truthfully contains, including
installed-state for the row chips (mirror of dev/48's template-roster grounding).

### 3.3 `dataset.install` (mutate) — the catalog lane's reviewed handoff

Mint: validate `datasetId` against `list_catalog` for THIS project (unknown → refusal;
already-installed → refusal telling the model to report the existing state — docs/06 idempotence
surfaces as honest chat, not a dead proposal). Proposal pins `{datasetId}`; summary "Install
dataset · <name>"; preview = name/format/origin (safe metadata). Apply: re-validate (dataset gone
from the catalog between mint and apply → 409 + `stale`, the dev/48 analogue), then the existing
`install_dataset(project_id, dataset_id)` — duplicates collapse idempotently inside the domain
service (docs/06 rule), result card + `mutation_applied`, response carries
`installedDataset: {id, name}` (informational; datasets surface through the existing catalog/
sidebar sync — no canvas bridge work). Apply consumes no quota (deterministic).

### 3.4 `datasetCandidates` — the two-lane suggestions part

Model-emitted, parsed in `content.py` with the same fail-open posture as every part. The part is
**informational**: selection state, multi-select, and confirmation live client-side; confirmation
is a normal user message (docs/06: rows carry no bespoke buttons; the suggested prompt is the
confirmation vehicle). URL fields accept http/https only at parse time; everything renders
through the existing sanitizer (`REQ-SEC-002`). The card coexists with `suggestedPrompts` in one
tail so a single reply carries candidates + the primary confirmation prompt.

### 3.5 The external lane (DEC-047)

On confirmation of external picks, the model replies with a `card` part summarizing each handoff
(source, endpoint, format, requirement — the docs/06 row contract) plus a suggested prompt of the
form "Ask Node Builder: author a fetch node for <source> — endpoint <url>, format <fmt>, parse
<…>". The chat UI's existing prompt-chip prefill carries it; the user sends it to their Node
Builder attachment, whose run produces the reviewed fetch-node `node.create` proposal (dev/48
end-to-end: template-validated, digest-free creation pins, apply→canvas bridge). When
`agent.node-builder` is not installed in the project, Dataset Finder's `delegateRequest` for
`dataset.fetch.author` resolves through dev/48's missing-specialist path and mints the reviewed
`project.install` proposal — the delegation seam is reused exactly where it is sound (resolution
+ install proposal), never for child-minted proposals.

## 4. Data and State Handling

- **Sources of truth**: the datasets domain (`list_catalog` / `install_dataset`) for everything
  catalog-shaped — the agents module owns no dataset knowledge (mirror of dev/48's template rule);
  the roster manifest for the contract; turn parts + `activeProposal` mirror for proposals
  (dev/41, unchanged); client component state for row selection (ephemeral by design — docs/06
  selections don't survive project switch; transcript turns record what was confirmed).
- **Install state**: rows show `installed` from tool results at generation time; the apply path
  re-validates at apply time — stale rows degrade to idempotent/`stale` outcomes, never double
  installs. After apply, the existing catalog/sidebar refresh paths pick up the new dataset
  (dev/47 notify pattern where needed).
- **Loading/empty/error**: slow discovery is just a normal streamed run (docs/06's cancellable
  progress = the existing stream + stop affordances); an empty lane renders its labeled empty
  state; tool failure → framed result, the model says the catalog was unavailable rather than
  inventing rows.
- **Race safety**: proposal supersede semantics unchanged; one `dataset.install` per dataset per
  proposal (multi-pick = the model mints them across rounds, bounded by `MAX_TOOL_ROUNDS`, or
  tells the user to confirm in batches — stated in the instruction; full batch apply is DR-4).

## 5. UI and UX Requirements

- **Card anatomy** (docs/06 §Visual Direction): one grouped suggestions surface, two labeled
  lanes ("External sources" / "From your Data Catalog"), rows with name, source-type badge,
  provider, safe URL text, format/coverage, fit score + rationale, requirement note, installed
  chip (catalog lane); multi-select via keyboard-operable checkboxes; selection state by
  label/control, never color alone; green data-agent accent via the existing category tint.
- **No bespoke actions**: no Use-source/Create-node/Install buttons on rows; the only controls
  are selection + the composed confirmation prompt in the editable chat input. Apply/Dismiss
  stay exclusively on review cards (`dataset.install`, `project.install`).
- **No inline preview**: detailed inspection remains the Data Catalog drawer's job (docs/06).
- **Review cards**: `dataset.install` renders with the dataset-scoped effect line;
  applied/stale/dismissed/superseded chips identical to dev/41.
- **Accessibility**: lanes as labeled groups, rows as checkboxes with full labels, aria-live
  polite for lane updates, focus preserved across selection, WCAG 2.2 AA per the established
  patterns.

## 6. Edge Cases

- Empty catalog / no matches → catalog lane's empty state; the model says so (tool-grounded).
- `catalog.search` failure → framed error result; no fabricated catalog rows (instruction + the
  grounding rule).
- Confirming an already-installed dataset → mint refuses with the existing-state message; the
  model reports "already installed" (idempotent UX, no dead proposal).
- Dataset removed between mint and apply → 409 + `stale`, card explains (dev/48 analogue).
- OSM group ids (`is_osm_group_id`) → the domain service's install-all-layers behavior applies
  unchanged; the proposal summary names the group.
- Duplicate rows across lanes (an external source that already exists as a catalog dataset) →
  the instruction prefers the catalog lane; the parser tolerates duplicates (display-only).
- Hostile candidate metadata (script URLs, `javascript:` schemes, HTML) → rejected at parse
  (scheme allowlist) or neutralized by the sanitizer; rows are never actionable markup.
- Node Builder not installed at external confirmation → reviewed `project.install` proposal via
  the dev/48 delegation path; nothing auto-installs.
- Attach to a non-data-loading node → 400 naming the requirement; canvas attach for mission-first
  discovery unaffected. Existing agents (empty `requires`) attach exactly as before (regression).
- More than 8 candidates per lane in a tail → the block fails open to text (bounds are the
  contract).
- Old client / new server: the `datasetCandidates` part degrades to nothing (unknown part type,
  T2 tolerance); `dataset.install` proposals render as the generic card shell.
- Project switch mid-selection → component state clears with the chat (docs/06 rule 4).

## 7. Testing Strategy

Backend (`utk_curio/backend`, pytest):
- **Roster/manifest**: dataset-finder validates; targets/requires round-trip; the fourteen prior
  manifests byte-identical (dev/48 regression re-pinned at fifteen); net-new prompt resolves +
  materializes; lifecycle (catalog/import/install/attach) for the new coord; attach gating —
  data-loading node OK, other node 400, canvas OK, existing agents unaffected.
- **content.py**: `datasetCandidates` grammar (lane/row bounds, source-type enum, scheme
  allowlist, coexistence with suggestedPrompts, one-per-reply, fail-open on any malformed row).
- **catalog.search**: bounded rows from a seeded catalog fixture; q/format/origin filters pass
  through; failure → framed error; output truncation.
- **dataset.install**: mint validates against the project catalog (unknown refused,
  already-installed refused with the existing-state text); proposal pins `{datasetId}`;
  apply re-validates (removed → 409 + `stale`), calls the domain installer (duplicate collapse
  asserted via double-apply), result card + `mutation_applied` + `installedDataset`; apply
  consumes no quota; injection-resistance suite extended to the new tool; dismiss paths.
- **DEC-047 path**: with Node Builder uninstalled, a `dataset.fetch.author` delegateRequest mints
  the `project.install` proposal (reuse of the dev/48 test pattern, by name); no child ever mints
  a node proposal (structural re-assertion).
- Rule-9 share suite re-run (candidates/proposals carry no agent-private data into shares).

Frontend (`npx jest` via the curio-feat conda env):
- `AgentDatasetCandidatesCard`: two lanes render with labeled groups; multi-select keyboard
  operability; installed chips; sanitizer applied to every text/URL field (hostile fixture);
  selection composes the confirmation prompt into the input; no per-row buttons rendered.
- Review card: `dataset.install` kind + effect line.
- Stream/content tolerance: unknown part regression stays green; the new part type parses.
- Full suites green (backend 951+, frontend 630+).

## 8. Acceptance Criteria

- [x] `agent.dataset-finder` is browsable, importable, installable, attachable (data-loading
      node or canvas; other nodes 400), and runnable with the net-new instruction; prior
      manifests byte-identical.
- [x] A discovery request yields ONE two-lane `datasetCandidates` card with bounded, sanitized,
      informational rows (catalog lane grounded in `catalog.search` results, installed state
      shown) and a confirmation prompt — no bespoke row actions.
- [x] Confirming a catalog pick mints a reviewed `dataset.install` proposal; **only** the
      authenticated apply endpoint installs, through the existing dataset-only flow (duplicates
      idempotent, removed-dataset drift → 409 + `stale`); no dataset pick ever installs an agent.
- [x] Confirming an external pick yields the DEC-047 handoff (card + Node Builder-addressed
      suggested prompt); the fetch node arrives as Node Builder's own reviewed `node.create`
      proposal; a missing Node Builder yields the reviewed `project.install` proposal.
- [x] No external HTTP, credentials, or secrets anywhere in the slice; candidate metadata is
      sanitized and scheme-allowlisted (`REQ-SEC-002`).
- [x] DEC-047 recorded (dev/03 table + 2.1); deviations recorded in §2 (foreground-only,
      geography/lineage via tool results, no auto-install, canvas target addition).
- [x] Injection-resistance and rule-9 suites pass.

## 9. Recommended Commit Breakdown

1. `Roster: agent.dataset-finder + compatibleTargets requires gating, net-new discovery instruction, with byte-parity + attach-gating tests`
2. `catalog.search: datasets-domain read tool + grounded tail, with tests`
3. `dataset.install: reviewed proposal/apply over the existing dataset-only install flow, with tests (dev/50)`
4. `datasetCandidates: two-lane content part + frontend card (multi-select, sanitized, prompt-composing), with tests`
5. `DEC-047 handoff path + review-card kind + docs/ledgers (dev/50 implemented, DEC-047, BL-P5 entry, docs/AGENTS.md)`

## 10. Engineering Quality Checklist

- [ ] Mutation authority stays structural: mint-only loop, apply-endpoint-only execution; the
      dataset installer is reached solely through the authenticated apply branch.
- [ ] No duplicated domain logic: catalog reads and installs go through the existing datasets
      services (`ADR-AG-007`); the agents module owns no dataset knowledge.
- [ ] One source of truth per fact: datasets domain (catalog rows + install state), roster
      manifest (contract), turn parts + mirror (proposals), client state (ephemeral selection).
- [ ] Depth-1 delegation untouched (DEC-046): the seam is reused for resolution + install
      proposals only; no child-minted proposals anywhere (DEC-047 tested by name).
- [ ] Existing manifests, grant-less runs, attach paths, and T2 clients byte-/behavior-identical
      (regressions named).
- [ ] All candidate content flows through the centralized sanitizer; bounds live in `content.py`
      once; no color-only state; keyboard operability tested.
- [ ] The two-lane card renders informational rows only — the sanctioned action surfaces remain
      review cards and the editable chat input.
- [ ] Deviations from dev/15 are recorded with rationale (§2) and each names its revisit point
      (T4, DR-4, DR-6, DEC-021).
