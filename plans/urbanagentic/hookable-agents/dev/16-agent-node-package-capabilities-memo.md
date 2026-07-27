# Implementation Memo: Agent Node-Package Capabilities (Identify, Suggest, Install)

This memo specifies how the node-building agents identify, suggest, and install **node packages**, and
specifies the previously named-only **Package Recommendation** agent (partially closing `OQ-011` from
`14-plan-hardening-and-open-decisions-memo.md`). It builds on the composite specs
(`15-composite-agent-specifications-memo.md`), the capability model (`08-semantic-agent-capabilities-memo.md`),
the current lifecycle (`12-...-memo.md`, `DEC-029`–`DEC-033`), and the sharing scope of memo `14`
(D-0 = B). It reuses Curio's **existing** node-package install product; it defines no new package
mechanism. Where this memo and an image differ, this specification is authoritative.

## 1. Problem Statement

Node packages are a first-class Curio resource with a complete real product — a per-project lockfile
(`spec.dataflow.packages`), a reviewed install dialog (`InstallPermissionsDialog`: permissions +
dependencies + conflicts), `packagesApi.resolve` / `installToProject` / `uninstallFromProject`, declared-
dependency provisioning (`useEnsureWorkflowDeps`), the "Packages" palette, and the Nodes Catalog drawer.
The agents plan, however, does **not** connect any agent to that product:

- "Package Recommendation" is **named only** (`docs/01:46`, `docs/02:75`, `docs/09:99-105`, scene 01
  card) with no manifest, no capability, and no hook contract — it is `OQ-011`.
- The Dataflow Builder plan card lists a **"Recommend packages"** step (`render...py:2283`), but its
  delegate target is unspecified and "resolved only if installed" (`dev/15:103-104`).
- **Node Builder** and **Connection Builder** are package-agnostic in the plan: a Node Builder node or a
  Connection Builder connection may require a node package (and its python/js libs) to run, yet nothing
  identifies or proposes installing it. A user must notice the missing package themselves.

**Expected behavior.** The agents that build nodes/connections/dataflows identify the node packages their
work requires, surface them as **reviewed** install suggestions, and drive installation **through the
existing package install flow** (permissions + dependencies + conflicts, per-project lockfile) — never a
silent install, never a new package mechanism, and never authoring/publishing a package (that stays in
the existing package-publishing product, out of scope).

## 2. Scope

**Included.** A `package.*` capability family (`package.recommend`, `package.identify`); a manifest and
capability set for `agent.package-recommendation`; `delegatesTo` wiring so `agent.node-builder`,
`agent.connection-builder`, and `agent.dataflow-builder` obtain required-package identification and emit
reviewed install proposals; the reviewed-install contract that reuses `InstallPermissionsDialog` /
`packagesApi.resolve` / `installToProject`; privacy/no-leak, no-silent-install, and no-authoring
invariants; tests, acceptance criteria, and traceability.

**Out of scope.** Authoring, forking, or publishing node packages by agents (existing package-publishing
product); changing the real package install/lockfile/dependency mechanism; the auto-install of dataflow-
declared dependencies (`useEnsureWorkflowDeps`), which is unchanged; dataset discovery (owned by Dataset
Finder, `dev/15`); the Validation and Optimization agents (still `OQ-011`); any new sharing mechanic
(D-0 = B); application code.

## 3. Recommended Implementation Approach

### 3.1 Model: packages are a distinct resource; agents recommend, never author

A node package is neither an agent nor a dataset. Agents interact with packages only in the
**identify → suggest → reviewed install** direction, always against the **existing** Nodes Catalog and
per-project lockfile:

1. **Identify** — resolve which catalog node package (and its python/js deps, permissions, conflicts) a
   proposed node/connection/plan requires. Built-in packages (`curio.builtin@*`) are always present and
   are never proposed.
2. **Suggest** — surface each required-but-not-installed package as a reviewed package-install proposal in
   the unified agent chat, with its why-needed rationale. No bespoke per-row install button; the proposal
   is confirmed like any other reviewed agent action.
3. **Install (reviewed)** — confirming opens the existing `InstallPermissionsDialog` (permissions +
   dependencies + conflicts via `packagesApi.resolve`); on confirm, `packagesApi.installToProject(projectId,
   dirName)` writes the **current project's** lockfile. Agents never call install silently and never bypass
   the permissions/conflict review.

This mirrors the dataset two-lane contract (`dev/15`, `docs/06`): a catalog dataset installs through the
existing dataset flow; a node package installs through the existing package flow. It also mirrors the
agent lifecycle rule — installing anything that grants permissions or pulls code is a **reviewed** action,
never auto-chained.

