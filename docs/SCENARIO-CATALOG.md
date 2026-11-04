# Scenario Catalog

The Scenario Catalog lists the **scenarios** saved in your projects, across every project you have. A scenario is a named selection of a dataflow's nodes, made on the canvas (see [Scenarios](USAGE.md#scenarios)). The catalog shows what each one reads, what it changes and what it produces, with the results its project saved.

Curio has seven catalogs: the [Node Catalog](NODE-CATALOG.md) holds the nodes you drop on the canvas, the [Data Catalog](DATA-CATALOG.md) the datasets they read, the [Model Catalog](MODEL-CATALOG.md) the models they run, the [Agent Catalog](AGENT-CATALOG.md) the assistants you attach to them, the [Skill Catalog](SKILL-CATALOG.md) the skills those assistants read, the [Discovery Catalog](DISCOVERY-CATALOG.md) the portals, storage, services and models you take datasets and models from, and the Scenario Catalog the scenarios saved in your projects.

This guide is in five parts:

- [1. What is the Scenario Catalog?](#1-what-is-the-scenario-catalog): scenarios, scenario sets, and where they are kept.
- [2. Surfaces and workflows](#2-surfaces-and-workflows): the page, the canvas drawer, the action matrix, and walkthroughs.
- [3. Reading a scenario](#3-reading-a-scenario): its shared context, its scenario-specific nodes and its shared outcomes, and their saved results.
- [4. Using a scenario in a dataflow](#4-using-a-scenario-in-a-dataflow): dragging scenarios in, what arrives, and when a drop is refused.
- [5. Importing, publishing, and sharing](#5-importing-publishing-and-sharing): copies and shared dataflows.

---

## 1. What is the Scenario Catalog?

### Concept

A scenario splits its dataflow into three parts:

- **Scenario-specific nodes:** the nodes unique to it, drawn in its box. This is what an alternative changes.
- **Shared context:** every node upstream of it, outside every box, that it uses: the data and settings it takes as given.
- **Shared outcomes:** every node downstream of it, outside every box, that it feeds: the maps, charts and tables the comparison is read on.

Every scenario belongs to one **scenario set**: the scenarios that answer one question, compared on the same shared context and shared outcomes. Scenarios of different sets never mix. A node of a set's shared context or shared outcomes can belong to some of its scenarios and not others: in the Lower Manhattan park shade example, only the two edited scenarios read *Buildings around parks*, and each change map compares *Existing* with one of them. On the canvas, such a node carries a row of circles under it, one per scenario of its set, filled where that scenario uses it.

Curio finds a scenario's shared context and shared outcomes by following the edges up and down from its nodes, never into another scenario's box and never along an interaction edge. You confirm them when you define the scenario, and change them later (see [Defining a scenario](#defining-a-scenario)); a scenario keeps what you confirmed.

On the canvas, each set is outlined under its name, **Scenario set:** and the set's name. Its shared context and shared outcomes are framed in gray, and each collapses into one box of cards, as a scenario does; the set keeps them collapsed.

Scenarios live in their projects. The catalog lists them; it keeps no copy. Editing a project changes its scenarios in the catalog, and deleting a project removes them.

### Defining a scenario

Choose **View → Define scenario**, or **Define scenario** at the top of the drawer's **In project** tab. Define scenario opens in a drawer at the side of the canvas, where the nodes stay selectable, in three steps:

1. **Scenario-specific nodes:** select on the canvas the nodes unique to the scenario (click one, or Shift and drag a box) and click **+ Add selected node**; **×** takes one out. Nodes selected when the drawer opens are listed already, and nodes already in a scenario are left out. The three lists of the drawer work alike.
2. **Shared context & outcomes:** Curio follows the edges from them and lists the shared context and the shared outcomes, and the canvas marks them. Confirm them, remove a node with **×**, or select one on the canvas and click **+ Add selected node**. When the set the scenario goes in has scenarios already, each list marks its nodes **Already in the set** or **New to the set**.
3. **Name & set:** name the scenario, pick its color, and name a new scenario set, named after the dataflow unless you name it, or pick one of this dataflow's. **Save scenario** writes it; nothing is written before. No two scenarios of a set share a name: a name another scenario of the set has is flagged as you type, and the scenario cannot be saved with it.

A drawer opened meanwhile, such as Provenance, API Settings, the Monitor or a catalog, opens over Define scenario, and closing it brings Define scenario back with what you picked.

A saved scenario is changed with **Edit scenario** on its card in the drawer's **In project** tab: Define scenario opens on it, with its nodes, its shared context and shared outcomes, and its name, color and set filled in. Change any step; **Save** changes the scenario in place from step 2 on. A set its last scenario leaves is removed.

A set is renamed with the pencil beside its name in the **In project** tab. A name another set of the dataflow has is refused until you change it.

### What ships with Curio

No scenario ships with Curio. The catalog lists the scenarios in your own projects and in the examples seeded into your account.

### Storage layers

| Layer | On disk | Written by |
|---|---|---|
| **A project's scenarios and sets** | The project's saved dataflow: each scenario with its scenario-specific nodes, its set, its shared context and its shared outcomes, and each set with its name | **Define scenario**, **Duplicate scenario**, a scenario dragged in from the catalog, and the canvas drawer's **In project** tab, saved with the dataflow. |
| **Their saved results** | Your Data Catalog, as the project's saved outputs | Running the project: the nodes of a scenario's shared context that feed it, its own last nodes (those whose output nothing else in it reads, or a node outside it reads) and its shared outcomes save their outputs. A scenario dragged into a dataflow brings copies of them, saved as that dataflow's own. |

---

## 2. Surfaces and workflows

- **The `/catalog/scenarios` page** lists every scenario in your projects. Reach it from **Scenario Catalog** in the top bar. Search with **Search scenarios**, sort by **Recently edited**, **Name** or **Project**, and filter by **By project** or **By origin** (**Your dataflows** or **Examples**) in the left rail. Click a card to describe it in the right-hand drawer.
- **The Scenario Catalog drawer**, on the canvas. Open it from the **Scenario** button in the top bar. It has two tabs:
  - **Browse all** lists every scenario in your projects, in a panel for each scenario set, headed by its name, how many of the scenarios listed are in it, and **Open source project**, with its scenarios' cards beneath. The sort orders the groups by their first card, and the cards within each group. Drag a card onto the canvas to bring its scenario into the open dataflow.
  - **In project** lists the open dataflow's own scenarios in a panel for each scenario set, headed by its name, how many scenarios it holds and a pencil that renames the set, and the tab shows how many there are. On top is **Define scenario**. Each card offers **Run scenario**, **Edit scenario**, which opens Define scenario on it, **Duplicate scenario** and **Delete**, which asks first, and its details rename, recolor and describe it (see [Scenarios](USAGE.md#scenarios)).

Each card shows a square of the scenario's color before its name, its project and how many nodes it has, then its description, and its project's graph; in the **In project** tab the graph marks the scenario's nodes. On the `/catalog/scenarios` page, the strip at the top is the same on every card.

Agents find your scenarios too: asked for a scenario of another project, the [Dataflow Builder](AGENT-CATALOG.md#widgets-and-scenarios) names it and its project for you to drag in from **Browse all**, and an agent that reads your dataflow tells which project a scenario you dragged in came from.

### Action matrix

| Action | Where | What it changes | What you see |
|---|---|---|---|
| **View details** | A card, the drawer, or the canvas drawer | Nothing | The scenario's shared context, its scenario-specific nodes and its shared outcomes, with their saved results. In the **In project** tab, the nodes as the canvas holds them. |
| **Open source project** | A card or the drawer on the `/catalog/scenarios` page, a set's heading in the canvas drawer's **Browse all** tab, or the details | Nothing | The project the scenario lives in, on the canvas. From an open dataflow with unsaved changes, Curio asks first. |
| **Drag onto the canvas** | A card in the canvas drawer's **Browse all** tab | The open dataflow: the scenario joins its set's copy, which the first scenario of the set dragged in makes, and the dataflow gains the packages its nodes need | The scenario in its set, collapsed where you dropped it, with its context, each shared outcome once every scenario it reads is in, and their saved results. See [4. Using a scenario in a dataflow](#4-using-a-scenario-in-a-dataflow). |
| **Run scenario**, **Edit scenario**, **Duplicate scenario**, **Delete** | A card in the canvas drawer's **In project** tab | The open dataflow's scenario | Its nodes run; Define scenario opens on it; its nodes are copied into a new scenario of its set, which Define scenario opens on at **Name & set**; or, once you confirm, it is gone and its nodes stay. |
| **Rename, recolor, describe** | The details of a card in the **In project** tab | The open dataflow's scenario | Its new name, color or description, on its card and on the canvas. |
| **Rename a set** | The pencil beside a set's name in the **In project** tab | The open dataflow's scenario set | Its new name, in the tab and on the canvas. |

### Workflows

**I want to find a study I made.** Open the **Scenario Catalog** page and search for the scenario's name, its description or its project's name.

**I want to change a scenario.** Click **Open source project** and change its nodes on the canvas. The catalog shows the change.

**I want to know what a scenario produced.** Click **View details**. Each outcome lists the output its project saved, by name, format and size. An outcome with **No saved output** has not run since the scenario was defined.

**I want to compare a scenario from another project with my own work.** Open the dataflow, click **Scenario** in the top bar, and drag the scenario's card onto the canvas. It arrives with its results. Double-click its box to see its nodes, and wire your own nodes into it in place of its shared context.

---

## 3. Reading a scenario

A scenario's details show its name, color, project, set and description, and its project's graph with the scenario's nodes marked in its color and its shared context outlined. Then three lists:

| List | Holds | Each node shows |
|---|---|---|
| **Shared context** | The nodes upstream of the scenario that it uses, as it keeps them | Its name, and for a node that feeds the scenario, the output its project saved |
| **Scenario-specific nodes** | The nodes in the scenario | Its name, and for one of its last nodes, the output its project saved |
| **Shared outcomes** | The nodes downstream of the scenario that it feeds, as it keeps them | Its name, and the output its project saved |

A chart or a Data Pool saves nothing itself, so its saved result is the output of the node feeding it.

---

## 4. Using a scenario in a dataflow

Scenarios dragged from the canvas drawer onto the canvas arrive as copies, and editing either one leaves the other as it is. Drag a card from **Browse all** to bring its scenario; drag another card of the same set to bring that scenario too.

- **A copy of its set.** The first scenario of a set you drag into a dataflow arrives in a new scenario set, a copy of its own, named as that set is, with a number added when the dataflow has a set of that name already. Each scenario of the same set you drag in after it joins that copy. Rename the copy with the pencil beside its name in the **In project** tab. Each scenario keeps its name, and its color unless a scenario here already wears it.
- **Its scenario-specific nodes** are copied with new ids. Each copy names the node it was copied from. They keep their places relative to one another, their top left where you dropped them.
- **The context it reads** arrives as data, once for the set. Each node feeding it becomes a **Data Loading** node that reads a copy of the output that node saved in its project, wired where the context was. A scenario of the set dragged in later reads the Data Loading nodes already there and brings only the context they lack. The copy is this dataflow's own: running the source project again changes its own output, not the copy.
- **A context node with no saved output** runs first, on the server and in the scenario's project, which saves its output there; the drop then brings it. While it runs, a notice names it, such as "Running Buildings and Season in Chicago Loop shadow with towers removed or edited for 'Existing'". When the run fails, the message says why and nothing is added.
- **Shared outcomes** come once every scenario they read has arrived, with every other input they have: a context node arriving as data, or another outcome that comes. A chart comparing three scenarios comes with the last of the three you drag in.
- **Its results** show what its project saved, before anything runs.
- **Packages** its nodes use are added to the dataflow, as **Add** in the Node Catalog adds one.
- **Everything arrives collapsed:** the scenario's box, and the shared context and shared outcomes of its set's copy. Double-click a box to open it.

A drop is all or nothing: when the scenario cannot come, nothing is added.

To use your own data instead, double-click the shared context's box, delete the Data Loading node, and connect your node to the scenario node it fed. **Run scenario** on the scenario's card then runs your node first.

A drop is refused, and nothing is added, when:

- the dataflow holds that scenario already; the message says so;
- a node feeding it has no saved output and cannot run on the server: only the browser runs it (an Autark compute node, for one), you are a guest on a hosted Curio, or Curio runs with `--no-project`. Run the scenario in its project, then drag it again;
- its nodes need a package, a dataset or a model your account does not have, or a package your account cannot add; the message names it.

---

## 5. Importing, publishing, and sharing

Scenarios are not imported or published on their own: they travel with their dataflow. **Duplicate** on a project's card makes a copy whose scenarios stay as they are at that moment, while the original's go on changing; the catalog lists both. A dataflow someone shares with you lists its scenarios in your catalog once you save it to your projects with **File → Save dataflow**.

---

## See also

- [`docs/USAGE.md`](USAGE.md#scenarios): making scenarios on the canvas, the **In project** tab, and collapsing a scenario.
- [`docs/DATA-CATALOG.md`](DATA-CATALOG.md): where a project's saved outputs land.
- [`docs/ARCHITECTURE.md`](ARCHITECTURE.md#scenario-catalog): how the catalog reads projects, and its routes.
