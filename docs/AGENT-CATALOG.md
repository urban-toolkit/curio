# Agent Catalog

The Agent Catalog is where Curio's **hookable agents** live. It is the third of
three catalogs, alongside the [Node Catalog](NODE-CATALOG.md) and the
[Data Catalog](DATA-CATALOG.md). Where the Node Catalog manages the *nodes* you
drop on the canvas and the Data Catalog manages the *data* those nodes read, the
Agent Catalog manages the *assistants* you attach to them.

This guide covers what an agent is, where its state lives, the three surfaces
you manage agents from, which layer each action writes, and how to write one of
your own.

This guide is in six parts, plus operator notes:

- [1. What is the Agent Catalog?](#1-what-is-the-agent-catalog): the storage layers, agent ids, and what ships built in.
- [2. Surfaces and workflows](#2-surfaces-and-workflows): the three places you manage agents, the action matrix, and walkthroughs.
- [3. Using an agent in a dataflow](#3-using-an-agent-in-a-dataflow): adding, attaching, and the difference between the two.
- [4. Importing, publishing, and sharing](#4-importing-publishing-and-sharing): authoring your own definitions.
- [5. The provider](#5-the-provider): which model answers, and where it is set.
- [6. Writing your own agent](#6-writing-your-own-agent): the manifest contract and capabilities.
- [Operator notes](#operator-notes): the provider requirement and launcher flags.

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
[part 6](#6-writing-your-own-agent) for the field table.

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
| **Attachments**, a private agent instance bound to a target | `spec.trill.json` then `dataflow.agentAttachments` | **Attach** (dragging an agent onto a node or the canvas) creates one; **Detach** deletes it and its transcript. |
| **Usage ledger** | `.curio/users/<user-key>/agents/ledger/<date>.jsonl` | Every run appends a reserve and settle pair. Append-only, not user-editable, and not surfaced in the interface. |

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
([part 6](#6-writing-your-own-agent)), then use the drawer's
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
[ARCHITECTURE.md](ARCHITECTURE.md#agent-routes) for the endpoints behind this.

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

## 5. The provider

Every agent, on every dataflow, is answered by one model. Which one is an
account-level setting, edited in **AI Settings** from the header.

| Field | What it is |
|---|---|
| Provider | OpenAI, Anthropic, Gemini, or any OpenAI-compatible endpoint. |
| Base URL | Only for a custom endpoint: Ollama, LM Studio, vLLM, Groq, Azure. |
| API key | Stored per account. Leave blank to keep the saved one. |
| Model | The model name. Leave blank to inherit the deployment's. |
| HuggingFace token | Not for agents: it unlocks *gated* models in the Street Vision node. It sits here because it is the same kind of setting, a model credential you hold per account. Public models need none. |

Whoever runs the Curio install can set a default for all four with
`curio.py start` flags (see [Operator notes](#operator-notes)). Those flags and
this panel write the same account-wide setting, so AI Settings shows the
deployment's choice as the inherited value and you override it only by typing
something else. Leave a field blank and you stay on the deployment default,
including when the operator later changes it.

**Curio does not meter, cap, or bill agent runs.** There is no quota screen, no
spend limit, and no way to configure either: the tokens are billed to whoever's
key is in use, so the ceiling is theirs to impose rather than Curio's to assume.
No run is ever refused for usage.

The one adjacent setting that survives is **max output tokens**, and it is not a
quota: it is passed to the provider as `max_tokens` on every completion, so it
shapes one reply rather than rationing a day's worth. It resolves
`attachment ?? project ?? account ?? deployment`, clamped downward on read, and
is editable through the agent settings API rather than the interface.

Curio does keep a local record of what ran, in an append-only per-day file under
`.curio/users/<key>/agents/ledger/`. It is written from the token counts each
provider already returns on the completion itself: no usage or billing API is
ever called, and no USD figure is computed, because Curio has no price table and
would have to invent the numbers.

---

## 6. Writing your own agent

An agent package is a directory named `<agentId>@<version>` holding a
`manifest.json` and a `prompts/` directory. The manifest uses **camelCase**
field names and is validated against
[`docs/schemas/agent-package.v1.json`](schemas/agent-package.v1.json) (JSON
Schema Draft 2020-12), which is the source of truth for what a manifest may
declare. The backend validator in
[`app/agents/manifest.py`](../utk_curio/backend/app/agents/manifest.py)
implements the supported subset.

A minimal, complete manifest:

```json
{
  "$schema": "../../docs/schemas/agent-package.v1.json",
  "id": "agent.node-explainer",
  "name": "Node Explainer",
  "category": "node",
  "version": "1.0.0",
  "purpose": "Explain what a node or its output does.",
  "roles": ["explanation"],
  "capabilities": [
    { "id": "node.explain", "contractVersion": "1" },
    { "id": "node.output.interpret", "contractVersion": "1" }
  ],
  "prompts": {
    "system": { "path": "prompts/default_preamble.txt", "sha256": "<sha256>", "variables": [] },
    "instruction": { "path": "prompts/single_box_explanation.txt", "sha256": "<sha256>", "variables": ["nodeContext"] }
  },
  "compatibleTargets": [{ "kind": "node", "requires": ["code-or-output"] }],
  "inputs": { "reads": ["nodeContext"], "requiredConfig": [] },
  "outputs": ["explanation"],
  "runtime": { "execution": "foreground", "reviewPolicy": "report-only" },
  "provenance": { "publisher": "curio", "license": "MIT", "trust": "built-in" }
}
```

| Field | Required | What it declares |
|---|---|---|
| `id` | Yes | `agent.`-prefixed, kebab-case package id. Pairs with `version` to form the directory `<id>@<version>`. |
| `version` | Yes | Semver-style version string. |
| `name` | Yes | Human-readable name shown in the catalog. |
| `category` | Yes | One of `data`, `node`, `canvas`, `package`, `evaluate`. See [Categories](#categories). |
| `capabilities` | Yes | Non-empty list of `{ id, contractVersion }`: the semantic contracts this agent implements. |
| `provenance` | Yes | `{ publisher, license?, trust? }`; `trust` is one of `built-in`, `global`, `imported`. |
| `purpose`, `roles` | | One-line description and display roles. |
| `delegatesTo` | | Other `agent.` ids this agent may call. A preferred implementation only: it grants nothing and never adds or imports anything. |
| `requiresAgents` | | A subset of `delegatesTo`: the agents this one is not functional without. See [Required agents](#required-agents). |
| `prompts` | | Prompt assets by package-relative `path` + `sha256` + declared `variables`. Absolute paths and `..` escapes are rejected. |
| `compatibleTargets` | | Where the agent can attach: `{ kind: node\|canvas\|connection, requires: [...] }`. |
| `inputs`, `outputs` | | Context the agent reads, config it requires, and the named outputs it produces. |
| `runtime` | | `execution` (`foreground` or `background`) and `reviewPolicy` (`report-only` or `review-before-apply`). |
| `providerRequirements` | | Provider *capability* requirements such as `structured-output`. Credentials are never in a manifest. |
| `tools` | | Typed, allowlisted tool **requirements**. Never executable code, and never a permission grant. |
| `settingsDefaults` | | Non-secret seed suggestions. A manifest cannot create a new trusted profile family implicitly. |

The directory name is authoritative: the loader cross-checks it against the
manifest's `id` and `version` and rejects a mismatch, exactly as the
node-package loader does.

### Capabilities

A **capability** is a semantic contract, meaning *what* an agent does, kept
deliberately separate from the prompt file that implements it. A capability id
is two or more dot-separated lowercase segments:

```
node.explain            dataflow.orchestrate       package.recommend
node.output.interpret   dataset.fetch.author       connection.propose
```

Capability ids drive catalog discovery, orchestration and substitution, and are
**never** used for authorization. Because they are contracts rather than assets,
a capability id must not contain a prompt filename, a path separator, an
underscore, or `.txt`: `node.explain` is valid, `single_box_explanation_prompt`
and `prompts/explain.txt` are rejected. A prompt can then be edited or replaced
without changing the contract.

Once written, import the package through the drawer's **Import agent** button
([part 4](#4-importing-publishing-and-sharing)).

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
| `--guest-llm-api-key` | `GUEST_LLM_API_KEY` | The gate on guest AI. No key, no guest access. |
| `--huggingface-token` | `CURIO_DEFAULT_HUGGINGFACE_TOKEN` | Fallback HuggingFace token for the Street Vision node's gated models. Each user can set their own in AI Settings, which wins over this. Not an agent setting, but it lives in the same panel. |
| `--agent-search-url` | `CURIO_SEARCH_URL` | Where the web-search tool looks, as a URL template with `{q}`. Defaults to DuckDuckGo's keyless Instant Answer API. Point it at a local SearXNG, SerpAPI, or Google Programmable Search for ranked web results. |

A flag writes its variable only when passed, so a value already set in the
environment is not cleared by a start that omits it. That matters here more than
for a boolean knob: an empty `CURIO_DEFAULT_LLM_MODEL` means "no provider" and
would disable every AI surface.

### Variables with no flag, on purpose

| Variable | Why there is no flag |
|---|---|
| `CURIO_DEFAULT_LLM_API_KEY` (or `AICONN_API_KEY`) | A key passed as an argument is visible in the process list to every user on the host. Set it in the environment. |
| `GUEST_LLM_API_TYPE`, `GUEST_LLM_BASE_URL`, `GUEST_LLM_MODEL` | Guests inherit the default provider and only the key gates access. These are an escape hatch for the rare split-provider deployment. |

The package-build variables (`CURIO_BUILD_*`, `CURIO_JS_*`,
`CURIO_BACKEND_SANDBOX_PYTHON`) belong to the package-build subsystem rather
than to this catalog, and have no launcher flags either.

### There is no publish gate for agents

As with datasets, agent publishing is authenticated but not gated by
configuration. The only restriction is the ownership check described in
[part 4](#4-importing-publishing-and-sharing): you may publish only definitions
you imported. On a multi-tenant deployment, any signed-in user can publish an
agent they authored into the shared catalog.

### The usage ledger needs no operational care

The per-day files under `.curio/users/<key>/agents/ledger/` record what ran.
They are append-only, rotate by date, and are written from token counts the
provider already returned on each completion, so nothing polls anything. They
are not surfaced in the interface.

Deleting a day's file loses that day's history and nothing else: no limit is
computed from it, so nothing changes for the user. Nothing expires the files
automatically and there is no cleanup job to schedule.

---

## See also

- [`docs/NODE-CATALOG.md`](NODE-CATALOG.md): the node package catalog, whose storage and publish model this mirrors.
- [`docs/DATA-CATALOG.md`](DATA-CATALOG.md): the dataset catalog, the closest peer to this one.
- [`docs/ARCHITECTURE.md`](ARCHITECTURE.md#agent-routes): the agent HTTP API reference and backend module layout.
- [`utk_curio/backend/app/agents/`](../utk_curio/backend/app/agents/): the implementation.
