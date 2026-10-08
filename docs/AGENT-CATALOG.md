# Agent Catalog

The Agent Catalog is where Curio's **hookable agents** live: the assistants you attach to a node, a connection, or the whole canvas.

Curio has six catalogs: the [Node Catalog](NODE-CATALOG.md) holds the nodes you drop on the canvas, the [Data Catalog](DATA-CATALOG.md) the datasets they read, the [Model Catalog](MODEL-CATALOG.md) the models they run, the Agent Catalog the assistants you attach to them, the [Discovery Catalog](DISCOVERY-CATALOG.md) the portals, storage, services and models you take datasets and models from, and the [Scenario Catalog](SCENARIO-CATALOG.md) the scenarios saved in your projects.

This guide is in six parts, plus operator notes:

- [1. What is the Agent Catalog?](#1-what-is-the-agent-catalog): agents, what ships, and the storage layers.
- [2. Surfaces and workflows](#2-surfaces-and-workflows): the three places you manage agents, the action matrix, walkthroughs, and catalog settings.
- [3. Using an agent in a dataflow](#3-using-an-agent-in-a-dataflow): adding, attaching, and the difference between the two.
- [4. LLM configurations](#4-llm-configurations): which model answers, and where it is set.
- [5. Importing, publishing, and sharing](#5-importing-publishing-and-sharing): your own definitions, and offering them to everyone.
- [6. The manifest](#6-the-manifest): writing your own agent.
- [Operator notes](#operator-notes): the Deployment default and launcher flags.

---

## 1. What is the Agent Catalog?

### Concept

An **agent** in Curio is a small self-contained folder, shaped like a node package, identified by an id and a version:

```
<agentId>@<version>     e.g.   agent.chat-agent@1.0.0
                               agent.dataflow-builder@1.0.0
```

The folder holds a `manifest.json` (the contract) and the prompt files the manifest references:

```
agent.chat-agent@1.0.0/
  manifest.json
  prompts/chat_prompt.md
```

Agent ids always begin with **`agent.`**, which keeps them apart from node package ids (`curio.builtin`, `ai.utk.uhvi`) and dataset ids (`data.utk.chicago-boundary`). The version is a full semver string.

### What ships with Curio

**Thirteen agents ship with Curio.** Ten of them are the catalog: **Chat**, **Dataflow Builder**, **Dataset Finder**, **Node Builder**, **Node Content Builder**, **Node Researcher**, **Package Builder**, **Package Recommendation**, **Researcher** and **Connection Builder**. Chat is the one agent for conversation: it explains a node or the whole dataflow, diagnoses errors, and helps you define what to build.

The other three work only on behalf of those ten: the **Dataflow Planner** plans, refreshes and checks a dataflow's tasks and extracts and binds the keywords that describe it, the **Dataflow Reader** explains a whole dataflow and suggests its next steps, and the **Generated Content Evaluator** checks generated node content against its goal. They are never listed, added or attached, and a catalog agent can delegate to one without it being added to the dataflow.

Every agent declares one **category**, which the browse page's rail counts:

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
| **Definition store**, the agents themselves | `.curio/users/<user-key>/agents/<agentId>@<version>/` (`manifest.json` and `prompts/`) | **Import agent** adds one; adding a built-in or published agent copies it here. |
| **Per-user list**, the agents in all your projects | `.curio/users/<user-key>/imported-agents.json` | **Add to all projects** and **Import agent** add an entry; **Remove from all projects** drops it. |
| **Catalog settings**, values you own | `.curio/users/<user-key>/catalog-settings.json` | **Settings** on `/catalog/agents` saves a setting you changed; **Restore default** removes it. See [Catalog settings](#catalog-settings). |
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

- **The `/catalog/agents` page** is the account-level library. Reach it from `/projects` and the **Agent Catalog** tab. It lists the built-in agents, every published one, and the ones you imported yourself. Filter by status (**All agents**, **In all projects**) and by category, search, and read an agent's full details. **Add to all projects**, **Publish**, **Unpublish**, **Settings** and **Import agent** live here. You cannot add an agent to just one dataflow from this page: that is the drawer's job.
- **The Agent Catalog drawer**, inside the canvas, is the working surface. Open it from the **Agent Catalog** button in the top bar, or from the left Tools panel's **Agent Catalog** dropdown and **Browse Agent Catalog +**. Its tabs are **Browse all** (the default) and **In project**, and everything scoped to the open dataflow happens here, including **Import agent** in its footer.
- **The Agent palette**, the **Agent Catalog** dropdown in the left Tools panel, holds the agents already added to this dataflow, ready to drag onto a node, a connection, or the canvas. It sits below the **Node Catalog** and **Data Catalog** dropdowns.

### Action matrix

| Action | Where | What it changes | What you see |
|---|---|---|---|
| **Add to project** | Drawer | This dataflow's lockfile, plus any agent it requires | The agent appears in this dataflow's **Agent Catalog** palette, ready to drag. |
| **Remove from project** | Drawer | This dataflow's lockfile and that agent's attachments | It leaves this dataflow's palette, and its attachments and their transcripts are deleted; the definition is **kept**. Refused while another added agent requires it. |
| **Add to all projects** | `/catalog/agents`, in the right-hand drawer or the right-click menu | Your per-user list and every project's lockfile | The agent is added to every dataflow you have, and new projects start with it. |
| **Remove from all projects** | `/catalog/agents`, in the right-hand drawer or the right-click menu | Your per-user list, every project's lockfile, and the agent's attachments | The agent and its attachments leave every dataflow. The definition stays on disk. |
| **Import agent** | Drawer footer, or the `/catalog/agents` header | Definition store and your per-user list | Your own `manifest.json` and prompt files are registered as a definition. It is not added to your existing dataflows and not published. |
| **Publish** | `/catalog/agents` drawer, for your own imports only | Shared catalog | Every user on this install can browse the agent. |
| **Unpublish** | `/catalog/agents` drawer | Shared catalog | It leaves the shared catalog. Other users who added it keep their copy. |
| **Attach** | Drag a palette row onto a node, a connection, or the canvas | Attachments | A private instance with its own chat panel. The agent must be added first. |
| **Detach** | The attachment's own control | Attachments | The instance and its transcript are deleted. The agent stays added. |

Nothing in this table deletes an agent definition from disk.

### Workflows

**I want to use an agent in my dataflow.** Open the dataflow, then click **Agent Catalog** in the top bar. Find the agent and click **Add to project**. It now appears in the left Tools panel's **Agent Catalog** dropdown. Drag it onto a node, a connection, or empty canvas to attach it, then click its badge (or its avatar in the dock) to open its chat panel.

**I want an agent in all my projects, present and future.** On `/catalog/agents`, click the agent's card and then **Add to all projects** in the drawer. It is added to every dataflow you have, and every project you create from then on starts with it.

**I want to browse without opening a dataflow.** Go to `/projects` and pick the **Agent Catalog** tab. Filter by status or category in the left rail, and click **View details** on a card to read everything about it.

**I want to write my own agent.** Author a `manifest.json` and its prompt files ([part 6](#6-the-manifest)), then use **Import agent** in the drawer's footer. It is listed on `/catalog/agents` beside the built-in and published agents, where **Publish** offers it to everyone on the install. Adding it to a dataflow and publishing it are separate actions.

### Catalog settings

Some values agents work with are yours to decide. They are **catalog settings**: open **Settings** on the `/catalog/agents` page to edit them. They belong to your account, so one edit applies in every project.

| Setting | What it holds | Read by |
|---|---|---|
| **Keyword types** | The types a keyword in a dataflow's description can take, each with a description and examples. | The Dataflow Planner, when it extracts the keywords of a description, binds them to nodes and edges, and refreshes a dataflow's task. |

Each setting lists the agents that read it. **Restore default** returns a setting to the value Curio ships, and only settings you changed are stored. A guest on a hosted instance can read the settings but not change them.

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

Chat reads the dataflow as it is on screen with every message, unsaved edits included, and when it is attached to a node, that node's content, what feeds it and its last run.

Each attachment has its own chat transcript and its own **intent**, the editable first instruction, which starts as the definition's own prompt. An agent must be added to the dataflow before you can attach it.

When an agent proposes a change to your dataflow, it does not apply it. The proposal appears as a **review card**, and applying it is a separate click, which first checks that the target has not changed since the proposal. Dismissing it leaves nothing behind.

### Required agents

An agent may require others. The drawer says so before you click: the button reads **Add to project (+2 required)**, and its tooltip names what else will be added. Adding brings in all of them at once.

The reverse holds too. Removing an agent that another added agent requires is refused, with a message naming the agent that needs it, so a dataflow never holds a broken reference.

### Solve

The **Dataflow Builder** plans a whole dataflow. Once you apply its plan, **Solve** in its strip fills in the planned nodes in one batch, and **Solve this node**, in the chat of an agent attached to a node, does the same for one node.

Solve runs what it writes. A node with code is generated, run in the sandbox, corrected when the run fails, and written only once a run passes. The nodes run in waves, the loaders first and then what depends on them, and the strip shows which wave is running (*wave 2 of 3*). A chart or map document is checked against its grammar's schema and reported as validated, not executed. A node with nothing to write, such as a Data Pool or a Spatial Join, is left wired as it is.

When Solve cannot fix a node, nothing is written, and the chat shows every attempt as its own row: the exception, where it was raised, and the code that attempt ran. The message names what stopped the loop, normally the time budget: the Solve's 15 minutes, or the node's own 15 minutes when you use **Solve this node**. A Solve keeps working for up to 15 minutes, and runs on if you close the chat or reload the page. **Stop** ends it after the current node, and what was written stays. What it did not reach stays *pending* with the reason, and **Solve** continues from there; after a failure or a server restart, the same button reads **Retry**.

Applying a plan gives every created node a **Node Builder**, and every data-loading node a **Dataset Finder** too. When a data-loading node's source is not settled, Solve asks that Dataset Finder for candidates: they appear in its chat, and the node stays pending, *awaiting your dataset selection*, with an **Open Dataset Finder** button. **Confirm source for this node** records your choice, and the next Solve builds the loader from that source.

A node with several inputs reads each through its input chip, `[!! input_0 !!]`, `[!! input_1 !!]` and so on, in the order of its input circles (see [Several inputs](USAGE.md#several-inputs)), and the agent is told which dataset sits on each circle. Code that treats the inputs as one value is refused before it runs.

### Widgets and scenarios

A planned node can declare widgets: values you set in its **Widgets** tab, which its code reads through references such as `[!! threshold !!]` (see [Widgets](USAGE.md#widgets)). The review card lists each node's widgets, and Solve writes code that places them and is told their current values. A value several nodes read is a **Parameter** node with one widget. A node the **Node Builder** proposes can declare widgets too. A widget a plan or a proposal declares is checked as the **Widgets** tab checks one you add.

A plan can also save [scenarios](USAGE.md#scenarios). A scenario in a plan is either a named selection of its nodes, or a duplicate of one: its nodes are copied with the connections between them and every connection entering them, as **Duplicate as scenario** copies them on the canvas, and the copies can be given other widget values. The review card names each scenario with its nodes, and for a duplicate the scenario it copies and the values it changes; each copy is listed as a node with its scenario beside its title.

Applying the whole plan saves its scenarios. Applied node by node, a copy can be created only after the node it copies, and a scenario is saved with the last of its nodes. A scenario that would take a node another scenario holds is not saved, since a node belongs to one scenario. A duplicate copies nodes the plan adds; scenarios already on the canvas are duplicated there. Solve writes a copy's code as it writes any planned node's, so the two can differ; compare them before relying on the comparison.

An agent that reads the dataflow sees each scenario with its fixed context, levers and outcomes, and each node's widget values.

### Finding data in portals

The **Dataset Finder** can search the portals in the [Discovery Catalog](DISCOVERY-CATALOG.md) as well as your own datasets, and propose downloading one. Nothing is downloaded until you apply the proposal. See [DISCOVERY-CATALOG.md part 6](DISCOVERY-CATALOG.md#6-the-dataset-finder).

---

## 4. LLM configurations

Every agent, on every dataflow, answers with an **LLM configuration**: the one chosen for it in **API Settings**, else your default. Configurations belong to your account. **API Settings** is in the top bar: on `/projects` and the catalog pages it opens the settings page; on the canvas and the dashboard it opens on the right side, and the dataflow stays open. The **API Settings** button in the Agent Catalog drawer's header opens it on the **Agent configuration** tab. Configurations are the rows of kind **Language model** on the **API keys** tab. A configuration is:

| Field | What it is |
|---|---|
| Label | Your name for it, unique in your account. |
| Provider | OpenAI, Anthropic, Gemini, Custom (any OpenAI-compatible endpoint), or **This Curio install** when the operator offers its endpoint. |
| Base URL | Only for Custom: Ollama, LM Studio, vLLM, Groq, Azure. |
| API key | Write-only, and held for this configuration's endpoint only. Editing leaves it in place unless you type a new one or remove it; changing the provider, or the base URL's scheme, host or port, needs it again. This Curio install uses the operator's key, which you never see. |
| Model | Which model answers. **Fetch models** suggests what the endpoint serves. |

To add a configuration:

1. Get an API key from the provider (see [USAGE.md](USAGE.md#your-configurations) for each provider's link).
2. Open **API Settings** from the top bar (on the canvas it opens on the right).
3. On the **API keys** tab, click **Add configuration**.
4. In **Kind**, choose **Language model**.
5. Type a **Label**, choose the **Provider**, paste the **API key**, and type the **Model**, or click **Fetch models** and pick one. **Custom** also asks for the **Base URL**.
6. Click **Add configuration**. The configuration's row shows in the list, with **saved** in its **Key** column when you gave a key.

**Make this my default** is ticked for your first configuration. Each row offers **Edit**, **Duplicate** (the copy keeps the key) and **Remove**; an account holds up to 32. Its **Details** show the provider, the model and the host, and **Chosen for** lists the agents chosen to run on it. The **Default** badge marks your default. The **Deployment default** row is the operator's own configuration: read-only, with **set by this Curio** in its **Key** column, shown when the operator configured one, and the one that answers while you have no default of your own. Choosing it in **Default for agents**, or removing your own default, goes back to it.

### Default and Agent models

The **Agent configuration** tab chooses which configuration answers. Its **Default** section names what answers your agents (**Answering now:** a label and a model) and sets your default in **Default for agents**: the Deployment default or any of your configurations. Below it, **Agent models** lists the ten catalog agents plus your imported and published agents, each with a select: **Default** (your default configuration), any of your configurations, or the Deployment default. A change is saved at once. Which configuration answers a run:

| Run | Configuration |
|---|---|
| An agent you attach (chat, Solve, Simulation, the per-node Solve) | Its choice, else your default, else the Deployment default |
| An agent another agent calls | Its choice, else its caller's |
| An internal helper (the Dataflow Planner, the Dataflow Reader, the content evaluator) | Always its caller's |
| A guest on a `--deploy` instance | The guest configuration, for every agent |

A choice that names nothing, such as a removed configuration or a Deployment default the operator withdrew, refuses the run with **Open API Settings**, which opens the **Agent configuration** tab on that agent's row; it never falls back to another configuration. Removing a configuration sends the agents chosen for it back to the default, and its confirmation names them.

A Solve of the Dataflow Builder runs on the Builder's configuration, and writes each node's content through Node Content Builder and each source through Dataset Finder, each on its own choice. The choices a Solve needs are checked before it starts, and one that names nothing refuses it. After a dataset selection, the node is built on its builder's configuration, not the Dataset Finder's.

The choice is per account, for every version of the agent and every project. A shared project carries none, so it runs on the configurations of whoever runs it. An agent's details show what it runs on, with **Change in API Settings**, which opens the **Agent configuration** tab on its row; a reply's status line says, on hover, which configuration and model answered it; and a delegated task in the chat names what the delegate ran on.

An agent's tools (reading the dataflow, searching the Data Catalog or the Model Catalog, reading a shipped example dataflow, proposing a node or a plan, handing a task to another agent) work the same on every configuration, and every change waits for your review. For a Custom endpoint, Curio asks once per model whether it calls tools, the first time an agent with tools runs on it: one short request, billed like any other and kept in the usage record.

### Choosing the model

**Fetch models**, under the Model field, asks the endpoint on screen what it serves, using the provider, base URL and key currently in the form, so you can choose a model for an endpoint you have not saved yet. While you edit a saved configuration, a blank key box asks with its saved key, as long as the endpoint on screen is still the configuration's own. What comes back is offered as suggestions in the Model box.

It is a convenience, not a gate: the field stays free text. Two sources fill the suggestions:

| Source | What it is |
|---|---|
| *From this endpoint* | What the endpoint reported just now. For Gemini, only models that support `generateContent` are offered. |
| *Last reported by this endpoint (on <date>)* | What it reported the last time it could be asked, shown when it cannot be asked now: no key pasted yet, offline, or a key without permission to list models. |

A model you type by hand is always accepted.

Whoever runs the install can set a Deployment default with `curio.py start` flags (see [Operator notes](#operator-notes)). It is not stored in your account, so when the operator changes it, the Deployment default row changes with it.

**Curio does not meter, cap, or bill agent runs.** There is no quota screen and no spend limit: the tokens are billed to whoever's key is in use. Curio keeps a local, per-day record of what ran (see [Storage layers](#storage-layers)), and calls no usage or billing API.

---

## 5. Importing, publishing, and sharing

**Import agent**, in the drawer's footer or the `/catalog/agents` header, takes a `manifest.json` and its `.md` or `.txt` prompt files, not an archive. The prompt files must match what the manifest references, size limits apply, and a definition whose id and version you already have is refused: a change is a new version.

**Publish**, on `/catalog/agents`, copies one of your own imported definitions into the shared catalog, where every user on the install can browse it. Built-in agents cannot be published. **Unpublish** removes it from the shared catalog, and only the publisher can do it; only the publisher can publish over it, too. Other users who added the agent keep their copy and keep running it.

---

## 6. The manifest

An agent package is a folder named `<agentId>@<version>` holding a `manifest.json` and a `prompts/` directory. The manifest uses **camelCase** field names; [`docs/schemas/agent-package.v1.json`](schemas/agent-package.v1.json) (JSON Schema Draft 2020-12) is the full reference.

A minimal, complete manifest:

```json
{
  "$schema": "../../docs/schemas/agent-package.v1.json",
  "id": "agent.my-helper",
  "name": "My Helper",
  "category": "node",
  "version": "1.0.0",
  "purpose": "Explain what a node or its output does.",
  "roles": ["explanation"],
  "capabilities": [
    { "id": "node.explain", "contractVersion": "1" },
    { "id": "node.output.interpret", "contractVersion": "1" }
  ],
  "prompts": {
    "system": { "path": "prompts/default_preamble.md", "sha256": "<sha256>", "variables": [] },
    "instruction": { "path": "prompts/explain_node.md", "sha256": "<sha256>", "variables": ["nodeContext"] }
  },
  "compatibleTargets": [{ "kind": "node" }],
  "inputs": { "reads": ["nodeContext"], "requiredConfig": [] },
  "outputs": ["explanation"],
  "runtime": { "execution": "foreground", "reviewPolicy": "report-only" },
  "provenance": { "publisher": "you", "license": "MIT", "trust": "imported" }
}
```

| Field | Required | What it declares |
|---|---|---|
| `id` | Yes | `agent.`-prefixed, kebab-case package id. Together with `version` it forms the folder name `<id>@<version>`. |
| `version` | Yes | Semver-style version string. |
| `name` | Yes | Human-readable name shown in the catalog. |
| `category` | Yes | One of `data`, `node`, `canvas`, `package`, `evaluate`. See [What ships with Curio](#what-ships-with-curio). |
| `capabilities` | Yes | Non-empty list of `{ id, contractVersion }`: the contracts this agent implements. A capability that also names an `instruction` is a mode; see [Modes](#modes). |
| `provenance` | Yes | `{ publisher, license?, trust? }`; `trust` is one of `built-in`, `global`, `imported`. |
| `purpose`, `roles` | | One-line description and display roles. |
| `delegatesTo` | | Other `agent.` ids this agent may call, in preference order. An entry `{ "id", "capabilities": [...] }` delegates only those capabilities of that agent. A preference only: it grants nothing and never adds or imports anything. |
| `requiresAgents` | | A subset of `delegatesTo`: the agents this one cannot work without. See [Required agents](#required-agents). |
| `prompts` | | Prompt files by package-relative `path`, `sha256`, and declared `variables`. Absolute paths and `..` are rejected. |
| `compatibleTargets` | | Where the agent can attach: `{ kind: node\|canvas\|connection, requires: [...] }`. For `node`, `requires` lists the node kinds it accepts, such as `data-loading`; empty means any node. |
| `inputs`, `outputs` | | The context the agent reads (`inputs.reads`), the [catalog settings](#catalog-settings) every run of it receives (`inputs.requiredConfig`), and the named outputs it produces. |
| `runtime` | | `execution` (`foreground` or `background`) and `reviewPolicy` (`report-only` or `review-before-apply`). |
| `providerRequirements` | | Provider *capability* requirements such as `structured-output`, as a preference: an agent runs on the configuration chosen for it whatever these say. Credentials and configurations are never in a manifest. |
| `tools` | | Typed, allowlisted tool **requirements**, not a permission grant. |
| `settingsDefaults` | | Non-secret seed suggestions. |

### Capabilities

A **capability** is a contract, meaning *what* an agent does, separate from the prompt file that implements it. A capability id is two or more dot-separated lowercase segments:

```
node.explain            dataflow.orchestrate       package.recommend
node.output.interpret   dataset.fetch.author       connection.propose
```

Capability ids drive catalog discovery, orchestration and substitution, and are **never** used for authorization. A capability id must not contain a prompt filename, a path separator, an underscore, `.txt` or `.md`: `node.explain` is valid, while `explain_node_prompt` and `prompts/explain.txt` are rejected. A prompt can then be edited or replaced without changing the contract.

### Modes

A capability can run an instruction of its own. Add the prompt under `prompts` and name its key as the capability's `instruction`:

```json
"capabilities": [
  { "id": "node.explain", "contractVersion": "1" },
  { "id": "node.output.interpret", "contractVersion": "1",
    "instruction": "interpret", "reads": ["nodeContext"], "requiredConfig": ["keywordTypes"] }
],
"prompts": {
  "system": { "path": "prompts/default_preamble.md" },
  "instruction": { "path": "prompts/explain_node.md" },
  "interpret": { "path": "prompts/interpret_output.md" }
}
```

When another agent delegates `node.output.interpret`, the run uses `prompts/interpret_output.md` in place of the `instruction` prompt, and receives the [catalog settings](#catalog-settings) named in that capability's `requiredConfig` as well as those in `inputs.requiredConfig`. An attached run, and a delegated run of a capability without an `instruction` of its own, uses the `instruction` prompt. A setting key Curio does not define is skipped.

A definition that declares `node.content.generate` may also declare an `autk-grammar` prompt. A run that writes an Autark document on a provider that takes a reply schema uses it in place of the capability's instruction, and holds the reply to the Autark schema. Without that prompt, its runs are never held to the schema.

Once written, import the package with the drawer's **Import agent** button ([part 5](#5-importing-publishing-and-sharing)).

---

## Operator notes

Curio ships with **no default LLM endpoint**. Until an operator sets a Deployment default, or a user adds an LLM configuration on the **API keys** tab of **API Settings**, that user's agents stop with the error *"No LLM configuration answers this run."* and a link to API Settings.

| Variable | Flag | Effect |
|---|---|---|
| `CURIO_DEFAULT_LLM_API_TYPE` | `--llm-provider` | The provider kind of the deployment's endpoint. |
| `CURIO_DEFAULT_LLM_BASE_URL` | `--llm-base-url` | The deployment's endpoint. With it or a key set, users are offered **This Curio install**. |
| `CURIO_DEFAULT_LLM_MODEL` | `--llm-model` | The Deployment default's model. Without one there is no Deployment default. |
| `CURIO_DEFAULT_LLM_API_KEY` | none | The deployment's API key. Set it in the environment. |
| `GUEST_LLM_API_KEY` | `--guest-llm-api-key` | The key of the guest configuration, which every guest on a `--deploy` instance answers with. Unset, it takes `CURIO_DEFAULT_LLM_API_KEY`; with neither, guests get no AI. |
| `GUEST_LLM_API_TYPE`, `GUEST_LLM_BASE_URL`, `GUEST_LLM_MODEL` | `--guest-llm-provider`, `--guest-llm-base-url`, `--guest-llm-model` | The guest configuration's provider, endpoint and model. Unset, it takes the deployment's; an empty endpoint is the provider's own. A guest configuration needs a key and a model. |
| `CURIO_SEARCH_URL` | `--agent-search-url` | Where the web-search tool looks, as a URL template with `{q}`. Defaults to DuckDuckGo's keyless Instant Answer API; point it at a local SearXNG, SerpAPI, or Google Programmable Search for ranked results. |
| `CURIO_SOLVE_MAX_ATTEMPTS` | `--solve-max-attempts` | How many times Solve may try one node, counting the first generation. Default 40. |
| `CURIO_SOLVE_NODE_BUDGET` | `--solve-node-budget` | Wall-clock seconds Solve may spend repairing a node solved on its own, as with **Solve this node**. Default 900. |
| `CURIO_SOLVE_SESSION_DEADLINE` | `--solve-session-deadline` | Seconds one Solve session keeps managing the dataflow. A node in the session gets what is left of it as its repair budget. Default 900. |
| `CURIO_SOLVE_BATCH_DEADLINE` | `--solve-batch-deadline` | Seconds a Solve batch may run in all. Default 2700. |
| `CURIO_VALIDATION_EXEC_TIMEOUT` | `--validation-exec-timeout` | Seconds one node may run when an agent validates code. Default 300. |
| `CURIO_VALIDATION_NODE_LIMIT` | `--validation-node-limit` | How many nodes one validation run may execute. Upstream nodes whose earlier output is reused do not count. Default 25. |

Run `python curio.py start --help` for the current list. A flag writes its variable only when passed, so a value already in the environment is not cleared by a start that omits it.

**Anyone signed in can publish.** Agent publishing has no on/off switch. The only restriction is ownership: you may publish only definitions you imported. On a multi-tenant deployment, any signed-in user can publish an agent they wrote into the shared catalog.

**The usage record needs no care.** The per-day files under `.curio/users/<key>/agents/ledger/` are append-only and rotate by date. Deleting a day's file loses that day's history and nothing else, and nothing expires the files automatically.

---

## See also

- [`docs/NODE-CATALOG.md`](NODE-CATALOG.md): the node package catalog, whose storage and publish model this one mirrors.
- [`docs/DATA-CATALOG.md`](DATA-CATALOG.md): the dataset catalog, the closest peer to this one.
- [`docs/DISCOVERY-CATALOG.md`](DISCOVERY-CATALOG.md): the data portals the Dataset Finder can search.
- [`docs/ARCHITECTURE.md`](ARCHITECTURE.md#agent-runtime): how Solve, source grounding, node code keys and evaluation work, the agent routes, and the backend layout.
- [`docs/schemas/agent-package.v1.json`](schemas/agent-package.v1.json): the manifest JSON Schema.
- [`docs/examples/prompts/README.md`](examples/prompts/README.md): the prompt fixtures, a reviewed prompt for each shipped example, and how to write one.
- [`utk_curio/backend/app/agents/`](../utk_curio/backend/app/agents/): the implementation.
