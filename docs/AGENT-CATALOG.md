# Agent Catalog

The Agent Catalog is where Curio's **hookable agents** live: the assistants you attach to a node, a connection, or the whole canvas.

Curio has six catalogs: the [Node Catalog](NODE-CATALOG.md) holds the nodes you drop on the canvas, the [Data Catalog](DATA-CATALOG.md) the datasets they read, the [Model Catalog](MODEL-CATALOG.md) the models they run, the Agent Catalog the assistants you attach to them, the [Discovery Catalog](DISCOVERY-CATALOG.md) the portals, storage, services and models you take datasets and models from, and the [Scenario Catalog](SCENARIO-CATALOG.md) the scenarios saved in your projects.

This guide is in six parts, plus operator notes:

- [1. What is the Agent Catalog?](#1-what-is-the-agent-catalog): agents, the ones that ship and how each picks what to run, and the storage layers.
- [2. Surfaces and workflows](#2-surfaces-and-workflows): the three places you manage agents, the action matrix, walkthroughs, and catalog settings.
- [3. Using an agent in a dataflow](#3-using-an-agent-in-a-dataflow): adding, attaching, and the difference between the two.
- [4. LLM configurations](#4-llm-configurations): which model answers, and where it is set.
- [5. Importing, publishing, and sharing](#5-importing-publishing-and-sharing): your own definitions, and offering them to everyone.
- [6. The manifest](#6-the-manifest): writing your own agent.
- [Operator notes](#operator-notes): the Deployment default and launcher flags.

---

## 1. What is the Agent Catalog?

### Concept

An **agent** in Curio is a small self-contained folder, shaped like a node package, named by its id and the major of its version:

```
<agentId>@<major>     e.g.   agent.curio.researcher@1
                             agent.curio.dataflow-builder@1
```

The folder holds a `manifest.json` (the contract) and the prompt files the manifest references:

```
agent.curio.researcher@1/
  manifest.json
  prompts/researcher_instruction.md
  prompts/researcher_notes_instruction.md
  prompts/research_instruction.md
```

Its manifest also names the preamble Curio shares with every agent, `curio:default_preamble.md`. An exported or added copy of the agent carries it as `prompts/default_preamble.md`.

An agent id is **`agent.`**, its publisher and its name (`agent.curio.researcher`, `agent.acme.heat-risk-summarizer`), as a dataset id is `data.` and its publisher (`data.utk.chicago-boundary`). The manifest's version is a full semver string, and a newer version of the same major replaces the older one in its folder.

### The agents

Agents build with Curio's own nodes, [functions](../agents/agent.curio.builtin@1/knowledge/node-functions.md), catalogs and chips, as you do, and read what you made with them.

An agent uses only what you have: the code it writes reads your Data Catalog's datasets, runs the models you added and uses the keys you saved, calling only the functions and importing only the modules its node gets.

**Seven agents ship with Curio.** Four of them are the catalog: **Researcher**, **Node Builder**, **Dataflow Builder** and **Dataset Finder**. This guide uses three words for what an agent does:

- **In chat:** what you can ask an agent where you dropped it.
- **Tools:** the actions an agent takes during a chat, such as reading the dataflow, searching the web, proposing a node or proposing a package install. Anything that changes your dataflow is a proposal you apply.
- **Modes:** what another agent, Solve or the agent itself can ask it to do. A mode runs as a separate call with no tools, on evidence Curio gathers for it, and has its own prompt when it needs one. You never chat with a mode. Each mode's capability id and prompt are listed under [Modes](#modes).

| Agent | In chat | Tools | Modes (who asks) |
|---|---|---|---|
| **Researcher** | Explains a node or the dataflow, diagnoses errors, helps define what to build, answers web questions as notes, checks facts | Read the dataflow and a node's last run; search and read the web; propose notes as Note nodes; propose a notes package | Notes from search results (Dataflow Builder); Check a fact (Node Builder, Dataset Finder, Dataflow Builder) |
| **Node Builder** | Builds a node, rewrites a node's content, suggests nodes for a connection, finds or writes node types | Read the dataflow, a node's last run and its history; search the Data and Model Catalogs; propose a node, a content change, a package install or a package draft | Write a node's content (Node Builder, Dataflow Builder, Solve); Recommend packages (Dataflow Builder); Write a package (Node Builder, Researcher, Dataflow Builder) |
| **Dataflow Builder** | Plans a whole dataflow, then solves its nodes | Read the dataflow, runs and node histories; propose a plan, a node or a package draft; read worked examples | None |
| **Dataset Finder** | Finds datasets in the Data Catalog and in portals | Search the catalog and portals; propose a download | Find datasets (Node Builder, Dataflow Builder, Solve) |

The other three are helpers. They have modes only, never a chat: they are never listed, added or attached, and a catalog agent asks for their modes without them being added to the dataflow.

| Helper | Modes (who asks) |
|---|---|
| **Dataflow Planner** | Plan a dataflow's tasks, refresh them and check a plan's coherence (Dataflow Builder); plan a follow-up from a node's run (Node Builder, Dataflow Builder); bind the keywords of a description (Dataset Finder); extract them (no agent asks for this) |
| **Dataflow Reader** | Explain the whole dataflow (Dataflow Builder); suggest its next steps (Dataset Finder, Dataflow Builder) |
| **Generated Content Evaluator** | Check generated node content against its goal (Node Builder, Dataflow Builder) |

Each of the seven is a folder in Curio's [`agents/`](../agents/), `agents/<agentId>@1/`, in the format of an agent you import ([The manifest](#6-the-manifest)). Its manifest's `catalog` says whether it is a catalog agent or a helper, and its place in the order the lists of who asks follow.

### How an agent picks what to run

- Every model call is the shared preamble plus one instruction, never two combined.
- A message you type goes to the agent's chat instruction, and the model follows its rules: in the same call that answers you, it decides what you asked for and which tools to use.
- A mode runs only when another agent, Solve or the agent itself asks for it, as a separate call with no tools.
- Curio picks the file from what the call is for; the model does not.
- Curio finds the agent for a job by the capability its manifest declares, never by its name or id (see [Capabilities](#capabilities)). An agent of your own that declares what a shipped one does is picked where the shipped one would be.

Each agent's prompts, by the key its manifest gives them:

**Researcher**

| Key | File | When it runs |
|---|---|---|
| `system` | [`default_preamble.md`](../agents/agent.curio.builtin@1/default_preamble.md) | every call |
| `instruction` | [`researcher_instruction.md`](../agents/agent.curio.researcher@1/prompts/researcher_instruction.md) | a message you type |
| `research.notes.compose` | [`researcher_notes_instruction.md`](../agents/agent.curio.researcher@1/prompts/researcher_notes_instruction.md) | the Dataflow Builder asks for notes from search results |
| `research.verify` | [`research_instruction.md`](../agents/agent.curio.researcher@1/prompts/research_instruction.md) | another agent asks for a fact to be checked |

**Node Builder**

| Key | File | When it runs |
|---|---|---|
| `system` | [`default_preamble.md`](../agents/agent.curio.builtin@1/default_preamble.md) | every call |
| `instruction` | [`node_build_instruction.md`](../agents/agent.curio.node-builder@1/prompts/node_build_instruction.md) | a message you type |
| `node.content.generate` | [`new_content_prompt.md`](../agents/agent.curio.node-builder@1/prompts/new_content_prompt.md) | someone asks for a node's content |
| `autk-grammar` | [`new_content_autk_prompt.md`](../agents/agent.curio.node-builder@1/prompts/new_content_autk_prompt.md) | the same, for an Autark node |
| `package.recommend` | [`package_recommendation_instruction.md`](../agents/agent.curio.node-builder@1/prompts/package_recommendation_instruction.md) | the Dataflow Builder asks which packages a task needs |
| `package.build`, `package.extend`, `node.kind.author` | [`package_build_instruction.md`](../agents/agent.curio.node-builder@1/prompts/package_build_instruction.md) | someone asks for a package to be written |

**Dataflow Builder**

| Key | File | When it runs |
|---|---|---|
| `system` | [`default_preamble.md`](../agents/agent.curio.builtin@1/default_preamble.md) | every call |
| `instruction` | [`orchestration_instruction.md`](../agents/agent.curio.dataflow-builder@1/prompts/orchestration_instruction.md) | a message you type |

**Dataset Finder**

| Key | File | When it runs |
|---|---|---|
| `system` | [`default_preamble.md`](../agents/agent.curio.builtin@1/default_preamble.md) | every call |
| `instruction` | [`discovery_instruction.md`](../agents/agent.curio.dataset-finder@1/prompts/discovery_instruction.md) | a message you type, and another agent or Solve asking for datasets |

### Walk-throughs

**Node Builder on a node: "turn this into a bar chart".**

1. Your message goes to the chat: the preamble and `node_build_instruction.md`, with the node, its last run and the Node Builder's tools. The model may read the node first, then asks for its content mode, with the node's id and what you asked for.
2. The content mode runs: the preamble and `new_content_prompt.md`, or the Autark prompt for an Autark node, with no tools. Curio hands it the node, what feeds it and the dataflow's task, and it replies with the node's new content.
3. Curio turns that content into a review card, and the chat runs again to tell you what changed. The node changes when you apply the card.

**Node Builder on a connection.**

1. Drop the Node Builder on the connection between two nodes and ask what could go there. The chat runs with `node_build_instruction.md`, told which node's output feeds which node's input, and suggests up to three nodes in prose.
2. Tell it which one you want. The chat proposes that node, and you review it. You connect the new node on the canvas yourself.

**Node Builder writing a node type: "score the sentiment of each review".**

1. The chat runs with `node_build_instruction.md`. No template on the dataflow does this and no catalog package fits, so the model asks for its package-writing mode, naming the templates it considered and why each falls short.
2. The writing mode runs: the preamble and `package_build_instruction.md`, with no tools. Curio hands it the packages you have and the shape of a draft, and it replies in JSON with a package draft and a justification: the closest existing templates and why each is inadequate.
3. Before building the draft, Curio checks each template it adds: the draft carries the justification, the template's label is not the label of a template the dataflow can use, and its code reads only files and web addresses Curio can ground. A draft that fails a check goes back to the writing mode with what to change.
4. Curio builds the package, and the review card shows the justification first, then the files, dependencies and preview. The package installs, with the nodes the draft asks for, when you apply the card.

**Researcher on a failed node: "why did this node fail?"**

1. The chat runs with `researcher_instruction.md`, the node, its last run and the dataflow on screen. The model reads the node's last run with its read tool.
2. The chat runs again with what it read, and answers with the cause and the fix. It uses no web tools and places no notes.

**Researcher on a web question: "which open datasets give building heights for downtown Chicago?"**

1. The chat runs with `researcher_instruction.md` and searches the web; a further round reads a page it will cite.
2. It answers in prose and proposes notes as Note nodes: the question in yellow, then each answer in green with its sources. Each proposal waits for your review.

**Researcher on a fact check: "is the dataset id abcd-1234 real?"**

1. The chat runs with `researcher_instruction.md` and fetches the dataset's address.
2. It answers in the chat, one labeled finding per line: VERIFIED, REPORTED or UNVERIFIED, with what it checked. It places no notes.

**Dataflow Builder asking the Researcher for notes.**

1. You ask the Dataflow Builder a research question. Its chat runs with `orchestration_instruction.md` and asks for the Researcher's notes mode, with your question.
2. Curio runs one web search. The notes mode runs: the preamble and `researcher_notes_instruction.md`, with no tools, given the search results, the notes templates the dataflow can use and the reply shape. It replies in JSON.
3. Curio turns the reply into note proposals in the Dataflow Builder's chat, and that chat runs again to state the answer. The notes are placed when you apply them.

### Categories

Every agent declares one **category**, which the browse page's rail counts:

| Category | What the agent acts on |
|---|---|
| `node` | One node: its content, its errors, its output. |
| `canvas` | The whole dataflow: planning, explanation, suggestion. |
| `data` | Datasets and data shape. |
| `evaluate` | Review, validation, and scoring. No catalog agent ships in it; the Generated Content Evaluator does. |
| `package` | Node packages: recommending, resolving and writing them. No card ships in it. |

Each category has its own colour and glyph in the interface, so a card is identifiable at a glance.

### Storage layers

Agent state lives in files under `.curio/` and inside each project's spec; the agents Curio ships are read from its own `agents/` folder. Knowing which layer an action writes is the key to predicting what happens after **Add to project**, **Add to all projects**, **Remove from project**, or attaching an agent:

| Layer | On disk | Written by |
|---|---|---|
| **Shipped agents**, the seven Curio ships | `agents/<agentId>@<major>/` beside `utk_curio/` (`utk_curio/_shipped/agents/` in a pip install), each a `manifest.json` and `prompts/` | Nothing: Curio reads them. Adding one to a project copies it into your definition store. |
| **Shared catalog**, published agents | `.curio/agents-catalog/<agentId>@<major>/` | **Publish** adds one; **Unpublish** removes it. |
| **Definition store**, the agents themselves | `.curio/users/<user-key>/agents/<agentId>@<major>/` (`manifest.json` and `prompts/`) | **Import agent** adds one; adding a built-in or published agent copies it here. |
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

- **The `/catalog/agents` page** is the account-level library. Reach it from `/projects` and the **Agent Catalog** tab. It lists the built-in agents, every published one, and the ones you imported yourself. Filter by status (**All agents**, **In all projects**) and by category, search, and read an agent's full details. **Add to all projects**, **Publish**, **Unpublish**, **Settings** and **Import agent** live here. You cannot add an agent to just one dataflow from this page: the drawer does that.
- **The Agent Catalog drawer**, inside the canvas, is the working surface. Open it from the **Agent Catalog** button in the top bar, or from the left Tools panel's **Agent Catalog** dropdown and **Browse Agent Catalog +**. Its tabs are **Browse all** (the default) and **In project**, and everything scoped to the open dataflow happens here, including **Import agent** in its footer.
- **The Agent palette**, the **Agent Catalog** dropdown in the left Tools panel, holds the agents already added to this dataflow, ready to drag onto a node, a connection, or the canvas. It sits below the **Node Catalog** and **Data Catalog** dropdowns.

**View details**, on any agent card and beside each agent in the palette, opens the agent's details window. Its first three sections use the three words defined in [The agents](#the-agents): **In chat** says what you can ask the agent where you drop it, **Tools** lists the actions it takes in that chat, what it reads before what it proposes, and **Modes (who asks)** lists each mode with the agents, or Solve, that ask for it, and the mode's capability ids beneath it. **Agent info** gives its identifier, version, category, publisher, what it attaches to and the model it runs on. **Prompts** shows each prompt file, labeled by when it runs: every call, a message you type, or the mode that reads it. **Requires** names the agents it cannot work without, and **Export** saves the agent as one file.

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

Not every agent accepts every target: an agent declares which kinds it works with. A `canvas` agent dropped on a node is refused. Of the four catalog agents, the Node Builder is the one that accepts a connection.

The Researcher reads the dataflow as it is on screen with every message, unsaved edits included, and when it is attached to a node, that node's content, what feeds it and its last run.

An agent that writes code, in its chat or when Solve or another agent asks it, also reads what the dataflow can use: the datasets and models under **Datasets in project** and **Models in project**, each with the line that loads it, and the names of your Node code keys, never their values. When it writes a node's code, it reads that node's template too: its whole description, its starter, and the functions the node's code can import from the template's package and from the packages that package needs. When that is more than fits, it reads the first part and how much was left out.

Each attachment has its own chat transcript and its own **intent**, the editable first instruction, which starts as the definition's own prompt. An agent must be added to the dataflow before you can attach it.

When an agent proposes a change to your dataflow, it does not apply it. The proposal appears as a **review card**, and applying it is a separate click, which first checks that the target has not changed since the proposal. Dismissing it leaves nothing behind. A chart or a map an agent proposes is checked against its grammar's schema before its card appears.

Once you apply a change an agent made to a node's code, the change is an entry of the node's [Provenance](USAGE.md#provenance) drawer, named after the agent, with the code it left, and a node an agent proposes with its code starts its history with one once you apply it. You open the entry and put its code back as you would a run's; an agent never does that for you. The Node Builder and the Dataflow Builder read a node's history as the dataflow was last saved, so you can ask either what changed in a node since a run.

A reply of Node Builder or Dataflow Builder that carries no review card says **No changes were made to the canvas** under it. A web address the egress policy refused shows its reason under the reply. So does any other tool call that failed, unless a later call of the same tool in that reply succeeded.

### Required agents

An agent may require others: the agents a job of its own runs without asking the model, such as the Node Builder and the Dataset Finder that the Dataflow Builder's Solve runs. The drawer says so before you click: the button reads **Add to project (+2 required)**, and its tooltip names what else will be added. Adding brings in all of them at once. A required agent that ships with Curio is added at its shipped version; one of your own at the highest version in your imports or the catalog.

The job itself goes to the agent in the dataflow that declares its capability: the one the requiring agent's `delegatesTo` names first, else any other that declares it and that `delegatesTo` does not name. So an agent of your own that requires your own copies of the Node Builder and the Dataset Finder runs them.

The reverse holds too. Removing an agent that another added agent requires is refused, with a message naming the agent that needs it, so a dataflow never holds a broken reference.

### Solve

The **Dataflow Builder** plans a whole dataflow. Once you apply its plan, **Solve** in its strip fills in the planned nodes in one batch, and **Solve this node**, in the chat of an agent attached to a node, does the same for one node.

Solve runs what it writes. A node with code is generated, run in the sandbox, corrected when the run fails, and written only once a run passes. The nodes run in waves, the loaders first and then what depends on them, and the strip shows which wave is running (*wave 2 of 3*). A chart or map document is checked against its grammar's schema and reported as validated, not executed. A node with nothing to write, such as a Data Pool or a Spatial Join, is left wired as it is. A node of a package template whose starter is its whole content ([Authoring nodes](AUTHORING-NODES.md#widgets-in-a-template)) starts with that starter and the template's widgets, set as the plan declares them, and Solve leaves it as it is too.

When Solve cannot fix a node, nothing is written, and the chat shows every attempt as its own row: the exception, where it was raised, and the code that attempt ran. The message names what stopped the loop, normally the time budget: the Solve's 15 minutes, or the node's own 15 minutes when you use **Solve this node**. A Solve keeps working for up to 15 minutes, and runs on if you close the chat or reload the page. **Stop** ends it after the current node, and what was written stays. What it did not reach stays *pending* with the reason, and **Solve** continues from there; after a failure or a server restart, the same button reads **Retry**.

Applying a plan gives every created node the agent that writes its content, the one that declares `node.content.generate` (the **Node Builder**). Every node that loads a dataset, one whose template declares `loadsDataset` such as Data Loading, also gets the agent that finds datasets, the one that declares `dataset.discover` (the **Dataset Finder**). When such a node's source is not settled, Solve asks that agent for candidates: they appear in its chat, and the node stays pending, *awaiting your dataset selection*, with an **Open Dataset Finder** button. **Confirm source for this node**, in the chat of an agent that declares `dataset.select`, records your choice, and the next Solve builds the loader from that source.

A node with several inputs reads each through its input chip, `[!! input_0 !!]`, `[!! input_1 !!]` and so on, in the order of its input circles (see [Several inputs](USAGE.md#several-inputs)), and the agent is told which dataset sits on each circle. Code that treats the inputs as one value is refused before it runs.

### Widgets and scenarios

A planned node can declare widgets: values you set in its **Widgets** tab, which its code reads through references such as `[!! threshold !!]` (see [Widgets](USAGE.md#widgets)). The review card lists each node's widgets, and Solve writes code that places them and is told their current values. A value several nodes read is a **Parameter** node with one widget. A node the **Node Builder** proposes can declare widgets too. A widget a plan or a proposal declares is checked as the **Widgets** tab checks one you add.

A planned **Spatial Join** says how its inputs' shapes meet and what it outputs, the two choices its body offers, and the review card lists them. A Spatial Join the **Node Builder** proposes carries them too. An agent can set only an operation and an output the node offers.

A plan can also save [scenarios](USAGE.md#scenarios). A scenario in a plan is either a named selection of its nodes, or a duplicate of one: its nodes are copied with the connections between them and every connection entering them, as **Duplicate as scenario** copies them on the canvas, and the copies can be given other widget values. The review card names each scenario with its nodes, and for a duplicate the scenario it copies and the values it changes; each copy is listed as a node with its scenario beside its title.

Applying the whole plan saves its scenarios. Applied node by node, a copy can be created only after the node it copies, and a scenario is saved with the last of its nodes. A scenario that would take a node another scenario holds is not saved, since a node belongs to one scenario. A plan's scenario takes a name no scenario of the dataflow has, and one that would repeat a name you gave a scenario after the review is not saved. A duplicate copies nodes the plan adds; scenarios already on the canvas are duplicated there. Solve writes a copy's code as it writes any planned node's, so the two can differ; compare them before relying on the comparison.

An agent that reads the dataflow sees each scenario with its fixed context, levers and outcomes, each node's widget values, and each node's [selection tags](USAGE.md#selection-tags), with the view each reads and how many rows it holds.

### Map Edits

An agent writes a Map Edits node's code as the node writes it: one call that holds the node's edits, which the node lists and shows on its map. Code the node cannot read is refused, and the agent is told why in the node's own words. An edit names its features by ids their layer holds, or by a condition; when a run says an edit names ids no feature has, Solve corrects it. Solve makes edits in an empty Map Edits node only when its goal names them, such as *Remove the two tallest towers*; otherwise the node gets its call with no edits, as when you drop it, and you make the edits on the map. An agent writing a node beside a Map Edits node reads its edits. Once you apply a change an agent made to a Map Edits node, it is an entry named after the agent in the node's Provenance drawer, as on any node, and the nodes below it are out of date until they run again, as when you edit the node yourself.

### Finding data in portals

The **Dataset Finder** can search the portals in the [Discovery Catalog](DISCOVERY-CATALOG.md) as well as your own datasets, and propose downloading one. Nothing is downloaded until you apply the proposal. See [DISCOVERY-CATALOG.md part 6](DISCOVERY-CATALOG.md#6-the-dataset-finder). In any agent's chat, the **From your Data Catalog** lane of a candidates card lists only datasets your Data Catalog holds, installed or not as the Data Catalog shows them, and a card left with no dataset says so. Confirming a row reads it from your Data Catalog again. Solve and the other agents ask whichever agent in the dataflow declares `dataset.discover`, so an agent of your own that declares it, with the same tools, searches in its place.

---

## 4. LLM configurations

Every agent, on every dataflow, answers with an **LLM configuration**: the one chosen for it in **API Settings**, else your default. Configurations belong to your account. **API Settings** is in the top bar: on `/projects` and the catalog pages it opens the settings page; on the canvas and the dashboard it opens on the right side, and the dataflow stays open. The **API Settings** button in the Agent Catalog drawer's header opens it on the **Agent configuration** tab. Configurations are the rows of kind **Language model** on the **API keys** tab. A configuration is:

| Field | What it is |
|---|---|
| Label | Your name for it, unique in your account. |
| Provider | OpenAI, Anthropic, Gemini, Custom (any OpenAI-compatible endpoint), or **This Curio install** when the operator offers its endpoint. |
| Base URL | Only for Custom: Ollama, LM Studio, vLLM, Groq, Azure. |
| API key | Write-only, and held for this configuration's endpoint only. Editing leaves it in place unless you type a new one or remove it; changing the provider, or the base URL's scheme, host or port, needs it again. This Curio install uses the operator's key, which you never see. |
| Model | Which model answers. For OpenAI, Anthropic and Gemini the empty box shows the provider's default model in grey; type it or another model. **Fetch models** suggests what the endpoint serves. |

To add a configuration:

1. Get an API key from the provider (see [USAGE.md](USAGE.md#your-configurations) for each provider's link).
2. Open **API Settings** from the top bar (on the canvas it opens on the right).
3. On the **API keys** tab, click **Add configuration**.
4. In **Kind**, choose **Language model**.
5. Type a **Label**, choose the **Provider**, paste the **API key**, and type the **Model** (the provider's default model is shown in grey), or click **Fetch models** and pick one. **Custom** also asks for the **Base URL**.
6. Click **Add configuration**. The configuration's row shows in the list, with **saved** in its **Key** column when you gave a key.

**Make this my default** is ticked for your first configuration. Each row offers **Edit**, **Duplicate** (the copy keeps the key) and **Remove**; an account holds up to 32. Its **Details** show the provider, the model and the host, and **Chosen for** lists the agents chosen to run on it. The **Default** badge marks your default. The **Deployment default** row is the operator's own configuration: read-only, with **set by this Curio** in its **Key** column, shown when the operator configured one, and the one that answers while you have no default of your own. Choosing it in **Default for agents**, or removing your own default, goes back to it.

### Default and Agent models

The **Agent configuration** tab chooses which configuration answers. Its **Default** section names what answers your agents (**Answering now:** a label and a model) and sets your default in **Default for agents**: the Deployment default or any of your configurations. Below it, **Agent models** lists the four catalog agents plus your imported and published agents, each with a select: **Default** (your default configuration), any of your configurations, or the Deployment default. A change is saved at once. Which configuration answers a run:

| Run | Configuration |
|---|---|
| An agent you attach (chat, Solve, Simulation, the per-node Solve) | Its choice, else your default, else the Deployment default |
| A mode another agent asks for | Its agent's choice, else its caller's |
| An internal helper (the Dataflow Planner, the Dataflow Reader, the content evaluator) | Always its caller's |
| A guest on a `--deploy` instance | The guest configuration, for every agent |

A choice that names nothing, such as a removed configuration or a Deployment default the operator withdrew, refuses the run with **Open API Settings**, which opens the **Agent configuration** tab on that agent's row; it never falls back to another configuration. Removing a configuration sends the agents chosen for it back to the default, and its confirmation names them.

A Solve of the Dataflow Builder runs on the Builder's configuration, and writes each node's content through Node Builder's content mode and each source through Dataset Finder, each on its own choice. The choices a Solve needs are checked before it starts, and one that names nothing refuses it. After a dataset selection, the node is built on its builder's configuration, not the Dataset Finder's.

The choice is per account, for every version of the agent and every project. A shared project carries none, so it runs on the configurations of whoever runs it. An agent's details show what it runs on, with **Change in API Settings**, which opens the **Agent configuration** tab on its row; a reply's status line says, on hover, which configuration and model answered it; and a mode another agent asked for names, in the chat, what it ran on.

An agent's tools (reading the dataflow, searching the Data Catalog or the Model Catalog, reading a shipped example dataflow, proposing a node or a plan, asking another agent for one of its modes) work the same on every configuration, and every change waits for your review. For a Custom endpoint, Curio asks once per model whether it calls tools, the first time an agent with tools runs on it: one short request, billed like any other and kept in the usage record.

### Choosing the model

**Fetch models**, under the Model field, asks the endpoint on screen what it serves, using the provider, base URL and key currently in the form, so you can choose a model for an endpoint you have not saved yet. While you edit a saved configuration, a blank key box asks with its saved key, as long as the endpoint on screen is still the configuration's own. What comes back is offered as suggestions in the Model box.

It is a convenience, not a gate: the field stays free text. Two sources fill the suggestions:

| Source | What it is |
|---|---|
| *From this endpoint* | What the endpoint reported just now. For Gemini, only models that support `generateContent` are offered. |
| *Last reported by this endpoint (on <date>)* | What it reported the last time it could be asked, shown when it cannot be asked now: no key pasted yet, offline, or a key without permission to list models. |

Until a key has listed an endpoint's models, there are no suggestions: the Model box shows the provider's default model in grey, and you type the model. A model you type by hand is always accepted.

Whoever runs the install can set a Deployment default with `curio.py start` flags (see [Operator notes](#operator-notes)). It is not stored in your account, so when the operator changes it, the Deployment default row changes with it.

**Curio does not meter, cap, or bill agent runs.** There is no quota screen and no spend limit: the tokens are billed to whoever's key is in use. Curio keeps a local, per-day record of what ran (see [Storage layers](#storage-layers)), and calls no usage or billing API.

---

## 5. Importing, publishing, and sharing

**Import agent**, in the drawer's footer or the `/catalog/agents` header, takes a `manifest.json` and its `.md` or `.txt` prompt files, not an archive. The prompt files must match what the manifest references, except a `curio:<path>` path, which names a page of Curio's own and takes no file; size limits apply; and a manifest that sets `catalog` is refused. An agent whose id and major you already have replaces yours when its version is newer, and is refused otherwise.

**Publish**, on `/catalog/agents`, copies one of your own imported definitions into the shared catalog, where every user on the install can browse it. Built-in agents cannot be published. **Unpublish** removes it from the shared catalog, and only the publisher can do it; only the publisher can publish over it, too. Other users who added the agent keep their copy and keep running it, and a newer version of the same major reaches them the next time they add the agent to a dataflow.

---

## 6. The manifest

An agent package is a folder named `<agentId>@<major>`, the major of its version, holding a `manifest.json` and a `prompts/` directory. The agents Curio ships are such folders in its [`agents/`](../agents/), read the way an imported agent is. The manifest uses **camelCase** field names; [`docs/schemas/agent-package.v1.json`](schemas/agent-package.v1.json) (JSON Schema Draft 2020-12) is the full reference.

A minimal, complete manifest:

```json
{
  "$schema": "../../docs/schemas/agent-package.v1.json",
  "id": "agent.you.my-helper",
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
    "system": { "path": "curio:default_preamble.md", "variables": [] },
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
| `id` | Yes | `agent.`, the publisher and the agent's name, each kebab-case: `agent.you.my-helper`. With the major of `version` it forms the folder name `<id>@<major>`. |
| `version` | Yes | Semver-style version string. A newer version of the same major replaces an older one. |
| `name` | Yes | Human-readable name shown in the catalog. |
| `category` | Yes | One of `data`, `node`, `canvas`, `package`, `evaluate`. See [Categories](#categories). |
| `capabilities` | Yes | Non-empty list of `{ id, contractVersion }`: the contracts this agent implements. A capability that also names an `instruction` is a mode; see [Modes](#modes). |
| `provenance` | Yes | `{ publisher, license?, trust? }`; `trust` is one of `built-in`, `global`, `imported`. |
| `purpose`, `roles` | | One-line description and display roles. |
| `delegatesTo` | | Other `agent.` ids this agent may call, in preference order. An entry `{ "id", "capabilities": [...] }` delegates only those capabilities of that agent. An entry may name the agent itself only in that form, with capabilities that are its own [modes](#modes). A preference only: it grants nothing and never adds or imports anything. |
| `requiresAgents` | | A subset of `delegatesTo`: the agents this one cannot work without. See [Required agents](#required-agents). |
| `prompts` | | Prompt files by package-relative `path`, `sha256`, and declared `variables`. Absolute paths and `..` are rejected. A path `curio:<path>` names one of [the pages Curio shares](../agents/agent.curio.builtin@1/) with every agent, by its path there: `curio:default_preamble.md`, the preamble Curio's own agents run, or `curio:rules/research_verify_rules.md`, the rules for checking a fact. Curio reads the page from its own, an import takes no file and no digest for it, and an export carries it as `prompts/<path>`. A `curio:` path that names no page, or leads out of them, is refused. |
| `compatibleTargets` | | Where the agent can attach: `{ kind: node\|canvas\|connection, requires: [...] }`. For `node`, `requires` lists what the node may be, any one of them enough: a flag its template declares, such as `loadsDataset` for a node that loads a dataset ([Node Catalog](NODE-CATALOG.md#6-the-manifest)), or a template id, such as `data-loading`. Empty means any node. |
| `inputs`, `outputs` | | The context the agent reads (`inputs.reads`), the [catalog settings](#catalog-settings) every run of it receives (`inputs.requiredConfig`), and the named outputs it produces. |
| `runtime` | | `execution` (`foreground` or `background`) and `reviewPolicy` (`report-only` or `review-before-apply`). |
| `providerRequirements` | | Provider *capability* requirements such as `structured-output`, as a preference: an agent runs on the configuration chosen for it whatever these say. Credentials and configurations are never in a manifest. |
| `tools` | | Typed, allowlisted tool **requirements**, not a permission grant. |
| `settingsDefaults` | | Non-secret seed suggestions. |
| `catalog` | | `{ listed, order }`, set by the agents Curio ships only: `listed` is `true` for a catalog agent and `false` for a helper, and `order` is the agent's place in the order the lists of who asks follow. No other key is accepted, and an import that sets it is refused. |
| `workedExamples` | | `true` gives a run of the agent's instruction worked examples, the shipped dataflows closest to its task. A mode says so for itself, with `workedExamples` on its capability. Read for the agents Curio ships. |

### Capabilities

A **capability** is a contract, meaning *what* an agent does, separate from the prompt file that implements it. A capability id is two or more dot-separated lowercase segments:

```
node.explain            dataflow.orchestrate       package.recommend
node.output.interpret   dataset.fetch.author       research.verify
```

Capability ids drive catalog discovery, orchestration and substitution, and are **never** used for authorization. A capability id must not contain a prompt filename, a path separator, an underscore, `.txt` or `.md`: `node.explain` is valid, while `explain_node_prompt` and `prompts/explain.txt` are rejected. A prompt can then be edited or replaced without changing the contract.

Curio finds the agent for each of its own jobs by the capability it declares:

| Capability | Curio picks the agent that declares it to |
|---|---|
| `node.content.generate` | write a node's content in Solve; it is attached to every node a plan creates |
| `dataset.discover` | find the datasets a node loads; it is attached to every node a plan creates that loads a dataset |
| `dataset.select` | record the source you confirm for a node, from its chat on that node |
| `dataflow.orchestrate` | plan a dataflow; its chat has the **Solve** strip, and API Settings lists the agents its Solve runs |
| `node.build` | build nodes on the canvas; its chat says when a reply changed nothing on it |

When several agents in the dataflow declare a capability, the one the asking agent's `delegatesTo` names first is picked. When none of those is in the dataflow, an agent in it that `delegatesTo` does not name at all takes the capability, so adding an agent of your own lets the others hand it that work. An agent `delegatesTo` names takes only the capabilities its entry names.

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

An agent can also hand work to one of its own modes. List the agent itself in `delegatesTo`, naming only those capabilities:

```json
"delegatesTo": [{ "id": "agent.you.my-explainer", "capabilities": ["node.output.interpret"] }]
```

A chat with the agent then runs the `instruction` prompt, and when the model asks for `node.output.interpret`, that mode runs as a second call, with no tools, and its answer comes back to the chat. A task for no node opens no chat of its own: it shows in the agent's reply. A capability of its own that no such entry names is never handed back to the agent.

A definition that declares `node.content.generate` may also declare an `autk-grammar` prompt. A run that writes an Autark document on a provider that takes a reply schema uses it in place of the capability's instruction, and holds the reply to the Autark schema. Without that prompt, its runs are never held to the schema.

The agents Curio ships also name their modes in plain words. A capability's `label` is what the details window lists it by, and capabilities with one label are one mode. A prompt that is neither the preamble, the instruction nor a mode's says when it runs with `runs`, as the Node Builder's `autk-grammar` prompt does. Curio reads `label`, `runs` and `workedExamples` for the agents it ships; the details window lists each capability of an imported agent by its id.

The modes of the agents Curio ships, each with its capability id and its prompt in the agent's folder in [`agents/`](../agents/):

| Mode | Capability id | Prompt |
|---|---|---|
| Researcher: notes from search results | `research.notes.compose` | `researcher_notes_instruction.md` |
| Researcher: check a fact | `research.verify` | `research_instruction.md` |
| Node Builder: write a node's content | `node.content.generate` | `new_content_prompt.md`, or `new_content_autk_prompt.md` for an Autark document |
| Node Builder: recommend packages | `package.recommend` | `package_recommendation_instruction.md` |
| Node Builder: write a package | `package.build`, `package.extend`, `node.kind.author` | `package_build_instruction.md` |
| Dataset Finder: find datasets | `dataset.discover` | its own `discovery_instruction.md`, with no separate prompt |
| Dataflow Planner: plan a dataflow's tasks | `workflow.plan.create` | `new_subtasks_prompt.md` |
| Dataflow Planner: plan a follow-up from a node's run | `execution.followup.plan` | `new_subtask_from_exec_prompt.md` |
| Dataflow Planner: refresh a task | `workflow.plan.refresh` | `task_refresh_prompt.md` |
| Dataflow Planner: check a plan's coherence | `workflow.coherence.validate` | `evaluate_coherence_subtasks_prompt.md` |
| Dataflow Planner: bind keywords | `workflow.keyword.bind` | `keywords_binding_prompt.md` |
| Dataflow Planner: extract keywords | `workflow.keywords.extract` | `syntax_analysis_prompt.md` |
| Dataflow Reader: explain the dataflow | `dataflow.explain` | `explanation_prompt.md` |
| Dataflow Reader: suggest next steps | `workflow.suggest` | `workflow_suggestions_prompt.md` |
| Generated Content Evaluator: check generated content | `content.quality.evaluate` | `evaluate_generated_content_prompt.md` |

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
| `CURIO_ALLOW_FACTORY_CATALOG_PUBLISH` | `--allow-publish` (default), `--no-allow-publish` | Allows or forbids **Publish** and **Unpublish** of agents, as it does for node packages and datasets. When forbidden, both are refused and their buttons are hidden on `/catalog/agents`. |

Run `python curio.py start --help` for the current list. A flag writes its variable only when passed, so a value already in the environment is not cleared by a start that omits it. `--allow-publish` is the exception: `curio.py start` sets it on every start.

**On a multi-user install, start with `--no-allow-publish`.** Otherwise any signed-in user can publish an agent they imported into the shared catalog.

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
