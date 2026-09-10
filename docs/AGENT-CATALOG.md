# Agent Catalog

The Agent Catalog is where Curio's **hookable agents** live. It is the third of
three catalogs, alongside the [Node Catalog](NODE-CATALOG.md) and the
[Data Catalog](DATA-CATALOG.md). Where the Node Catalog manages the *nodes* you
drop on the canvas and the Data Catalog manages the *data* those nodes read, the
Agent Catalog manages the *assistants* you attach to them.

This guide covers what an agent is, where its state lives, the three surfaces
you manage agents from, which layer each action writes, and how to write one of
your own.

This guide is in seven parts, plus operator notes:

- [1. What is the Agent Catalog?](#1-what-is-the-agent-catalog): the storage layers, agent ids, and what ships built in.
- [2. Surfaces and workflows](#2-surfaces-and-workflows): the three places you manage agents, the action matrix, and walkthroughs.
- [3. Using an agent in a dataflow](#3-using-an-agent-in-a-dataflow): adding, attaching, and the difference between the two.
- [4. Importing, publishing, and sharing](#4-importing-publishing-and-sharing): authoring your own definitions.
- [5. The provider](#5-the-provider): which model answers, and where it is set.
- [6. Writing your own agent](#6-writing-your-own-agent): the manifest contract and capabilities.
- [7. Measuring the agents against the shipped examples](#7-measuring-the-agents-against-the-shipped-examples): whether a model can rebuild an example from a prompt, what that measurement may not do, and how to train a model on those examples.
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

Each category carries its own colour and glyph in the interface, so a card is
identifiable at a glance.

### Origins

Alongside its category, every agent has an **origin**, which is provenance
rather than function. It is backend metadata: the browse page counts it in its
facets but does not currently offer it as a filter, and no card renders it as a
chip. What the page's left rail offers is a **status** rail (All agents / In my
account / Published) and a **category** rail.

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
  filter by status and category, search, read an agent's full detail, and add an
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
`/projects` and pick the **Agent Catalog** tab. Filter by status or category in
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

### What a dataflow plan may change

A Dataflow Builder plan may add nodes, add connections, and remove — each part
optional, so a plan that only rewires a connection is valid and no filler node
is ever needed to make one (memo `dev/125`, applying `DEC-070`). Two rules make
the result trustworthy:

- **A connection carries a kind.** `interaction` is the Trill's feedback link —
  a visualization and a data-pool node, `in/out` at both ends, bidirectional on
  the canvas, carrying selections rather than data. It is refused anywhere
  else, by a message that names the node it was aimed at.
- **Data connections must stay a DAG.** A plan whose data edge would close a
  cycle is refused when it is proposed, with the loop written out and the fix
  named; the check runs again at Apply against your live canvas, so a cycle you
  drew in the meantime stops the apply rather than being written. A cycle the
  plan did not create is *reported*, never blamed on the plan.

Every removed connection is named on the card, and every applied result ends
with a `Topology:` verdict — `acyclic`, or the path of a cycle still present —
which the agent is instructed to read before it claims a repair. Before this,
an agent asked to fix a cycle could diagnose it correctly, propose the right
repair, and silently rebuild the same cycle on every round, because the kind it
asked for had nowhere to live in the contract.

### Required agents

An agent may declare that it requires others. The drawer discloses this before
you click: the button reads **Add to dataflow (+2 required)** and its tooltip
names what else will be added. Adding pulls in the whole closure in one request.

The reverse is enforced too. Removing an agent that another added agent requires
is refused, with a message naming the dependent, so a dataflow cannot end up
holding a broken reference.

The **Dataflow Builder requires three**: the Node Content Builder (its Solve
generates content through it), the **Dataset Finder** (resolving a data-loading
node asks it for candidates) and the **Node Builder** (every node an applied
plan creates is given one). Each is a server path with no model choice, which is
what "required" means here. The Node Builder in turn requires the Dataset
Finder, for the same reason.

A dataflow created before an agent declared what it requires is **repaired the
next time you act on that agent** — a run, an attach, an apply, a Solve
(memo dev/126, `DEC-080`). The missing required agents are added through the
same install path a click uses, and the chat says so: *"Added Dataset Finder —
required by Dataflow Builder."* Only agents an agent DECLARES as required are
ever added this way; a merely preferred delegate still reaches you as a review
card you apply yourself. Before this, a Dataflow Builder conversation could
spend a turn proposing to install one of its own specialists, and you had to
apply it and ask again.

### Where a data-loading node's source comes from

An agent never decides on its own that a file exists. Every piece of node
content an agent authors — a Node Builder `node.create`, a content replacement,
a new node type's first node, and every node the Dataflow Builder's Solve fills
— passes one runtime **source-grounding gate** before it can become a review
card or reach the saved dataflow (memo dev/114, DEC-072; issue #298, where the
proposed code read `pd.read_csv("bras_ibge_data.csv")` and the file had never
existed):

| The code opens or fetches | Grounded only when |
|---|---|
| A local file path | You typed that path in the conversation, or the Data Catalog resolves it — the portable `curio_dataset_path("<id>")` line the catalog's loader recipe emits counts by dataset id. |
| A URL | The runtime probed it in this run (2xx; 401/403 is accepted and labeled *credential-gated*), or a candidates card in this conversation already carried it as **Verified ✓**. A URL in your own message is not evidence — the runtime checks it. |
| Nothing (inline data in a data-loading node) | You asked for synthetic or sample data; the card then says *Synthetic data*. |

Anything else is **refused with the literal named** and the allowed routes
listed; the refusal is a free correction round for the agent (dev/105), and a
Solve that cannot ground a node marks it *failed — ungrounded source* with the
remedy instead of writing the code. The resulting review card carries a
**Source** block above the preview: the catalog dataset by title and id, the URL
with its verification chip, the user-provided path marked *not checked by
Curio*, or the synthetic label.

Discovery follows the same order. Node Builder holds `catalog.search` (rows
include the resolved path and the loader line) and can delegate
`dataset.discover` to Dataset Finder: the tool-less child receives the catalog
listing as input, its candidates are re-checked against that listing and probed
by the runtime, and the two-lane card appears in the Node Builder's own chat.
Selecting rows prefills an editable **Build the data-loading node — …** prompt;
nothing is proposed until you send it. In the Dataset Finder's chat the same
card composes the reviewed `dataset.install` or the hand-off to Node Builder, as
before.

### The Dataset Finder lives on the data-loading node

Applying a dataflow plan gives every created node a **Node Builder**, and every
**data-loading** node its own **Dataset Finder** as well (memo dev/126) — the
two badges appear on the node as soon as the apply lands, and the applied card
says what it attached. Both plan-apply paths do it identically: the whole-plan
**Apply** and Simulation Mode's per-node apply.

Resolving such a node then goes to that Dataset Finder rather than to a guess:

| The node | What happens |
|---|---|
| Its intent already names a source (a path you typed, a Data Catalog dataset, a URL the runtime verified, or explicitly synthetic data) | Discovery is skipped, and the skip is recorded with the literal that grounded it. |
| Your Data Catalog holds datasets | The first attempt is generated against those rows, and the grounding gate above enforces them. |
| Nothing could ground it, or the attempt was refused for its source anyway | The runtime asks that node's Dataset Finder itself. The candidates appear in **its** chat, and the node's Solve result is **pending — awaiting your dataset selection**, with an **Open Dataset Finder** button. Nothing is generated, run or written. |

On the card, **Confirm source for this node** records your selection against the
node. The record is what the next Solve reads, so the loader is built from
exactly the source you confirmed — not from what a model remembers you picked. A
catalog row that is not installed yet keeps the node waiting for its reviewed
install, and the applied install then says how many nodes it unblocked. A row
the runtime cannot reach at confirmation time is recorded with that verdict and
does **not** resolve the node.

Every external row also says what you can **do** with it (memo dev/132), read
from the same probe — never from the model's prose:

| The row's access | What the card offers |
|---|---|
| **fetchable** — the data URL answered with data (JSON, GeoJSON, CSV, an archive) | Confirming it starts this node's own builder on it immediately. There is no prompt to compose: the loader is written, verified and lands as the ordinary reviewed content, and the card says the builder is writing it now. |
| **manual-download** — the data URL answered with a *page*, or gated it (401/403/451) | The card carries the portal's download steps (its URL, the page as it actually answered, the file format, the row's stated requirement) and an **Import dataset** button — the same Data Catalog import as the drawer footer and the catalog page. After the import, that dataset becomes the node's source and the builder starts on it, by id. |
| **unknown** — nothing was probed, the policy refused the URL, or the answer was neither | The row says so, and nothing upgrades it silently. |

The steps are the portal's, not Curio's invention: when a page title is all the
portal gave, the step says the portal describes the click path. Automating the
download itself is deliberately not done — a click-through portal is a browser
task, and scripting one is both brittle and often against its terms.

A dataset you import or install *while* a Solve session is running is picked up
by it: the moved selection record is what the session watches for, and the
dataset's sandbox path is resolved for the running job rather than waiting for
the next Solve.

The Dataflow Builder therefore plans first and never blocks a plan on dataset
identity: a data-loading node is planned with an honest intent naming the DATA
it needs, and its source is resolved at the node.

### Solve is the engineering loop — and it runs in the background

Grounding says where a data-loading node's source may come from; it does not
say the code works. **Solve** does (memo dev/115, DEC-073; every executable
kind since memo dev/118, DEC-075). When you ask to solve a node — the Dataflow
Builder's **Solve** over an applied plan, or **Solve this node** in the chat of
an agent attached to the node — the runtime executes the node's code in the
sandbox exactly as Play would (same dataset-path mapping, a fetch-sized timeout
aligned to the sandbox's own wall clock), and only code that ran successfully
lands:

| The run… | Then |
|---|---|
| passes | An empty plan node gets the content written. A node that already had content is untouched: "verified — no change needed". |
| fails | The failure goes back to the content generator with the traceback, the previous attempt, the grounded sources, **what its inputs actually contain** (memo dev/127 — the columns, dtypes and row counts of the frames feeding this node, through a merge in `arg` order), and a fresh probe of the URL it fetched (a `400` after a reachable base URL is a wrong request shape, not a dead endpoint). The corrected code is grounded again and re-run. |
| keeps failing | Corrections continue **while this node's repair budget allows — 15 minutes by default**, as many attempts as fit (the attempt cap sits above what a quarter hour affords, so the clock is the normal stop). A repeated candidate does not end the loop: the next correction is told, in plain words, that it repeated itself and must change approach; only a long run of identical candidates stops it. Whichever bound binds is NAMED — *"not fixed after 6 attempts (stopped by the round cap)"*, *"…(stopped by this node's time budget)"*, *"…(stopped by a repeated attempt)"*. A second identical candidate ends it: more retries must not mean more copies. |
| still fails | Nothing is written. The node shows *failed*, and **every attempt appears in the chat** as its own card: one disclosure per round with the exception line, the frame that raised it, and **the code that attempt ran**, copyable, with the last round open. One click opens that node's own agent. |
| cannot run (sandbox unreachable) | The node stays *pending* with the reason — never *failed*: an outage is not a content failure. |

**A node fed through a merge is told what `arg` is.** The merge hands the next
node a **list**, one item per connected input, in the order of its input
handles (`in_0`, `in_1`, …) — and that order is now read from the handles
everywhere: by Play, by Solve's validation runner, and by the contract the
generator is given (memo dev/128). Before that fix the validation runner read
the slot out of the edge's *id*, which an agent-applied edge does not carry, so
a plan-created merge was ordered arbitrarily: a node could pass validation
against `[population, boundaries]` and fail on Play against
`[boundaries, population]`.

The generator receives an `inputContract` for the node — `list` with a slot
table (each slot's node, goal and columns) or `single` — and code that treats a
list-shaped `arg` as a value (`arg.crs`, or `gdf = arg` then `gdf.to_crs(…)`) is
**refused before the sandbox runs**, with the slot table in the refusal, exactly
as an ungrounded source is refused. A merge with only one connected input passes
its value straight through, so there `arg` IS the value and nothing is refused.

**A document that cannot be run is still checked.** A Vega-Lite chart and an
AUTK map grammar are documents, so before either is written into a node the
runtime validates it — Vega-Lite against the schema Curio already ships, the
map grammar against what the renderer cannot draw without (a `map`, a non-empty
`layerRefs`, a `dataRef` per layer) — and an invalid document is a **correction
round** like a failing traceback, with the validator's complaint as the
instruction (memo dev/129; before it, an invalid spec was written and the chat
said *solved* while the node rendered red). A written document is reported as
*"document validated — not executed"*: still honest that nothing ran, no longer
silent about whether it is well-formed. And a kind nothing here can validate is
**not written at all** — the node stays *pending* with the reason, because
nothing unchecked belongs in a node.

A failure never reads as more certain than it is. The exception type and its
message lead every failure line and are never cut mid-word (memo dev/127 —
before it, a sliced traceback reached the chat as `execution-error:
das/core/generic.py`, and one round's message survived as the two characters
`de`), an error the generated code raised itself is labeled as such instead of
being blamed on the library whose file appears in the frame, and *"not fixed
after N attempts"* is always followed by the bound that stopped the loop.

Both budgets are deployment knobs: `CURIO_SOLVE_NODE_BUDGET` (default 900
seconds — the bound that normally binds) and `CURIO_SOLVE_MAX_ATTEMPTS`
(default 40, a cap above what that budget affords), alongside the existing
`CURIO_VALIDATION_EXEC_TIMEOUT` for one run and `CURIO_SOLVE_BATCH_DEADLINE`
for the whole batch. An unusable value falls back to the default rather than
breaking every run.

Apply itself never executes anything and is never blocked by verification: a
proposal's Apply places the node as proposed, and the card says that Solve is
what runs it. Nothing ever claims a node works until a passing run is on record.

**The run outlives the request.** A Solve is a detached job on the server:
closing the chat panel or reloading the page does not stop it. The agent's badge
shows a running dot while the job is live; opening the chat re-attaches to the
live progress (the strip's pills read *generating*, *verifying — running in the
sandbox*, *fixing*, *solved ✓ verified*). Cancel stops after the current node
finishes — a running fetch cannot be aborted. If the server itself stops
mid-Solve, the session is marked **interrupted** the next time it is read: nodes
that finished keep their content, nothing is replayed, and **Retry** starts a
new execution linked to the interrupted one. This is the single-process form of
the runtime's lease model; a multi-instance deployment still needs a durable
job owner and is not claimed.

### Key-gated APIs — connection keys

Many data APIs answer only with a key (the Census API, for one, redirects a
key-less query to a "Missing Key" page). A key must never be a literal in node
code: the code is saved into the dataflow, replayed in every proposal preview,
recorded by the runtime journal on every run and exported with the project.
Curio's answer is a **connection key** (memo dev/116, DEC-074): you save the
key once under a name bound to a host — **AI Settings → Connection keys**,
through a masked field that never reads the value back — and node code
reaches it only as

```python
api_key = curio_secret("census")
```

The runtime resolves the names the code uses at execution time — for Play and
for Solve alike — and hands the values to the sandbox inside the execution
request, where they exist only as that callable in the node's namespace: never
an environment variable (node code can read `os.environ`), never a file, never
a log line. A key a node prints is redacted before the output leaves the
sandbox. The saved dataflow, the journal, the proposals and the chat carry the
name only.

What the agents see is the name, never the value. A content builder's grounded
inputs list `availableSecrets` with the one line to copy and how the API
expects the key (`query:<param>`, `header:<Name>`, or "in the code"); the
grounding gate accepts `curio_secret("<name>")` for a saved name (the Source
block reads *Connection key · census · api.census.gov*), refuses an unknown
name listing the saved ones, and refuses a credential-shaped literal before
anything runs. When a saved key is bound to the host a failing request targets,
Solve probes that request *with* the key and tells the correction what the
keyed request answered, redacted. When no key exists, the content builder
declines in one line and the node's failure ends with a concrete remedy —
**Add key for api.census.gov** — which opens the settings section with the
host filled in; save the key and Solve again.

What this is not: encryption at rest. The store is a 0600 file under the
user's own directory (unreadable by isolated node code), the same posture as
the LLM key today; an encrypted store remains the deployment-tier remainder.
A published dataflow carries key *names*, so whoever installs it saves their
own key under the same name. The shared guest account, when authentication is
off, shares one key store with every other guest, and the section says so.

The one path the gate cannot cover is a person typing a key into a node's
code. The code editor watches for that shape (memo dev/117) and shows a
non-blocking hint naming the line, with the same **Save as connection key**
route the Solve cards offer; nothing is refused, rewritten or sent — the
finding is a name and a line, and it stays in the browser tab.

**Every executable kind, in waves.** Solve verifies every node kind the
sandbox can run — the Python kinds and JavaScript computation. A batch runs the
plan the way Play would: in topological waves, roots first, each wave's nodes
in parallel. A wave's verified content is written at the wave boundary, so the
next wave generates and executes against the upstream code that actually ran,
and a downstream correction is told what its upstreams produced (`upstreamOutputs`,
the output data type). An upstream that passed earlier in the batch is not run
again: its recorded output stands in, and if that artifact has meanwhile
vanished the slice runs whole once, silently, before the result counts. A
process that dies between waves keeps every persisted wave; Retry continues.

**What cannot run is never called verified.** Whether the sandbox can run a
node kind is read from its template (memo dev/119, DEC-076): a code editor
(`hasCode`), a `python` or `javascript` engine, and no `backendHandler`. That
covers every built-in Python and JavaScript kind and every package template
that declares the same — nothing to register, no list to keep. A template with
no code — Vega and Autark specs, merge nodes, data pools, the spatial join
(its work happens in the browser or through its own backend endpoint) — is
written as before and labeled honestly: *written — no code to run; renders in
the browser or its own service* on the pill, `not executable` in a review's
attempt trail, and the Node Builder's proposal card reads *Solve writes it, the
browser or its own service renders it* instead of promising a run. The same
words appear when you ask **Solve this node** or validate-node on such a node:
nothing runs, nothing is claimed. Without a reachable template roster (the
end-to-end runner over a raw file) the legacy name tables answer instead, as
the offline fallback.

**Bounds.** A batch has a time budget (`CURIO_SOLVE_BATCH_DEADLINE`, seconds,
default 45 minutes), checked at every wave boundary and before every node.
What it did not reach stays *pending* with the reason, the Solve card names it
once, and Retry continues from there. A node whose upstream slice exceeds the
validation bound (25 nodes) or contains a cycle is *skipped* with the bound
named — a bound on validation, never a failure of the content — and no
correction is spent on it. The stale-run marker (15 minutes) is measured from
the last completed wave. `verify: false` on the Solve request keeps the legacy
write for every kind. The per-node execution timeout is
`CURIO_VALIDATION_EXEC_TIMEOUT` (seconds, default 300).

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
| API key | **One per account**, held against the provider you saved it under. The saved-key markers and *Remove saved key* appear only on that provider's tab; on any other tab the field is empty and required, and saving there replaces the stored key rather than adding a second one. Leave blank to keep it while you are on its own tab. |
| Model | Which model answers. **Fetch models** asks the endpoint above what it serves and turns this into a dropdown; when it cannot be asked, Curio replays what that endpoint last reported. Leave blank to inherit the deployment's. |
| HuggingFace token | Not for agents: it unlocks *gated* models in the Street Vision node. It sits here because it is the same kind of setting, a model credential you hold per account. Public models need none. |

### Choosing the model

The **Fetch models** button under the Model field asks the configured endpoint
what it serves (`POST /api/agents/provider-models`, which the panel calls with
the base URL and key currently *on screen* rather than the saved ones — you are
usually choosing a model for an endpoint you have not saved yet). What comes
back becomes a dropdown.

It is a convenience, not a gate. A model you saved earlier stays selected and is
marked *(not listed)* if the endpoint stops offering it, rather than
disappearing from the control that claims to show it, and the field is free text
until you press the button.

**The answer is hybrid, and both halves come from the API** (the decision
recorded for [#241]). Two sources fill the dropdown:

| Source | What it is |
|---|---|
| *From this endpoint* | What the endpoint reported just now. OpenAI-compatible endpoints, Anthropic, and Gemini are all asked; for Gemini only models supporting `generateContent` are offered, since an embedding model saved here would fail at the first agent run. |
| *Last reported by this endpoint (on <date>)* | What it reported the last time it could be asked. Recorded per account on every success (`agents/model_catalog.py`) and replayed when a live listing is impossible - no key pasted yet, offline, or a key without the scope to list. |

**Nothing here is maintained by hand.** An earlier cut shipped a literal table
of model ids per provider. That drifts the moment a provider ships or retires a
model, nobody notices because stale entries still look plausible, and it could
say nothing at all about a custom endpoint - there is no such thing as a model
somebody's Ollama probably serves. A recording of what an endpoint said about
itself has none of those problems, and it covers custom endpoints for free:
fetch once against your own server and it is remembered like any other.

Suggestions are never an allowlist. Nothing rejects a model missing from them,
the box stays free text, a live listing always wins, and a model you type by
hand is always accepted. A replay is labelled with the date it was true, because
presenting a recording as the present tense is how you save a model the endpoint
no longer has - which surfaces much later as a failed agent run, not here.

Two consequences worth stating. A **brand-new account with no key has nothing to
suggest**, and the panel says so rather than guessing; the deployment's own
configured model still shows as the placeholder. And Curio **does not send a
placeholder key** - every provider authenticates its models endpoint, so with no
key the replay answers immediately instead of waiting out a socket timeout for a
foregone 401.

An earlier version of this panel reported Anthropic and Gemini as
`listable: false` and said *"This provider does not publish a model list"*. That
was untrue - nobody had asked them - and it is what #241 was filed about.

[#241]: https://github.com/urban-toolkit/curio/issues/241

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

One adjacent setting is **max output tokens**, and it is not a quota: it is
passed to the provider as `max_tokens` on every completion, so it shapes one
reply rather than rationing a day's worth. It is a deployment constant, the same
for every run.

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

## 7. Measuring the agents against the shipped examples

Curio's tests prove two things that sound like the same thing and are not: that
a *saved* dataflow still loads, renders and runs, and that the agent runtime
does what its contract says. Neither asks whether a **model** can build one of
those dataflows when a person describes it. That question has its own harness
(memo `dev/121`).

Every shipped example — the eleven curated ones and the twenty legacy
structural dataflows — has a **prompt fixture** under
[`docs/examples/prompts/`](examples/prompts/README.md): a reviewed
natural-language prompt paired with the example's digest, its declared datasets
and packages, its normalized expected graph, node intents, an execution mode, a
capability tier and scoring thresholds. During an evaluation the agent receives
the prompt and nothing else — never the example JSON, the node ids, the code or
the expected graph, which a test enforces.

The run itself is the ordinary product path: an empty project, the Dataflow
Builder attached, one message, the plan's review card, Apply, then Solve. What
lands on disk is compared **semantically** — canonical template ids and their
roles, topology with edge kinds and merge slots, the declared dataset and
package references, absence of invented templates/packages/datasets/paths/URLs,
node intents, and Solve's own verdicts. Regenerated ids, layout, formatting and
behaviourally equivalent code are ignored by construction; a graph built in a
different order scores the same.

Three things the harness will not do:

- **It does not weaken an expectation to pass.** A construct the agent contract
  cannot express is reported as a named *capability gap*. Eight fixtures needed
  one — a brushable chart that highlights its map is a bidirectional link, and
  the plan contract carried no edge kind, so no plan could build those edges.
  Their expected graphs kept them, and when the contract learned edge kinds
  (memo `dev/125`) the same eight began scoring with **no fixture edited**.
  That is the whole point of naming a gap instead of lowering a bar.
- **It does not gate anything on a model.** A live-model run writes an
  evaluation report, opt-in and never in CI. Nothing in Curio passes or fails
  because of those numbers.
- **It does not let an agent grade an agent.** The comparison is deterministic
  code. The Generated Content Evaluator remains advisory and has no authority
  here, and a candidate never judges itself.

### Evaluation mode

The place to ask it is **AI Settings → Evaluation mode**, because that is where
the model is chosen. Pick an example, read the prompt that will be sent, and
run it.

What happens is the ordinary product, not a test harness: the run creates a
**project of its own** (yours is untouched), installs and attaches the Dataflow
Builder through the normal install flow with the agents it requires, sends the
prompt through the normal runtime with **your** configured model, applies the
plan through the same endpoint the Apply button uses, and solves. Then the
dataflow it built is compared with the saved example — server-side, so the
reference never reaches the model. The panel names each step while it happens
(*waiting for the model*, *solving the nodes*), and the run keeps going if you
close the panel.

Applying a plan without you clicking is an automated approval, so it is granted
narrowly rather than quietly: only inside the project that run created, only
for the plan and the installs the example requires, refused for anything a
person should decide, and recorded per apply. Your normal review policy is
unchanged everywhere else.

When it finishes you get the overall accuracy, a score per category, the
failure categories, and a link to **the project it built** — the graph is how
you understand the number. An unmeasured category says so rather than reading
as zero. The link appears only once the run is over, because the graph is
written when the plan is applied and a project opened earlier would show an
empty canvas.

Open it and the dataflow is on the canvas, and the Dataflow Builder's own chat
there carries the whole run: the prompt, the plan it proposed, what was
applied, what Solve verified, and the report. That transcript stays with the
project. The graph an evaluation built is protected from being erased by a
canvas that was open before the run finished, and so is every other project's:
a save that would delete a node, a connection or a node's code that the browser
never saw is refused, and says what would be lost and to reload (memo
`dev/124`). Editing is otherwise yours to do.

A model configured by the launcher counts: if the deployment was started with
`--llm-provider`, `--llm-base-url` and `--llm-model`, the panel says so and runs
against it. With nothing configured anywhere it says so and offers no Run.

**Approving a prompt happens here too.** Each prompt was drafted by a model and
needs a person's approval before it can be exported; the panel that shows you
the prompt is where you record that, and where you can withdraw it.

```bash
# the deterministic tiers (offline, no stack, seconds)
pytest utk_curio/backend/tests/test_agents/test_example_fixtures.py \
       utk_curio/backend/tests/test_agents/test_example_reconstruction.py \
       utk_curio/backend/tests/test_agents/test_evaluation_service.py

# what the fixtures say
python -m utk_curio.tools.agent_eval list

# the same evaluation against a REMOTE stack, from a terminal
export CURIO_EVAL_LIVE=1
python -m utk_curio.tools.agent_eval run --token "$CURIO_EVAL_TOKEN" --tier T0
```

A run started from the panel is recorded per account under
`.curio/users/<key>/agents/evaluation/`, with the fixture, the provider and
model, the prompt and agent digests, the generated project id, the phases it
went through, its latency and token usage, the comparison and the score — and
never a key. The command-line runner writes its own report to
`.curio/eval/<runId>/` as `report.json` (the machine record: provider,
model, prompt and instruction digests, attempts, latency, token usage,
redacted transcripts, the generated dataflow, the diff, the score
and its failure categories) and `report.md` (the same thing as a table). No USD
figure is computed unless you supply a rate, for the same reason the usage
ledger computes none: Curio has no price table and would have to invent the
numbers.

### Training a model on these examples

The fixtures are also how you can make a model *better* at planning Curio
dataflows, in **AI Settings → Model training** (memo `dev/122`).

**It tells you first whether your endpoint can do this at all.** Nobody
maintains a list of which providers support fine-tuning — that list would drift
the moment one shipped or retired the feature, exactly as a list of model ids
would. Curio asks the endpoint you configured. So the section reads
*Unavailable* with a different sentence for each real reason: an Anthropic key
(its API publishes Messages, Batches, Token Counting, Models, Files and Skills,
and no tuning endpoint), a local Ollama or LM Studio (chat routes only), or a
key without the scope to list tuning jobs — which says the endpoint may still
support tuning, because the fix there is a different key. When the endpoint
cannot be asked at all, the last answer it gave is replayed with the date it
was true.

**What gets sent, and what does not.** Only fixtures that are on the `train`
split *and* approved by a person. Each row is one training example: the system
turn a real run carries, the fixture's prompt, and the plan block the runtime's
own parser accepts — so the model is taught the shape the product actually
takes, and an example whose graph the plan contract cannot express is excluded
with that as its reason rather than taught in a weakened form. (The eight with
a bidirectional link were that case until `dev/125`; the rule did not change,
the contract did, so the same rule now includes them.) Every row is scrubbed and then re-checked; anything
still resembling a credential stops the upload rather than being sent redacted.

Before anything moves you see the row count, the byte count, the examples by
name, their licences, and the **host** it would go to — the endpoint you
configured, never a third party Curio chose. A row carries the prompt, the
expected graph shape and the plan text, all authored in this repository, plus
dataset and package **identifiers**: no dataset row, column, geometry or file
is included, which is why the datasets' own licences are not implicated.
Consent is a tick plus the digest of that exact set, and it is recorded before
the first byte leaves.

**The provider owns the job.** A fine-tune takes minutes to hours, so Curio
holds its id and asks the endpoint when you look; the status you see always
carries the time it was read. Closing the panel or restarting the server loses
nothing. Cancel asks the endpoint and reports what it says. Trained tokens are
shown as the provider reported them, and no dollar figure appears unless you
supply a rate — the same reason the usage ledger computes none.

**A trained model cannot be switched on until you have evaluated it.** Not
because Curio judges it: there is no pass mark here, and inventing one would be
Curio deciding for you. The rule is narrower and enforceable — an evaluation of
**that exact model**, on the **held-out** examples it never trained on, whose
fixture digests still match the corpus. Four refusals, each naming what to fix.
The scores come from the same deterministic comparator as everything else in
part 7, so no model and no agent is anywhere in the approval path, and a
candidate never judges itself. Switching over records the model you were using,
so going back is one click.

```bash
export CURIO_EVAL_LIVE=1
python -m utk_curio.tools.agent_eval run \
    --model ft:your-base:curio-plans:abc --gate-for train-20260909T161200Z-a1b2
```

Two honest limits. The training data is Curio's own examples, so this teaches
the *shape* of a Curio dataflow, not your domain — training on your own
dataflows needs a consent surface that does not exist yet. And nothing here
trains a model locally: if your endpoint cannot fine-tune, Curio cannot do it
for you.

---

## Operator notes

### An unconfigured install has no provider

Curio ships with **no default LLM endpoint**. This is deliberate: a built-in
default would mean an unconfigured instance silently sending user data to a
third party nobody chose. An unconfigured install reaches a clear "no provider
configured" error instead, and every agent surface that is blocked for want of
one links to **AI Settings**.

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
- [`docs/examples/prompts/README.md`](examples/prompts/README.md): the prompt fixtures behind [part 7](#7-measuring-the-agents-against-the-shipped-examples), and how to write one.