### 3.2 Capability IDs introduced by this memo

Contract version `1`; IDs contain no `_prompt`/`.txt`/path tokens (`08`, `docs/11:334`).

| Capability ID | Declared by | Contract summary (inputs → outputs) |
| --- | --- | --- |
| `package.recommend` | `agent.package-recommendation` | mission + node/graph context + installed packages + catalog → ranked node-package candidates with why-needed rationale (recommendation only; no install) |
| `package.identify` | `agent.package-recommendation` | a proposed node/connection/fetch-node/plan → the specific catalog node packages it requires, each resolved with python/js deps, requested permissions, and conflicts, as a reviewed install proposal |

Both are **advisory + proposal** only. Neither installs; installation is the user's reviewed action
through the existing package install dialog. Recommending or identifying a package grants nothing —
each install re-authorizes through `InstallPermissionsDialog`.

### 3.3 Delegation wiring

`agent.package-recommendation` is the specialist that owns both capabilities. The build agents delegate
to it (they do not declare `package.*` themselves), so package identification stays in one place:

```text
agent.package-recommendation  (declares package.recommend, package.identify)
  delegatesTo → agent.syntax-analysis-agent   (code.syntax.analyze)   # extract imports/needs from proposed node code

agent.node-builder        delegatesTo → + agent.package-recommendation   # a built node's required packages
agent.connection-builder  delegatesTo →   agent.package-recommendation   # a proposed connection's required packages
agent.dataflow-builder    delegatesTo → + agent.package-recommendation   # the "Recommend packages" plan step
```

- **Node Builder** (`dev/15`): when `node.build` / `dataset.fetch.author` produces a node whose code
  imports a library provided by a catalog package, it delegates `package.identify` and emits the
  package-install proposal **alongside** its node preview (still one reviewed apply per graph mutation).
- **Connection Builder** (`agent.connection-builder`, migrated in `dev/06`): gains
  `delegatesTo: [agent.package-recommendation]` so a proposed connection that requires a package surfaces
  the same reviewed proposal. This is an addendum to its migrated manifest; its `connection.propose`
  capability is unchanged.
- **Dataflow Builder** (`dev/15`): its "Recommend packages" plan step delegates to
  `agent.package-recommendation` (`package.recommend`); a missing Package Recommendation template yields
  a reviewed `Install in project` proposal, never a silent install (`REQ-ORCH-001`).

### 3.4 `agent.package-recommendation` manifest

```json
{
  "$schema": "../../docs/schemas/agent-package.v1.json",
  "id": "agent.package-recommendation",
  "name": "Package Recommendation",
  "category": "package",
  "version": "1.0.0",
  "purpose": "Identify and recommend the node packages a task, node, or dataflow needs, and surface each required-but-uninstalled package as a reviewed install proposal against the existing Nodes Catalog.",
  "roles": ["recommendation"],
  "capabilities": [
    { "id": "package.recommend", "contractVersion": "1" },
    { "id": "package.identify", "contractVersion": "1" }
  ],
  "delegatesTo": ["agent.syntax-analysis-agent"],
  "prompts": {
    "system": { "path": "prompts/default_preamble.txt", "sha256": "<sha256>", "variables": [] },
    "instruction": { "path": "prompts/package_recommendation_instruction.txt", "sha256": "<sha256>", "variables": ["mission", "nodeContext", "graphContext", "installedPackages"] }
  },
  "contracts": {
    "inputSchema": "schemas/input.schema.json",
    "outputSchema": "schemas/output.schema.json"
  },
  "compatibleTargets": [
    { "kind": "node", "requires": [] },
    { "kind": "canvas", "requires": [] }
  ],
  "inputs": {
    "reads": ["mission", "nodeContext", "graphContext", "installedPackages", "catalog"],
    "requiredConfig": []
  },
  "outputs": ["packageRecommendations", "packageInstallProposals"],
  "configuration": {
    "options": ["maxRecommendations", "tokenBudget"],
    "defaults": { "maxRecommendations": 5 }
  },
  "runtime": { "execution": "background", "reviewPolicy": "review-before-apply" },
  "providerRequirements": { "capabilities": ["structured-output"] },
  "tools": [
    { "id": "packages.catalog", "required": true },
    { "id": "packages.resolve", "required": false }
  ],
  "settingsDefaults": {
    "profileId": "mutation-proposal",
    "profileVersion": "1",
    "suggestions": {
      "quota": { "maxConcurrentExecutions": 1 },
      "resource": { "resourceClass": "standard", "network": "provider-and-authorized-tools-only" },
      "promptQuality": { "staticChecksAfterEdit": true, "requiredBeforeRelease": true }
    }
  },
  "provenance": { "publisher": "curio", "license": "MIT", "trust": "built-in" }
}
```

