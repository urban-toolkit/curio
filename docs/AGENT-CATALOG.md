# Agent Catalog

The Agent Catalog is where Curio's **hookable agents** live. It is the third of
three catalogs, alongside the [Node Catalog](NODE-CATALOG.md) and the
[Data Catalog](DATA-CATALOG.md). Where the Node Catalog manages the *nodes* you
drop on the canvas and the Data Catalog manages the *data* those nodes read, the
Agent Catalog manages the *assistants* you attach to them.

This guide covers the catalog: what an agent package is, where its state lives,
the three surfaces you manage agents from, and which layer each action writes.
For the agent runtime itself, meaning the manifest contract, capabilities,
prompts, tools, and the chat and review loop, see [AGENTS.md](AGENTS.md). The two
do not overlap: this file is the catalog model, that one is the agent model.

This guide is in five parts, plus operator notes:

- [1. What is the Agent Catalog?](#1-what-is-the-agent-catalog): the storage layers, agent ids, and what ships built in.
- [2. Surfaces and workflows](#2-surfaces-and-workflows): the three places you manage agents, the action matrix, and walkthroughs.
- [3. Using an agent in a dataflow](#3-using-an-agent-in-a-dataflow): adding, attaching, and the difference between the two.
- [4. Importing, publishing, and sharing](#4-importing-publishing-and-sharing): authoring your own definitions.
- [5. Settings and limits](#5-settings-and-limits): the three policy scopes and where each is edited.
- [Operator notes](#operator-notes): the provider requirement, launcher flags, and quotas.

---

## 1. What is the Agent Catalog?

### Concept

An **agent** in Curio is a small self-contained folder, shaped like a node
package, identified by a reverse-domain id and a version:

```
<agentId>@<version>     e.g.   agent.node-explainer@1.0.0
                               agent.dataflow-builder@1.0.0
```

The folder holds a `manifest.json` (the contract) and the prompt assets the
manifest references by digest:

```
agent.node-explainer@1.0.0/
  manifest.json
  prompts/single_box_explanation_prompt.txt
```

Agent ids always begin with **`agent.`**, which keeps them distinct from node
package ids (`curio.builtin`, `ai.urbanlab.uhvi`) and dataset ids
(`data.urbanlab.chicago-boundary`). The manifest is validated against
[`docs/schemas/agent-package.v1.json`](schemas/agent-package.v1.json); see
[AGENTS.md section 2](AGENTS.md#2-the-agent-manifest) for the field table.

**Twenty-one agents ship with Curio**, declared in
[`app/agents/builtin.py`](../utk_curio/backend/app/agents/builtin.py) and
materialized into each user's store on first use. They cover the five categories
below, and among them are the agents that replaced Curio's earlier built-in AI
assistance: `agent.node-explainer` (which superseded the per-node Explanation
tab) and `agent.node-content-builder` (which superseded the authoring assistant).

### Categories

Every agent declares one `category`, which is the manifest's own vocabulary and
what the browse page's rail counts:

| Category | What the agent acts on |
|---|---|
| `node` | One node: its content, its errors, its output. |
| `canvas` | The whole dataflow: planning, explanation, suggestion. |
| `data` | Datasets and data shape. |
| `evaluate` | Review, validation, and scoring. |
| `package` | Node packages: recommending and resolving them. |

Categories are **not** a separate colour family. Each maps onto a bucket that
already exists in Curio's palette
([`agentCategoryStyle.ts`](../utk_curio/frontend/urban-workflows/src/components/menus/nodes/agentsPalette/agentCategoryStyle.ts)),
so a hue means the same thing across all three catalogs and the canvas: `data`
reuses the data-node blue, `evaluate` the computation purple, `canvas` the
dataflow slate, and `node` and `package` the neutral package grey. No agent
surface declares a colour of its own.

### Origins

Alongside its category, every card carries an **origin**, which is provenance
rather than function, and which the browse page also rails on:

| Origin | Meaning |
|---|---|
| `builtin` | Shipped with Curio. |
| `published` | Published into the shared catalog and browsable by every user on this install. |
| `imported` | A definition you authored and imported into your own account. |

### The storage layers

Agent state lives on the **filesystem, not the database.** Curio's database holds
users and the project index; agents, like node packages and datasets, are files
under `.curio/` and inside each project's spec. There are no agent tables and no
migrations.

Knowing which layer each action writes is the key to predicting what happens
after an **Add to dataflow**, a **Remove from dataflow**, or an **Attach**:

| Layer | On disk | Who writes |
|---|---|---|
| **Definition store**, the immutable agent itself | `.curio/users/<user-key>/agents/<agentId>@<version>/` (`manifest.json` + `prompts/`) | Seeded from the built-ins; **Import agent** adds one; **Publish** copies one to the shared catalog. |
| **My imports** (account) | `.curio/users/<user-key>/imported-agents.json` | **Import agent** adds a coordinate; removing an import drops it. The analogue of `default-packages.json`. |
| **In dataflow** (per-dataflow lockfile) | `spec.trill.json` then `dataflow.agents[]` | **Add to dataflow** adds an entry for the open dataflow; **Remove from dataflow** removes it. |
| **Per-dataflow defaults** | `spec.trill.json` then `dataflow.agentDefaults` | Materialized by **Add to dataflow**, edited by the card's settings cog, dropped on removal. |
| **Attachments**, a private agent instance bound to a target | `spec.trill.json` then `dataflow.agentAttachments` | **Attach** (dragging an agent onto a node or the canvas) creates one; **Detach** deletes it and its transcript. |
| **Usage ledger** | `.curio/users/<user-key>/agents/ledger/<date>.jsonl` | Every run appends a reserve and settle pair. Append-only; not user-editable. |

The same tolerances apply as elsewhere in the catalog: a missing registry file
is an empty list, a corrupt one is treated as empty (reads never raise), and one
invalid definition directory is skipped rather than failing the listing. Every
path resolves through the shared containment guard
([`app/common/safe_paths.py`](../utk_curio/backend/app/common/safe_paths.py)), so
a coordinate cannot escape the user's store.

> [!NOTE]
> **Adding is not attaching.** Adding an agent to a dataflow makes it available
> in that dataflow's palette. Attaching it creates a private instance bound to
> one node, one connection, or the canvas, with its own chat transcript and its
> own settings. One added agent can carry many attachments. See
> [part 3](#3-using-an-agent-in-a-dataflow).

### Agent coordinates

The backend identifies an agent by its **coordinate**, `<agentId>@<version>`,
written `coord` throughout the API and `dirName` on a card. It is the agent
equivalent of a dataset's `datasetId@major` and a node package's `dirName`.
Unlike those two, an agent version is a full semver string rather than a major,
because an agent definition is immutable: publishing a change means bumping the
version, and an upload against an existing coordinate is refused with a `409`.

---

## 2. Surfaces and workflows

There are three places you interact with agents, and as with the Data Catalog
they are **not** interchangeable:

- **The `/catalog/agents` page** is the account-level library view. Reach it from
  `/projects` and the **Agent Catalog** tab in the section nav. You can browse,
  filter by category and origin, search, read an agent's full detail, and add an
  agent to your account. You **cannot add an agent to a dataflow from here**,
  because adding is relative to a dataflow and this page has none.
- **The Agent Catalog drawer** (inside the canvas) is the working surface. Open
  it from the top menu **Data** then **Agent Catalog**, or from the left Tools
  panel's **Agent Catalog** dropdown and **Browse Agent Catalog +**. Everything
  scoped to the open dataflow happens here: Add to dataflow, Remove from
  dataflow, Import agent, Publish, Unpublish, and the per-dataflow settings cog.
- **The Agent palette** (left Tools panel, the **Agent Catalog** dropdown) holds
  the agents already added to this dataflow, ready to drag onto a node or the
  canvas to attach. It sits in the left rail below the **Node Catalog** and
  **Data Catalog** dropdowns, mirroring both.

The drawer has three tabs: **Browse all** (the default), **My imports**, and
**In dataflow**. There is no Featured tab. The two peers declare one, but the
Node drawer maps it onto Browse all as a dead member, and agents have nothing to
feature; a tab that renders the same rows under a second name is worse than
three honest ones.

### Action matrix

| Action | Where | Endpoint | Layers it writes | What you see |
|---|---|---|---|---|
| **Add to dataflow** | Drawer | `POST /api/agents/projects/<id>/install` | per-dataflow lockfile + defaults record | The agent appears in this dataflow's **Agent Catalog** palette, ready to drag. Any agent it requires is added with it. |
| **Remove from dataflow** | Drawer, or the **In dataflow** tab | `DELETE /api/agents/projects/<id>/<coord>` | per-dataflow lockfile + defaults record | Confirms first. It leaves this dataflow's palette; the definition and the account-level import are **kept**. Refused if another added agent requires it. |
| **Add to my account** | `/catalog/agents` detail drawer | `POST /api/agents/imports` | My imports | The agent is available to add to any of your dataflows. It is **not** added to any of them. |
| **Remove from my account** | Drawer (**My imports** tab), or the `/catalog/agents` detail drawer | `DELETE /api/agents/imports/<coord>` | My imports | It leaves your account list. The definition stays on disk and dataflows that already added it are untouched. |
| **Import agent** | Drawer footer | `POST /api/agents/imports/upload` | definition store + My imports | Your own `manifest.json` and prompt files are registered as a definition. Never adds to a dataflow and never publishes. |
| **Publish** | Drawer (owned imports only) | `POST /api/agents/publications` | shared catalog | The definition becomes browsable by every user on this install. |
| **Unpublish** | Drawer | `DELETE /api/agents/publications/<coord>` | shared catalog | The listing goes away. Copies already added to dataflows are untouched. |
| **Attach** | Drag a palette row onto a node or the canvas | `POST /api/agents/projects/<id>/attachments` | attachments | A private instance with its own chat panel. Requires the agent already added. |
| **Detach** | The attachment's own control | `DELETE /api/agents/projects/<id>/attachments/<aid>` | attachments | The instance and its transcript are deleted. The agent stays added. |

Only **Remove from dataflow** asks for confirmation, matching the Node and
Data drawers; the rest act immediately. Nothing in this table deletes an agent
definition from disk: **Remove from my account** drops the registry entry and
leaves the folder, which is why it is not called Delete.

### Workflows

**I want to use an agent in my dataflow.** Open the dataflow, then **Data** and
**Agent Catalog**. Find the agent, click **Add to dataflow**. It now appears in
the left Tools panel's **Agent Catalog** dropdown. Drag it onto a node or onto
empty canvas to attach it, which opens its chat panel.

**I want to browse everything available without opening a dataflow.** Go to
`/projects` and pick the **Agent Catalog** tab. Filter by category or origin in
the left rail, click a card to read its full detail, and use **Add to my
account** to keep it. Open a dataflow afterwards to add it there.

**I want to write my own agent.** Author a `manifest.json` and its prompt files
([AGENTS.md section 2](AGENTS.md#2-the-agent-manifest)), then use the drawer's
**Import agent** footer button. It lands in **My imports** as your own
definition. Adding it to a dataflow and publishing it are separate actions.

---

## 3. Using an agent in a dataflow

**Adding** an agent writes its coordinate to the dataflow's lockfile and
materializes a per-dataflow settings record. Nothing runs yet. The agent is
simply available in the palette.

**Attaching** it creates a private instance bound to a target:

| Target kind | Bound to | Reached by |
|---|---|---|
| `node` | One node on the canvas | Dragging a palette row onto that node. |
| `connection` | One edge between two nodes | Dragging a palette row onto that edge. |
| `canvas` | The whole dataflow | Dragging a palette row onto empty canvas. |

Not every agent accepts every target: an agent declares which kinds it is
compatible with, and its category implies a default. A `canvas` agent dropped on
a node is refused rather than silently rebound.

Each attachment carries its own chat transcript, its own **intent** (the editable
first instruction, defaulting to the definition's own prompt), and its own
optimistic `revision`. Attaching requires the agent to be added to the dataflow
first: attaching never auto-adds, in the same way that adding never auto-imports.

Where an agent proposes a change to your dataflow, it does not apply it. The
proposal surfaces as a **review card**, and applying it is a separate explicit
click that re-checks the target has not drifted since the proposal was minted.
Dismissing it leaves nothing behind. See
[AGENTS.md section 6](AGENTS.md#6-catalog--lifecycle-api) for the mechanics.

### Required agents

An agent may declare that it requires others. The drawer discloses this before
you click: the button reads **Add to dataflow (+2 required)** and its tooltip
names what else will be added. Adding pulls in the whole closure in one request.

The reverse is enforced too. Removing an agent that another added agent requires
is refused, with a message naming the dependent, so a dataflow cannot end up
holding a broken reference.

---

## 4. Importing, publishing, and sharing

**Import agent** takes a `manifest.json` and its `.txt` prompt files as JSON, not
an archive. The upload is strict on purpose: trust is forced to `imported`,
digests are stamped from the actual bytes rather than trusted from the manifest,
the prompt files must correspond exactly to what the manifest references, size
limits apply, and an existing coordinate returns `409` rather than overwriting.
Agent definitions are immutable; a change means a new version.

**Publish** copies an owned, imported, store-backed definition into the shared
catalog, where every user on the install can browse it. It rejects built-in and
absent definitions: you can only publish something you authored and imported.
**Unpublish** removes the listing and is owner-only. Neither touches any dataflow
that has already added the agent.

---

## 5. Settings and limits

Agents are the one catalog whose entries cost money to run, so they carry a
policy model the other two do not need. Three scopes nest, each able only to
**tighten** what the one above it allows:

| Scope | Edited from | Stored in | Covers |
|---|---|---|---|
| **Account** | **AI Settings** in the header, the **Agent limits** tab | `.curio/users/<key>/agents/settings.json` | Your default runs per day, daily budget, and max output tokens. |
| **Per-dataflow** | The settings cog on an **In dataflow** card | `spec.trill.json` then `dataflow.agentDefaults` | One added agent's limits within one dataflow. |
| **Per-attachment** | The attachment's own settings | `spec.trill.json` then `dataflow.agentAttachments` | One bound instance's limits. |

Above all three sits the **deployment ceiling**, which an operator sets and no
user scope can exceed. The effective value at any point is
`attachment ?? project ?? account ?? deployment`, clamped downward on read, so a
limit loosened upstream never silently widens a scope that tightened it.

The **provider**, meaning which model actually answers, is a separate question
with a single answer, and lives in the **Provider** tab of the same **AI
Settings** modal. It is account-level: every agent, on every dataflow, uses it.
That is why the two live in one modal rather than two.

Runs are admitted through an append-only per-day ledger under a file lock, so two
concurrent runs competing for the last slot serialize to exactly one admission.
A denied run consumes nothing and returns `429` with the limit it hit and when it
resets.

---

## Operator notes

### An unconfigured install has no provider

Curio ships with **no default LLM endpoint**. This is deliberate: an earlier
build defaulted to a specific university endpoint, which meant an unconfigured
instance silently sent user data to a third party. Today an unconfigured install
reaches a clear "no provider configured" error instead, and every agent surface
that is blocked for want of one links to **AI Settings**.

So an operator must configure a provider, or each user must configure their own
in AI Settings, before any agent will run. Guests are a separate case: they can
use AI only if the deployment ships a guest key, and AI Settings says so plainly
rather than offering fields that cannot take effect.

### Launcher flags

Agent configuration follows Curio's convention: an operator knob is a documented
`curio.py start` flag whose help names the variable it sets. Run
`python curio.py start --help` for the current list. The agent-facing ones are:

| Flag | Sets | Effect |
|---|---|---|
| `--llm-provider` | `CURIO_DEFAULT_LLM_API_TYPE` | The default provider kind. |
| `--llm-base-url` | `CURIO_DEFAULT_LLM_BASE_URL` | The default endpoint. |
| `--llm-model` | `CURIO_DEFAULT_LLM_MODEL` | The default model. |
| `--llm-api-key` | `CURIO_DEFAULT_LLM_API_KEY` | The default key. Prefer the variable: an argument is visible in the process list on a shared host. |
| `--guest-llm-api-key` | `GUEST_LLM_API_KEY` | The gate on guest AI. No key, no guest access. |
| `--agent-runs-per-day` | `CURIO_AGENT_RUNS_PER_DAY` | The deployment ceiling on runs. |
| `--agent-search-url` | `CURIO_SEARCH_URL` | The endpoint for agents with a search capability. |

A flag writes its variable only when passed, so a value already set in the
environment is not cleared by a start that omits it. That matters here more than
for a boolean knob: an empty `CURIO_DEFAULT_LLM_MODEL` means "no provider" and
would disable every AI surface.

`GUEST_LLM_API_TYPE`, `GUEST_LLM_BASE_URL`, and `GUEST_LLM_MODEL` stay
environment-only. Guests inherit the default provider and only the key gates
access; these exist as an escape hatch for the rare split-provider deployment.

### There is no publish gate for agents

As with datasets, agent publishing is authenticated but not gated by
configuration. The only restriction is the ownership check described in
[part 4](#4-importing-publishing-and-sharing): you may publish only definitions
you imported. On a multi-tenant deployment, any signed-in user can publish an
agent they authored into the shared catalog.

### The ledger needs no operational care

The per-day ledger files under `.curio/users/<key>/agents/ledger/` are the record
of what ran and what it cost. They are append-only and rotate by date. Deleting
an old day's file loses that day's usage history and nothing else; deleting the
current day's file resets today's quota, which is worth knowing but not something
to schedule.

---

## See also

- [`docs/AGENTS.md`](AGENTS.md): the agent runtime, meaning the manifest contract, capabilities, prompts, tools, and the chat and review loop.
- [`docs/NODE-CATALOG.md`](NODE-CATALOG.md): the node package catalog, whose storage and publish model this mirrors.
- [`docs/DATA-CATALOG.md`](DATA-CATALOG.md): the dataset catalog, the closest peer to this one.
- [`docs/ARCHITECTURE.md`](ARCHITECTURE.md#agent-routes): the agent HTTP API reference and backend module layout.
- [`utk_curio/backend/app/agents/`](../utk_curio/backend/app/agents/): the implementation.
