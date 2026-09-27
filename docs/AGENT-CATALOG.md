# Agent Catalog

The Agent Catalog is where Curio's **hookable agents** live: the assistants you attach to a node, a connection, or the whole canvas.

Curio has four catalogs: the [Node Catalog](NODE-CATALOG.md) holds the nodes you drop on the canvas, the [Data Catalog](DATA-CATALOG.md) the datasets they read, the Agent Catalog the assistants you attach to them, and the [Data Lake Catalog](DATA-LAKE-CATALOG.md) the open data portals you download datasets from.

This guide is in six parts, plus operator notes:

- [1. What is the Agent Catalog?](#1-what-is-the-agent-catalog): agents, what ships, and the storage layers.
- [2. Surfaces and workflows](#2-surfaces-and-workflows): the three places you manage agents, the action matrix, and walkthroughs.
- [3. Using an agent in a dataflow](#3-using-an-agent-in-a-dataflow): adding, attaching, and the difference between the two.
- [4. The provider](#4-the-provider): which model answers, and where it is set.
- [5. Importing, publishing, and sharing](#5-importing-publishing-and-sharing): your own definitions, and offering them to everyone.
- [6. The manifest](#6-the-manifest): writing your own agent.
- [Operator notes](#operator-notes): the provider requirement and launcher flags.

---

## 1. What is the Agent Catalog?

### Concept

An **agent** in Curio is a small self-contained folder, shaped like a node package, identified by an id and a version:

```
<agentId>@<version>     e.g.   agent.node-explainer@1.0.0
                               agent.dataflow-builder@1.0.0
```

The folder holds a `manifest.json` (the contract) and the prompt files the manifest references:

```
agent.node-explainer@1.0.0/
  manifest.json
  prompts/default_preamble.txt
  prompts/single_box_explanation_prompt.txt
```

Agent ids always begin with **`agent.`**, which keeps them apart from node package ids (`curio.builtin`, `ai.urbanlab.uhvi`) and dataset ids (`data.urbanlab.chicago-boundary`). The version is a full semver string.

### What ships with Curio

**Twenty-one agents ship with Curio.** Every agent declares one **category**, which the browse page's rail counts:

| Category | What the agent acts on |
|---|---|
| `node` | One node: its content, its errors, its output. |
| `canvas` | The whole dataflow: planning, explanation, suggestion. |
| `data` | Datasets and data shape. |
| `evaluate` | Review, validation, and scoring. |
| `package` | Node packages: recommending and resolving them. |

Each category has its own colour and glyph in the interface, so a card is identifiable at a glance.

### Storage layers

Agent state lives in files under `.curio/` and inside each project's spec. Knowing which layer an action writes is the key to predicting what happens after **Add to project**, **Add to all projects**, **Remove from project**, or attaching an agent:

| Layer | On disk | Written by |
|---|---|---|
| **Shared catalog**, published agents | `.curio/agents-catalog/<agentId>@<version>/` | **Publish** adds one; **Unpublish** removes it. |
| **Definition store**, the agents themselves | `.curio/users/<user-key>/agents/<agentId>@<version>/` (`manifest.json` and `prompts/`) | **Import agent** adds one; adding a built-in agent copies it here. |
| **Per-user list**, the agents in all your projects | `.curio/users/<user-key>/imported-agents.json` | **Add to all projects** and **Import agent** add an entry; **Remove from all projects** drops it. |
| **Per-dataflow lockfile**, the agents one dataflow has | `dataflow.agents` in the project's `spec.trill.json` | **Add to project** and **Remove from project** in the drawer. **Add to all projects** and **Remove from all projects** change every project. |
| **Attachments**, private instances bound to a target | `dataflow.agentAttachments` in the project's `spec.trill.json` | Attaching (dragging an agent onto a node, a connection, or the canvas) creates one. **Detach** deletes it and its transcript, and **Remove from project** deletes every attachment of that agent. |
| **Usage record** | `.curio/users/<user-key>/agents/ledger/<date>.jsonl` | Every run appends to it. It is not editable and not shown in the interface. |

> [!NOTE]
> **Adding is not attaching.** Adding an agent to a dataflow makes it available
> in that dataflow's palette. Attaching it creates a private instance bound to
> one node, one connection, or the canvas, with its own chat transcript. One
> added agent can carry many attachments. See
> [part 3](#3-using-an-agent-in-a-dataflow).

---

## 2. Surfaces and workflows

There are three places you work with agents, and as with the Data Catalog they are **not** interchangeable:

- **The `/catalog/agents` page** is the account-level library. Reach it from `/projects` and the **Agent Catalog** tab. It lists the built-in agents, every published one, and the ones you imported yourself. Filter by status (**All agents**, **In all projects**) and by category, search, and read an agent's full details. **Add to all projects**, **Publish** and **Unpublish** live here. You cannot add an agent to just one dataflow from this page: that is the drawer's job.
- **The Agent Catalog drawer**, inside the canvas, is the working surface. Open it from the top menu **Data ⏷ → Agent Catalog**, or from the left Tools panel's **Agent Catalog** dropdown and **Browse Agent Catalog +**. Its tabs are **Browse all** (the default) and **In project**, and everything scoped to the open dataflow happens here, including **Import agent** in its footer.
- **The Agent palette**, the **Agent Catalog** dropdown in the left Tools panel, holds the agents already added to this dataflow, ready to drag onto a node, a connection, or the canvas. It sits below the **Node Catalog** and **Data Catalog** dropdowns.

### Action matrix

| Action | Where | What it changes | What you see |
|---|---|---|---|
| **Add to project** | Drawer | This dataflow's lockfile, plus any agent it requires | The agent appears in this dataflow's **Agent Catalog** palette, ready to drag. |
| **Remove from project** | Drawer | This dataflow's lockfile and that agent's attachments | It leaves this dataflow's palette, and its attachments and their transcripts are deleted; the definition is **kept**. Refused while another added agent requires it. |
| **Add to all projects** | `/catalog/agents`, in the right-hand drawer or the right-click menu | Your per-user list and every project's lockfile | The agent is added to every dataflow you have, and new projects start with it. |
| **Remove from all projects** | `/catalog/agents`, in the right-hand drawer or the right-click menu | Your per-user list, every project's lockfile, and the agent's attachments | The agent and its attachments leave every dataflow. The definition stays on disk. |
| **Import agent** | Drawer footer | Definition store and your per-user list | Your own `manifest.json` and prompt files are registered as a definition. It is not added to your existing dataflows and not published. |
| **Publish** | `/catalog/agents` drawer, for your own imports only | Shared catalog | Every user on this install can browse the agent. |
| **Unpublish** | `/catalog/agents` drawer | Shared catalog | It leaves the shared catalog. Other users who added it can no longer use it. |
| **Attach** | Drag a palette row onto a node, a connection, or the canvas | Attachments | A private instance with its own chat panel. The agent must be added first. |
| **Detach** | The attachment's own control | Attachments | The instance and its transcript are deleted. The agent stays added. |

Nothing in this table deletes an agent definition from disk.

### Workflows

**I want to use an agent in my dataflow.** Open the dataflow, then **Data ⏷ → Agent Catalog**. Find the agent and click **Add to project**. It now appears in the left Tools panel's **Agent Catalog** dropdown. Drag it onto a node, a connection, or empty canvas to attach it, then click its badge (or its avatar in the dock) to open its chat panel.

**I want an agent in all my projects, present and future.** On `/catalog/agents`, click the agent's card and then **Add to all projects** in the drawer. It is added to every dataflow you have, and every project you create from then on starts with it.

**I want to browse without opening a dataflow.** Go to `/projects` and pick the **Agent Catalog** tab. Filter by status or category in the left rail, and click **View details** on a card to read everything about it.

**I want to write my own agent.** Author a `manifest.json` and its prompt files ([part 6](#6-the-manifest)), then use **Import agent** in the drawer's footer. It is listed on `/catalog/agents` beside the built-in and published agents, where **Publish** offers it to everyone on the install. Adding it to a dataflow and publishing it are separate actions.

---

## 3. Using an agent in a dataflow

**Adding** an agent makes it available in the dataflow's palette. Nothing runs yet.

**Attaching** it creates a private instance bound to a target:

| Target kind | Bound to | Reached by | Shown as |
|---|---|---|---|
| `node` | One node on the canvas | Dragging a palette row onto that node. | A badge under the node. |
| `connection` | One edge between two nodes | Dragging a palette row onto that edge. | A badge at the connection's midpoint, **and** an avatar in the dock. |
| `canvas` | The whole dataflow | Dragging a palette row onto empty canvas. | An avatar in the dock. |

While you drag a palette row across the canvas, the connection that would receive the drop is highlighted. A node under the pointer wins over any edge routed beneath it.

A connection agent is listed in **both** places. The badge says *which* connection the agent is about; the dock is the roster, always reachable. Detaching works from either.

Not every agent accepts every target: an agent declares which kinds it works with. A `canvas` agent dropped on a node is refused.

Each attachment has its own chat transcript and its own **intent**, the editable first instruction, which starts as the definition's own prompt. An agent must be added to the dataflow before you can attach it.

When an agent proposes a change to your dataflow, it does not apply it. The proposal appears as a **review card**, and applying it is a separate click, which first checks that the target has not changed since the proposal. Dismissing it leaves nothing behind.

### Required agents

An agent may require others. The drawer says so before you click: the button reads **Add to project (+2 required)**, and its tooltip names what else will be added. Adding brings in all of them at once.

The reverse holds too. Removing an agent that another added agent requires is refused, with a message naming the agent that needs it, so a dataflow never holds a broken reference.

### Finding data in portals

The **Dataset Finder** can search the portals in the [Data Lake Catalog](DATA-LAKE-CATALOG.md) as well as your own datasets, and propose downloading one. Nothing is downloaded until you apply the proposal. See [DATA-LAKE-CATALOG.md part 6](DATA-LAKE-CATALOG.md#6-the-dataset-finder).

---

## 4. The provider

Every agent, on every dataflow, is answered by one model. Which one is an account-level setting, edited in **AI Settings**: the button in the page header on `/projects` and the catalog pages, or in the Agent Catalog drawer's header on the canvas.

| Field | What it is |
|---|---|
| Provider | OpenAI, Anthropic, Gemini, or any OpenAI-compatible endpoint. |
| Base URL | Only for a custom endpoint: Ollama, LM Studio, vLLM, Groq, Azure. |
| API key | **One per account**, held against the provider you saved it under. The saved-key markers and **Remove saved key** appear only on that provider's tab; on any other tab the field is empty, and saving there replaces the stored key rather than adding a second one. Leave it blank to keep the saved key while you are on its own tab. |
| Model | Which model answers. **Fetch models** asks the endpoint what it serves and turns this field into a dropdown. Leave it blank to use the deployment's model. |
| HuggingFace token | Not for agents: it unlocks *gated* models in the Street Vision node. Public models need none. |
| Socrata app token | Not for agents: the Data Lake Catalog sends it to Socrata portals. See [DATA-LAKE-CATALOG.md part 5](DATA-LAKE-CATALOG.md#5-api-tokens). |

### Choosing the model

**Fetch models**, under the Model field, asks the endpoint on screen what it serves, using the base URL and key currently in the form, so you can choose a model for an endpoint you have not saved yet.

It is a convenience, not a gate. A model you saved earlier stays selected, marked *(not listed)* if the endpoint stops offering it, and the field takes free text until you press the button. The dropdown has two sources:

| Source | What it is |
|---|---|
| *From this endpoint* | What the endpoint reported just now. For Gemini, only models that support `generateContent` are offered. |
| *Last reported by this endpoint (on <date>)* | What it reported the last time it could be asked, shown when it cannot be asked now: no key pasted yet, offline, or a key without permission to list models. |

A model you type by hand is always accepted.

Whoever runs the install can set a default for provider, base URL and model with `curio.py start` flags (see [Operator notes](#operator-notes)).

**Curio does not meter, cap, or bill agent runs.** There is no quota screen and no spend limit: the tokens are billed to whoever's key is in use. Curio keeps a local, per-day record of what ran (see [Storage layers](#storage-layers)), and calls no usage or billing API.

---

## 5. Importing, publishing, and sharing

**Import agent**, in the drawer's footer, takes a `manifest.json` and its `.txt` prompt files, not an archive. The prompt files must match what the manifest references, size limits apply, and a definition whose id and version you already have is refused: a change is a new version.

**Publish**, on `/catalog/agents`, copies one of your own imported definitions into the shared catalog, where every user on the install can browse it. Built-in agents cannot be published. **Unpublish** removes it from the shared catalog, and only the publisher can do it. Other users who added the agent can no longer use it.

---

## 6. The manifest

An agent package is a folder named `<agentId>@<version>` holding a `manifest.json` and a `prompts/` directory. The manifest uses **camelCase** field names; [`docs/schemas/agent-package.v1.json`](schemas/agent-package.v1.json) (JSON Schema Draft 2020-12) is the full reference.

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
    "instruction": { "path": "prompts/single_box_explanation_prompt.txt", "sha256": "<sha256>", "variables": ["nodeContext"] }
  },
  "compatibleTargets": [{ "kind": "node" }],
  "inputs": { "reads": ["nodeContext"], "requiredConfig": [] },
  "outputs": ["explanation"],
  "runtime": { "execution": "foreground", "reviewPolicy": "report-only" },
  "provenance": { "publisher": "curio", "license": "MIT", "trust": "built-in" }
}
```

| Field | Required | What it declares |
|---|---|---|
| `id` | Yes | `agent.`-prefixed, kebab-case package id. Together with `version` it forms the folder name `<id>@<version>`. |
| `version` | Yes | Semver-style version string. |
| `name` | Yes | Human-readable name shown in the catalog. |
| `category` | Yes | One of `data`, `node`, `canvas`, `package`, `evaluate`. See [What ships with Curio](#what-ships-with-curio). |
| `capabilities` | Yes | Non-empty list of `{ id, contractVersion }`: the contracts this agent implements. |
| `provenance` | Yes | `{ publisher, license?, trust? }`; `trust` is one of `built-in`, `global`, `imported`. |
| `purpose`, `roles` | | One-line description and display roles. |
| `delegatesTo` | | Other `agent.` ids this agent may call. A preference only: it grants nothing and never adds or imports anything. |
| `requiresAgents` | | A subset of `delegatesTo`: the agents this one cannot work without. See [Required agents](#required-agents). |
| `prompts` | | Prompt files by package-relative `path`, `sha256`, and declared `variables`. Absolute paths and `..` are rejected. |
| `compatibleTargets` | | Where the agent can attach: `{ kind: node\|canvas\|connection, requires: [...] }`. For `node`, `requires` lists the node kinds it accepts, such as `data-loading`; empty means any node. |
| `inputs`, `outputs` | | The context the agent reads, the config it requires, and the named outputs it produces. |
| `runtime` | | `execution` (`foreground` or `background`) and `reviewPolicy` (`report-only` or `review-before-apply`). |
| `providerRequirements` | | Provider *capability* requirements such as `structured-output`. Credentials are never in a manifest. |
| `tools` | | Typed, allowlisted tool **requirements**, not a permission grant. |
| `settingsDefaults` | | Non-secret seed suggestions. |

### Capabilities

A **capability** is a contract, meaning *what* an agent does, separate from the prompt file that implements it. A capability id is two or more dot-separated lowercase segments:

```
node.explain            dataflow.orchestrate       package.recommend
node.output.interpret   dataset.fetch.author       connection.propose
```

Capability ids drive catalog discovery, orchestration and substitution, and are **never** used for authorization. A capability id must not contain a prompt filename, a path separator, an underscore, or `.txt`: `node.explain` is valid, while `single_box_explanation_prompt` and `prompts/explain.txt` are rejected. A prompt can then be edited or replaced without changing the contract.

Once written, import the package with the drawer's **Import agent** button ([part 5](#5-importing-publishing-and-sharing)).

---

## Operator notes

Curio ships with **no default LLM endpoint**. Until an operator configures a provider, or each user configures their own in **AI Settings**, agents stop with the error *"No AI provider is configured."*

| Variable | Flag | Effect |
|---|---|---|
| `CURIO_DEFAULT_LLM_API_TYPE` | `--llm-provider` | The default provider kind. |
| `CURIO_DEFAULT_LLM_BASE_URL` | `--llm-base-url` | The default endpoint. |
| `CURIO_DEFAULT_LLM_MODEL` | `--llm-model` | The default model. |
| `CURIO_DEFAULT_LLM_API_KEY` | none | The default API key. Set it in the environment. |
| `GUEST_LLM_API_KEY` | `--guest-llm-api-key` | The key guests use. Unset, guests use the default API key. |
| `GUEST_LLM_API_TYPE`, `GUEST_LLM_BASE_URL`, `GUEST_LLM_MODEL` | none | A separate provider for guests. Unset, guests use the default provider. |
| `CURIO_DEFAULT_HUGGINGFACE_TOKEN` | `--huggingface-token` | A fallback HuggingFace token for the Street Vision node's gated models. A user's own token wins. |
| `CURIO_SEARCH_URL` | `--agent-search-url` | Where the web-search tool looks, as a URL template with `{q}`. Defaults to DuckDuckGo's keyless Instant Answer API; point it at a local SearXNG, SerpAPI, or Google Programmable Search for ranked results. |

Run `python curio.py start --help` for the current list. A flag writes its variable only when passed, so a value already in the environment is not cleared by a start that omits it.

**Anyone signed in can publish.** Agent publishing has no on/off switch. The only restriction is ownership: you may publish only definitions you imported. On a multi-tenant deployment, any signed-in user can publish an agent they wrote into the shared catalog.

**The usage record needs no care.** The per-day files under `.curio/users/<key>/agents/ledger/` are append-only and rotate by date. Deleting a day's file loses that day's history and nothing else, and nothing expires the files automatically.

---

## See also

- [`docs/NODE-CATALOG.md`](NODE-CATALOG.md): the node package catalog, whose storage and publish model this one mirrors.
- [`docs/DATA-CATALOG.md`](DATA-CATALOG.md): the dataset catalog, the closest peer to this one.
- [`docs/DATA-LAKE-CATALOG.md`](DATA-LAKE-CATALOG.md): the data portals the Dataset Finder can search.
- [`docs/ARCHITECTURE.md`](ARCHITECTURE.md#agent-routes): the agent routes and backend layout.
- [`docs/schemas/agent-package.v1.json`](schemas/agent-package.v1.json): the manifest JSON Schema.
- [`utk_curio/backend/app/agents/`](../utk_curio/backend/app/agents/): the implementation.