Notes: `category: "package"` matches the catalog's Package chip (`render...py:1279`) and the scene-01 card.
`tools` are typed allowlisted **requirements** mapping to the existing `packagesApi.catalog` / `resolve`
surfaces — not executable code or install grants (`docs/11:158`). Profile family `mutation-proposal`
because a package install is a reviewed project mutation. Prompt provenance is **net-new** (no migrated
prompt), authored as a built-in seed and subject to the same validation/evaluation gates.

## 4. Data and State Handling

- **Source of truth.** The installed set is the **current project's** package lockfile
  (`spec.dataflow.packages`), read via `packagesApi.getProjectPackages(projectId)`; the recommendable set
  is `packagesApi.catalog()`. Agents read both; they never maintain their own package store.
- **Reviewed install.** A confirmed proposal runs `packagesApi.resolve(dirNames)` for conflicts, opens
  `InstallPermissionsDialog` (permissions + python/js dependencies + conflicts), and on confirm calls
  `packagesApi.installToProject(projectId, dirName)`. Built-ins (`curio.builtin@*`) are never proposed
  (always installed, non-uninstallable).
- **Auto-install unchanged.** Once an agent-proposed node is added and the dataflow declares a package
  dependency, the existing `useEnsureWorkflowDeps` provisioning behaves as today. Its security rule
  stands: no auto-install for passively-opened foreign/shared specs. Agent-surfaced installs are always
  reviewed at the suggestion boundary.
- **Loading/empty/error/success.** Recommendations show ranked candidates with an installed/not-installed
  chip; an already-installed package is a no-op labeled installed; a resolve conflict blocks install until
  the user resolves it; a pip/js dependency failure surfaces the existing install-dialog error and leaves
  the lockfile unchanged.
- **No stale/duplicated state.** Project switching clears package recommendations/proposals with the rest
  of the agent state. Recommended/identified packages and their code are **agent-private** and excluded
  from the shared result (existing exclusion lists — `docs/01:112`, `docs/09:197`, `dev/03:717`).

## 5. UI and UX Requirements

- **Where it appears.** Package suggestions render in the unified agent chat as reviewed proposals (like
  the Dataflow Builder `Install in project` proposal and the Dataset Finder handoff), naming the package,
  its why-needed rationale, and its install-state chip. No bespoke per-row install button.
- **Reviewed install dialog.** Confirming opens the existing `InstallPermissionsDialog` unchanged —
  Permissions requested, Dependencies (python/js), and Conflicts, with Cancel / Install (Install disabled
  on unresolved conflicts). This is the established Nodes Catalog install pattern; agents introduce no new
  install UI.
- **Catalog + palette consistency.** The Package Recommendation card uses the same catalog card controls
  as every other agent (dark `Install` / neutral `Uninstall` / `Publish` pill in My Imports) and the
  `Package` category chip; once installed it is a draggable action-free AGENTS palette row.
- **Dataflow Builder plan.** The "Recommend packages" step is delegated to Package Recommendation and its
  status appears in the delegated-specialists card; a missing template shows the reviewed `Install in
  project` proposal.
- **Accessibility.** Package proposals and the install dialog expose semantic labels, focus management,
  non-color install-state, and screen-reader-friendly rationale text (WCAG 2.2 AA).

## 6. Edge Cases

- A required library is provided by a **built-in** package (`curio.builtin@*`) → never proposed (already
  installed, non-uninstallable).
- The required package is **already installed** in the project → shown as installed; no proposal.
- `packagesApi.resolve` reports a **version conflict** → install blocked; the dialog shows conflicting
  ranges and the "uninstall one of the conflicting packages" hint; the agent does not force-resolve.
- A python/js dependency **fails to install** → existing install-dialog error; lockfile unchanged; the
  proposed node still needs review before it can run.
- The recommended package is **not in the catalog** → the agent recommends only catalog packages; it never
  sideloads an arbitrary archive (untrusted). The user may use the existing "Import package" footer
  themselves; agents do not drive sideload.
- A **shared/passively-opened** dataflow → no auto-install (existing `useEnsureWorkflowDeps` security
  rule); agent proposals require the active project and an authorized actor.
- Node Builder proposes a node **and** a package in one turn → still one reviewed apply per graph mutation;
  the package install is its own reviewed dialog.
