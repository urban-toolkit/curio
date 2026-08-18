# Dev/84 — `agent.package-recommendation`: roster entry, package tools, reviewed install proposal, parent wiring

Status: implemented (2026-08-18, commits `577315d8` tools+roster / `cff987df` proposal
lane / `60d8e6e4` parent wiring / `8b847211` frontend dialog flow; build-log entry
BL-P5-20260818-30). Implementation notes: no design deviations beyond the four recorded
below (D1–D4 all landed as specified). Two implementation-time details worth knowing:
the dialog-gated apply is a **deferred promise** — `beginReview` resolves only when the
dialog flow settles (apply success / apply failure / cancel), so the review card's own
busy/error handling wraps the whole round-trip and no new error surface exists; and the
frontend probe passes every user-store package plus the candidate (the drawer's exact
shape), while the backend apply re-checks via `agent_resolve_report` regardless.

Implements the deferred fourteenth releasable built-in, specified in dev/16 (DEC-035) and
recorded as deferred in the roster itself (`builtin.py:162` — the Connection Builder
addendum, `:199` — the Dataflow Builder deviation). Every prerequisite dev/16 waited on
now exists: the delegation seam (`delegation.py`, DEC-046/048 — capability-first
resolution, missing-specialist `project.install` proposals), the mutate-tool proposal
mint + apply machinery (`dataset.install` is the direct precedent), typed read tools
(`catalog.search` precedent), and net-new built-in prompts in `llm-prompts/`
(`node_build_instruction.txt` et al. set the pattern).

This memo grounds dev/16's design in today's code and records four deviations (§3.6).
dev/16 remains the product spec; where the two disagree on mechanism, this memo wins.

---

## 1. Problem Statement

Node packages have a complete product — per-project lockfile (`spec.dataflow.packages`),
reviewed install dialog (`InstallPermissionsDialog`: permissions + python/js dependencies
+ conflicts), `packagesApi.catalog/resolve/installToProject`, the Packages palette — but
no agent is connected to it:

- "Package Recommendation" is named across the concept docs and the dev/16 spec, yet the
  roster ships 16 agents without it; `builtin.py` records the deferral twice.
- The Dataflow Builder's delegation paragraph (auto-generated from `delegatesTo` by
  `delegation.visible_capability_entries`) offers no package capability, so its
  "Recommend packages" intent has no delegate target.
- Node Builder can propose a node whose code imports a library provided by an
  uninstalled catalog package; Connection Builder can propose a connection with the same
  gap. Nothing identifies the missing package — the user must notice it themselves and
  find it in the Nodes Catalog drawer.

**Expected behavior (dev/16):** the build agents identify the node packages their work
requires and surface each required-but-uninstalled package as a **reviewed** install
proposal with a why-needed rationale; confirming routes through the **existing** package
install review (permissions + dependencies + conflicts) and writes the current project's
lockfile via the existing endpoint. Never a silent install, never a new package
mechanism, never agent-authored packages, and built-ins (`curio.builtin@*`) are never
proposed.

Why it matters: this is the last specified-but-unshipped roster agent; it closes the
`package.*` capability gap in the composite delegation graph and removes a real
usability cliff (agent-built nodes that can't run until the user diagnoses a missing
package on their own).

## 2. Scope

### In scope

Backend (`app/agents/`):

- `builtin.py` — the `agent.package-recommendation` roster entry; `delegates_to`
  additions on `agent.node-builder`, `agent.dataflow-builder`, and
  `agent.connection-builder`.
- `tools.py` — two read contracts (`packages.catalog`, `packages.resolve`) and one
  mutate contract (`package.install`), plus their `execute_read_tool` wrappers over the
  packages domain (ADR-AG-007: thin wrappers, no package knowledge owned here).
- `services.py` — `package.install` mint validation (same seam as `dataset.install`)
  and `_apply_package_install` in `apply_proposal`.