- Delegated `agent.package-recommendation` is **not installed** → Dataflow/Node/Connection Builder emit a
  reviewed `Install in project` proposal for it; never a silent install.
- A package requests **broad permissions** → surfaced verbatim in the permissions list; the user decides;
  the agent never pre-accepts permissions.

## 7. Testing Strategy

- **Capability contracts.** `package.recommend` and `package.identify` input/output schema validity; IDs
  contain no prompt/path tokens; `package.identify` output carries per-package deps/permissions/conflicts.
- **Manifest.** `agent.package-recommendation` validates against `agent-package.v1.json` (category
  `package`, both capabilities, `mutation-proposal` profile, built-in trust, contained digest-verified
  net-new prompts, typed `packages.*` tool requirements).
- **Reviewed install.** A confirmed proposal calls `packagesApi.resolve` and opens
  `InstallPermissionsDialog` with permissions + dependencies + conflicts; on confirm calls
  `installToProject` with the **current** project ID; never installs silently; never bypasses conflicts;
  never proposes a `curio.builtin@*` package.
- **Delegation.** Node Builder / Connection Builder / Dataflow Builder resolve `agent.package-recommendation`
  only among current-project templates; a missing template yields a reviewed `Install in project` proposal;
  Dataflow Builder's "Recommend packages" step delegates to `package.recommend`.
- **Privacy / D-0 = B.** Regression guard that recommended/identified packages and their code are not added
  to Curio's existing flow-sharing as a new shared surface.
- **Idempotency / concurrency.** Re-proposing an installed package is a no-op; concurrent installs use the
  existing resolve/lockfile concurrency; project switch clears proposals.
- **Accessibility.** Package proposal and install dialog meet WCAG 2.2 AA.

## 8. Acceptance Criteria

- `agent.package-recommendation` is specified with a schema-valid manifest, `package.recommend` +
  `package.identify` capabilities, `Node / canvas` hook, `mutation-proposal` profile, and net-new prompt
  provenance.
- `agent.node-builder`, `agent.connection-builder`, and `agent.dataflow-builder` delegate to
  `agent.package-recommendation`; none declares `package.*` itself.
- Building a node/connection/dataflow that requires an uninstalled catalog package surfaces a reviewed
  package-install proposal with a why-needed rationale.
- Installing an agent-suggested package reuses the existing `InstallPermissionsDialog` (permissions +
  dependencies + conflicts) and `installToProject` against the current project lockfile — never silent,
  never a new mechanism.
- Built-in packages are never proposed; conflicts block install; auto-install of dataflow-declared deps is
  unchanged and still excluded for shared/passive specs.
- Agents never author, fork, or publish a node package.
- Recommended/identified packages and their code remain agent-private and excluded from shares (D-0 = B).
- The Dataflow Builder "Recommend packages" plan step resolves to `package.recommend`, and a missing
  Package Recommendation template yields a reviewed `Install in project` proposal.

## 9. Recommended Commit Breakdown

1. `feat(agents-manifest): add package.recommend/package.identify capability contracts` with schema + ID-format tests.
2. `feat(agents-manifest): add agent.package-recommendation manifest + net-new prompt assets` with reviewed-install-proposal tests.
3. `feat(agents): wire node-builder/connection-builder/dataflow-builder delegatesTo package-recommendation` with delegation-resolution and missing-template proposal tests.
4. `feat(agents): route agent package-install proposals through the existing InstallPermissionsDialog/installToProject` with per-project-lockfile and conflict tests.
5. `test(agents-package): privacy/D-0 and built-in/auto-install regression coverage`.

## 10. Engineering Quality Checklist

- [ ] `package.recommend` / `package.identify` are advisory + proposal only; neither installs.
- [ ] Only `agent.package-recommendation` declares `package.*`; build agents delegate, never declare.
- [ ] Agent package installs reuse the existing reviewed dialog and per-project lockfile; no silent install, no new mechanism.
- [ ] Built-in (`curio.builtin@*`) packages are never proposed; conflicts block install; permissions are never pre-accepted.
- [ ] `useEnsureWorkflowDeps` auto-install is unchanged and still excluded for shared/passively-opened specs.
- [ ] Agents never author, fork, or publish a node package.
- [ ] Recommended/identified packages and their code are excluded from Curio's existing flow-sharing (D-0 = B).
- [ ] A missing `agent.package-recommendation` template yields a reviewed `Install in project` proposal, never auto-install.
- [ ] Package Recommendation uses the same catalog card controls, `Package` category chip, and action-free palette row as every other agent.