- `utk_curio/llm-prompts/package_recommendation_instruction.txt` — net-new instruction
  prompt (the only prompt file added; parents' delegation offers are auto-generated).
- `docs/AGENTS.md` roster count/table update.

Frontend:

- `components/agents/attach/` — apply-time interception for `package.install`
  proposals: a small `usePackageInstallReview` hook + dialog host that runs
  `packagesApi.catalog`/`resolve` and renders the existing `InstallPermissionsDialog`
  before `agentsApi.applyProposal` fires (§3.4).
- `components/agents/content/AgentReviewCard.tsx` (or its dispatch table) — a
  `package.install` card variant: package name + why-needed rationale + installed-state
  line.

Tests on both sides (§7).

### Out of scope (intentionally)

- Authoring/forking/publishing packages by agents; any change to the package
  install/lockfile/resolve mechanism or to `useEnsureWorkflowDeps` auto-provisioning
  (dev/16's standing rule: unchanged, still excluded for shared/passively-opened specs).
- The Validation and Optimization agents (OQ-011 remains open for them) and the
  `agent.generated-content-evaluator` (OQ-007).
- The `connection` attach target for Node Builder (the other `builtin.py:162` deferral —
  separate concern, untouched).
- Dataset discovery, agent sharing mechanics (D-0 = B), settings-profile machinery
  (built-ins seed empty defaults today; dev/16's `settingsDefaults` block is not
  representable in the roster — deviation D3).

## 3. Recommended Implementation Approach

### 3.1 Roster entry (the manifest, via the existing generator)

One `BuiltinAgentSpec`, appended with the composites:

- id `agent.package-recommendation`, name "Package Recommendation", category
  `"package"` (the category already exists in `_TARGET_BY_CATEGORY`), version rides
  `BUILTIN_VERSION`.
- capabilities `("package.recommend", "package.identify")`, contractVersion 1 (both
  advisory + proposal only); roles `("recommendation",)`.
- `targets=("node", "canvas")` (dev/16 `compatibleTargets`; the category default alone
  would be node-only).
- `reads=("mission", "targetContext", "installedTemplates")` — deviation D2: these three
  frontend `readFragment` producers exist (dev/67-2); dev/16's `installedPackages` read
  is served by the `packages.catalog` tool's installed flags instead of a new fragment.
- `tools=("packages.catalog", "packages.resolve", "package.install", "dataflow.read")` —
  all optional declarations (DEC-017 posture; a missing grant degrades to blind).
- `delegates_to=("agent.syntax-analysis-agent",)` (dev/16 §3.3 — extract imports/needs
  from proposed node code via `code.syntax.analyze`).
- `prompt_file="package_recommendation_instruction.txt"` (net-new, §3.5),
  `review_policy="review-before-apply"`.

The manifest falls out of `build_builtin_manifest` and validates through
`parse_agent_manifest` like every built-in; materialization, import/install, catalog
cards, palette row, and attachment chat all work with zero additional wiring.

### 3.2 Read tools (registry + executor)

Mirroring `catalog.search`'s shape and bounds:

- **`packages.catalog`** (read, v1): rows from `packages` domain catalog ∪ the current
  project's lockfile — `{dirName, packageId, label, description≤200, installed,
  builtin}` for every catalog package, bounded to ~40 rows with optional
  `{"q": "<text>"}` substring filtering. `curio.builtin@*` rows are flagged
  `builtin: true` and the description tells the model built-ins are always present and
  never proposed. Wrapper over the packages service the Nodes Catalog drawer uses — one
  truth.
- **`packages.resolve`** (read, v1): `{"dirNames": ["<dirName>", …]}` → per-package
  python/js dependencies, requested permissions, and conflicts against the current
  lockfile — the same resolver `packagesApi.resolve` fronts. This is what lets
  `package.identify` output carry deps/permissions/conflicts (dev/16 §3.2) without the
  agent inventing them.

Both are `execute_read_tool` branches; failures are data (`"error", <reason>`), output
bounded by `TOOL_RESULT_MAX_CHARS`.

### 3.3 The `package.install` mutate contract + apply

- **Registry entry** (mutate, v1): `Propose installing ONE node package from the Nodes
  Catalog into this project. Params: {"dirName": "<from packages.catalog results>",
  "reason": "why this work needs it"}.` Description states the review rule and that
  built-ins are never proposed.
- **Mint validation** (run-loop seam, exactly where `dataset.install` mints): the
  `dirName` must exist in the packages catalog, must not match `curio.builtin@*`
  (rejected with a corrective tool error), and an already-installed package mints
  nothing — the tool result says "already installed" (dev/16: no-op labeled installed).
  The proposal summary carries the package label + the model's `reason` (the why-needed
  rationale the card renders).
- **`_apply_package_install`** (in `apply_proposal`, beside `_apply_dataset_install`):
  re-resolve server-side; the package gone from the catalog or a **conflict** against
  the current lockfile is the drift analogue → `_mark_stale` + 409. Otherwise install
  through the existing packages service (`install_to_project` — lockfile write, dep
  provisioning, its own `spec_write_lock` serialization), then the standard
  applied-turn result card (package label, dirName, "installed to this project").
  Execution authority stays with the apply endpoint alone — the established invariant.

### 3.4 Frontend: the permissions dialog gates the apply

The one genuinely new UX mechanic. Today `applyProposal`
(`AgentAttachmentsProvider.tsx:393`) posts straight to the apply endpoint. A package
install must first show the existing review dialog (dev/16 §5: permissions +
dependencies + conflicts, `InstallPermissionsDialog` unchanged):

- A small agents-owned hook + host, `usePackageInstallReview` (under
  `agents/attach/`, per the dev/76 encapsulation rule; importing the shared
  `components/packages/publishing/InstallPermissionsDialog` is genuine cross-feature
  reuse, not duplication): given a pending `package.install` proposal's `dirName`, it
  loads `packagesApi.catalog()` (the row) + `packagesApi.resolve([dirName])`
  (conflicts), and renders the dialog.
- The apply dispatch branches on `proposal.tool === "package.install"`: instead of
  posting immediately, open the dialog; **the dialog's Install button is the apply
  trigger** (`agentsApi.applyProposal` fires on confirm), Cancel leaves the proposal
  pending (dismiss remains its own existing action). The backend re-checks conflicts
  regardless (§3.3) — the dialog is the review surface, the endpoint is the authority.
- The proposal card (AgentReviewCard variant) shows package label, why-needed rationale,
  and an installed-state line; no bespoke per-row install button (dev/16 §5). Applied
  state renders the standard result card.

### 3.5 Prompt (net-new, one file)

`package_recommendation_instruction.txt`, following the composites' instruction style:
role (identify/recommend node packages; never install, never author), the two modes
(recommend from a mission/graph; identify from proposed node/connection code — delegate
`code.syntax.analyze` for import extraction when code is present), the tool discipline
(candidates only from `packages.catalog` results; enrich with `packages.resolve`;
propose via ONE `package.install` toolRequest per package with a concrete why-needed
reason; already-installed and `builtin: true` rows are answers, not proposals), and the
honesty rule (a need it cannot ground in a catalog row is reported as a finding, not a
proposal — no sideloading, mirroring dev/16's not-in-catalog edge).

### 3.6 Parent wiring + recorded deviations

Add `"agent.package-recommendation"` to `delegates_to` of:

- `agent.dataflow-builder` (closes the `builtin.py:199` deferral — its delegation
  paragraph now auto-offers `package.recommend`/`package.identify`; no prompt edit
  needed, `visible_capability_entries` generates the offer),
- `agent.node-builder` (a built node's required packages),
- `agent.connection-builder` (dev/16 §3.3's migrated-manifest addendum).

A missing installed template resolves through the existing missing-specialist
`project.install` proposal (`delegation.resolve` — REQ-ORCH-001), no new code.

**Deviations from dev/16, recorded here:**

- **D1 — manifest shape**: generated by the roster (`build_builtin_manifest`), so no
  `$schema`/`contracts`/`configuration` blocks and `runtime.execution: "foreground"` —
  dev/16's `"background"` predates the foreground-only posture the Dataset Finder
  deviation already recorded. Tool ids are the registry's (`packages.catalog`,
  `packages.resolve`, `package.install`), not dev/16's un-namespaced draft ids.
- **D2 — `installedPackages` read**: served by `packages.catalog`'s installed flags,
  not a new frontend fragment producer (`installedTemplates` already covers the palette
  registry; a third package-shaped fragment would duplicate the tool).
- **D3 — `settingsDefaults` (`mutation-proposal` profile)**: not representable in the
  roster today — built-ins seed empty defaults (BL-P3-08 behavior). The
  review-before-apply policy carries the actual product requirement.
- **D4 — Connection Builder byte-identity**: the dev/48 regression pinned the thirteen
  migrated manifests byte-identical; adding `delegatesTo` to Connection Builder is a
  deliberate spec'd change (dev/16 §3.3), so that regression's expectation updates for
  exactly this one manifest, in the same commit, with the memo reference.

## 4. Data and State Handling

| Data | Source of truth | Consumers |
| --- | --- | --- |
| Installed packages | current project lockfile (`spec.dataflow.packages`, packages domain) | `packages.catalog` installed flags, resolve conflicts, apply |
| Recommendable set | packages catalog (packages domain) | `packages.catalog` rows, mint validation |
| Deps/permissions/conflicts | packages resolver | `packages.resolve` tool, InstallPermissionsDialog, apply re-check |
| The proposal | attachment record + session transcript (existing single-active-slot machinery) | card, apply endpoint |

- The agent owns no package state; every read is a thin domain wrapper (ADR-AG-007).
- Apply-time drift: package gone or conflicting → 409 + `stale` (the `dataset.install`
  pattern); re-proposing an installed package is a mint-time no-op.
- Lockfile concurrency: `install_to_project` already serializes under the project spec
  lock (`packages/services.py::_write_lockfile`); the agents layer adds no second
  writer.
- Project switch clears proposals with the rest of the attachment state (existing).
- Privacy (D-0 = B): recommendations/identified packages live in the agent session
  only; `strip_agent_state` already excludes agent sections from shares — regression
  test pins that no new shared surface appears.

## 5. UI and UX Requirements

- Package proposals render in the unified agent chat as reviewed proposal cards:
  package label, why-needed rationale, installed-state line — visually consistent with
  the `dataset.install` card; no bespoke install button.
- Confirming opens the **existing** `InstallPermissionsDialog` unchanged (permissions,
  python/js dependencies, conflicts; Install disabled on unresolved conflicts); Install
  applies, Cancel returns to the pending card.
- The catalog card / palette row for Package Recommendation behaves like every built-in
  (Install/Uninstall pills, `Package` category chip, action-free draggable palette
  row) — free from the roster entry.
- Dataflow Builder delegation: package steps appear in the existing delegated-
  specialists transcript surface; a missing Package Recommendation template shows the
  existing reviewed `Install in project` proposal.
- Accessibility: proposal card text is real text (screen-reader-friendly rationale);
  the dialog's existing semantics are reused; no new focus traps — the dialog host
  manages focus exactly as the Nodes Catalog drawer usage does.

## 6. Edge Cases

1. Required library provided by `curio.builtin@*` → never proposed (mint rejects;
   catalog rows flag `builtin: true`; prompt says so).
2. Package already installed → tool result says installed; no proposal minted.
3. Resolve conflict at apply time → 409 + stale card; the user resolves via the
   existing package UI; the agent never force-resolves.
4. Dependency (pip/js) failure during apply → the packages service's own error surfaces
   through the apply error path; lockfile unchanged (existing service semantics).
5. Recommendation not in the catalog → finding text, not a proposal; agents never
   sideload (the user's own Import package footer is untouched).
6. Delegate not installed → reviewed `project.install` proposal via the existing
   missing-specialist path; never silent.
7. Node Builder proposes a node AND identifies a package in one turn → two proposals
   through the existing single-active-slot machinery (the second queues exactly as
   multi-proposal turns do today); each applies through its own review.
8. Dialog data fails to load (catalog/resolve error) at apply time → the apply is not
   sent; the card shows the fetch error and stays pending.
9. Shared/passively-opened dataflow → attachments/apply already require the active
   authorized project; `useEnsureWorkflowDeps` exclusions unchanged.
10. Proposal minted, package uninstalled-then-conflicting later → the apply re-check
    catches it (drift 409), never a partial install.

## 7. Testing Strategy

Backend (`tests/test_agents/`):

- **Roster/manifest**: 17-agent roster validates; the new manifest's capabilities,
  targets, tools, delegatesTo, review policy; prompt files exist (extends
  `test_builtin.py`'s existing invariants); Connection Builder's manifest change is
  asserted (D4 — the byte-identity expectation updates deliberately).
- **Tools**: `packages.catalog` rows (installed flags, builtin flags, bounds, `q`
  filter); `packages.resolve` deps/permissions/conflicts pass-through; error framing.
- **Mint**: valid dirName mints a proposal with label+reason summary; builtin dirName
  → corrective error; installed dirName → "already installed" result, no proposal.
- **Apply**: happy path installs to the current project lockfile (packages service
  called with the right project), applied turn + result card; conflict/absent package →
  409 + stale in both homes; never touches other lockfile entries.
- **Delegation**: the three parents resolve `package.identify`/`package.recommend` to
  the installed template; missing template yields the `project.install` proposal
  (extends existing delegation tests).
- **Privacy regression**: `strip_agent_state` posture unchanged — package proposals
  never enter the shared spec surface.

Frontend (jest):

- `usePackageInstallReview`: loads row+resolve, exposes dialog props, apply fires only
  on dialog confirm, cancel keeps the proposal pending, load error surfaces without
  applying.
- Review-card variant: label + rationale + installed line render; apply path branches
  to the dialog for `package.install` and NOT for other tools (regression).
- Full suites + `tsc --noEmit` (the two pre-existing tsconfig notices only).

## 8. Acceptance Criteria

1. `agent.package-recommendation@1.0.0` appears in the Global Catalog, imports,
   installs, attaches (node + canvas), and runs with materialized prompts like any
   built-in; the roster count is 17.
2. Asked to recommend/identify, it grounds candidates in `packages.catalog` rows and
   emits at most one reviewed `package.install` proposal per package, each with a
   why-needed rationale; built-ins and installed packages are never proposed.
3. Applying a package proposal shows the existing `InstallPermissionsDialog`
   (permissions + dependencies + conflicts) and only its Install button triggers the
   apply; the backend installs through the existing packages service into the current
   project's lockfile; conflicts/absence yield 409 + a stale card.
4. Node Builder, Connection Builder, and Dataflow Builder offer the package
   capabilities in their delegation paragraphs; a missing Package Recommendation
   template produces the reviewed `Install in project` proposal.
5. No new install mechanism, no silent install, no agent-authored packages, no change
   to `useEnsureWorkflowDeps`; recommendations remain agent-private (share regression
   green).
6. Full backend agents suite + frontend jest + tsc green; the four deviations (D1–D4)
   are visible in code comments where they bite.

## 9. Recommended Commit Breakdown

1. **Commit 1 — backend tools + roster**: `packages.catalog`/`packages.resolve`
   contracts + executors, the roster entry, the net-new instruction prompt, roster
   tests. (The agent exists and can read; nothing mutates yet.)
2. **Commit 2 — backend proposal lane**: `package.install` contract, mint validation,
   `_apply_package_install`, apply/mint/drift tests.
3. **Commit 3 — parent wiring**: `delegates_to` additions (incl. the D4 regression
   update) + delegation tests.
4. **Commit 4 — frontend review flow**: `usePackageInstallReview` + dialog host +
   card variant + apply-branch wiring, with component/hook tests.
5. **Docs commit**: memo flip + BL-P5 entry + `docs/AGENTS.md` roster update.

## 10. Engineering Quality Checklist

- [ ] Only `agent.package-recommendation` declares `package.*`; parents delegate.
- [ ] All tool implementations are thin wrappers over the packages domain; the agents
      module owns no package knowledge (ADR-AG-007).
- [ ] Mutate execution authority stays with `apply_proposal`; the dialog is review,
      not authority; conflicts re-checked server-side.
- [ ] Built-in exclusion enforced in three layers (tool rows, mint, prompt).
- [ ] The dev/48 byte-identity regression updates only for Connection Builder, with
      the dev/16/84 reference in the test.
- [ ] Frontend additions live under `agents/` (dev/76); `InstallPermissionsDialog` is
      imported, never duplicated.
- [ ] No fabricated data: rationale is the model's, deps/permissions/conflicts come
      from the resolver, nothing invented at render time.
- [ ] Full backend pytest (agents + packages suites) and frontend jest + tsc verified
      before each commit, per the build-log convention.
