# Scenario Catalog

The Scenario Catalog lists the **scenarios** saved in your projects, across every project you have. A scenario is a named selection of a dataflow's nodes, or the whole dataflow, made on the canvas (see [Scenarios](USAGE.md#scenarios)). The catalog shows what each one reads, what it changes and what it produces, with the results its project saved.

Curio has six catalogs: the [Node Catalog](NODE-CATALOG.md) holds the nodes you drop on the canvas, the [Data Catalog](DATA-CATALOG.md) the datasets they read, the [Model Catalog](MODEL-CATALOG.md) the models they run, the [Agent Catalog](AGENT-CATALOG.md) the assistants you attach to them, the [Discovery Catalog](DISCOVERY-CATALOG.md) the portals, storage, services and models you take datasets and models from, and the Scenario Catalog the scenarios saved in your projects.

This guide is in four parts:

- [1. What is the Scenario Catalog?](#1-what-is-the-scenario-catalog): scenarios, scenario sets, and where they are kept.
- [2. Surfaces and workflows](#2-surfaces-and-workflows): the page, the canvas drawer, the action matrix, and walkthroughs.
- [3. Reading a scenario](#3-reading-a-scenario): its shared context, its own nodes and its outcomes, and their saved results.
- [4. Using a scenario in a dataflow](#4-using-a-scenario-in-a-dataflow): dragging one in, what arrives, and when a drop is refused.
- [5. Importing, publishing, and sharing](#5-importing-publishing-and-sharing): copies and shared dataflows.

---

## 1. What is the Scenario Catalog?

### Concept

A scenario splits its dataflow into three parts:

- **Its own nodes:** the nodes unique to it, drawn in its box. This is what an alternative changes.
- **Shared context:** every node upstream of it, outside every box, that it uses: the data and settings the comparison holds fixed.
- **Shared outcomes:** every node downstream of it, outside every box, that it feeds: the maps, charts and tables the comparison is read on.

Every scenario belongs to one **scenario set**: the scenarios that answer one question, compared on the same shared context and outcomes. Scenarios of different sets never mix. A context or outcome node can belong to some of a set's scenarios and not others: in the Lower Manhattan park shade example, only the two edited scenarios read *Buildings around parks*, and each change map compares *Existing* with one of them. On the canvas, such a node carries a row of circles under it, one per scenario of its set, filled where that scenario uses it.

Curio infers a scenario's context and outcomes by following the edges up and down from its nodes, never into another scenario's box and never along an Interaction link. You finalize them when you define the scenario, and edit them later (see [Defining a scenario](#defining-a-scenario)); a scenario keeps what you finalized.

On the canvas, each set's shared context and shared outcomes are framed in gray under their name, and each collapses into one box of cards, as a scenario does; the set keeps them collapsed.

Scenarios live in their projects. The catalog lists them; it keeps no copy. Editing a project changes its scenarios in the catalog, and deleting a project removes them.

### Defining a scenario

Choose **View → Define scenario**, or **Define scenario** in the drawer's **In project** tab. A panel opens beside the canvas, in three steps:

1. **Scenario-specific nodes:** select on the canvas the nodes unique to the scenario (click one, or Shift and drag a box) and click **+ Add selected node**; **×** takes one out. Nodes selected when the panel opens are listed already, and nodes already in a scenario are left out. The three lists of the panel work alike.
2. **Shared context & outcomes:** Curio follows the edges from them and lists the shared context and the outcomes, and the canvas marks them. Confirm them, remove a node with **×**, or select one on the canvas and click **+ Add selected node**. Joining a set that has scenarios already, each list says what the set has and what is new to it.
3. **Name & set:** name the scenario, pick its color, and put it in one of this dataflow's scenario sets or create a new one, named after the dataflow unless you name it. **Save scenario** writes it; nothing is written before. No two scenarios of a set share a name: a name another scenario of the set has is flagged as you type, and the scenario cannot be saved with it.

On the canvas, each scenario's frame shows its set's name before its own.

A saved scenario is changed with **Edit scenario** on its card in the drawer's **In project** tab: the define panel opens on it, with its nodes, its shared context and outcomes, and its name, color and set filled in. Change any step; **Save** changes the scenario in place from step 2 on. A set its last scenario leaves is removed. A dataflow from before scenario sets is read with its scenarios grouped by the nodes they share and their lists inferred, the way its next save keeps them.

### What ships with Curio

No scenario ships with Curio. The catalog lists the scenarios in your own projects and in the examples seeded into your account.

### Storage layers

| Layer | On disk | Written by |
|---|---|---|
| **A project's scenarios and sets** | `dataflow.scenarios` and `dataflow.scenarioSets` in the project's saved dataflow; each scenario names its `set` and keeps its `context` and `outcomes` | **Define scenario**, **Save dataflow as scenario**, **Duplicate scenario**, a scenario dragged in from the catalog, and the canvas drawer's **In project** tab, saved with the dataflow. |
| **Their saved results** | Your Data Catalog, as the project's saved outputs | Running the project: a scenario's fixed context and outcomes save their outputs. A scenario dragged into a dataflow brings copies of them, saved as that dataflow's own. |

---

## 2. Surfaces and workflows

- **The `/catalog/scenarios` page** lists every scenario in your projects. Reach it from the **Scenario Catalog** tab. Search with **Search scenarios**, sort by **Recently edited**, **Name** or **Project**, and filter by **By project** or **By origin** (**Your dataflows** or **Examples**) in the left rail. Click a card to describe it in the right-hand drawer.
- **The Scenario Catalog drawer**, on the canvas. Open it from the **Scenario** button in the top bar. It has two tabs:
  - **Browse all** lists every scenario in your projects, in a panel for each scenario set, headed by its name, how many of the scenarios listed are in it, and **Open source project**; its scenarios hang beneath it. The sort orders the groups by their first card, and the cards within each group. Drag a card onto the canvas to bring the scenario into the open dataflow.
  - **In project** lists the open dataflow's own scenarios, saved or not, under their sets, and the tab shows how many there are. Each card runs its scenario, opens it in the define panel with **Edit scenario**, copies it with **Duplicate scenario**, or deletes it (a scenario collapses and expands on the canvas), and its details rename, recolor and describe it (see [Scenarios](USAGE.md#scenarios)).

Each card shows a square of the scenario's color before its name, then its description, and its project's graph; in the **In project** tab the graph marks the scenario's nodes. On the `/catalog/scenarios` page, the strip at the top is the same on every card.

Agents find your scenarios too: asked for a scenario of another project, the [Dataflow Builder](AGENT-CATALOG.md#widgets-and-scenarios) names it and its project for you to drag in from **Browse all**, and an agent that reads your dataflow tells which project a scenario you dragged in came from.

### Action matrix

| Action | Where | What it changes | What you see |
|---|---|---|---|
| **View details** | A card, the drawer, or the canvas drawer | Nothing | The scenario's shared context, its own nodes and its outcomes, with their saved results. In the **In project** tab, the nodes as the canvas holds them. |
| **Open source project** | A card or the drawer on the `/catalog/scenarios` page, a set's heading in the canvas drawer's **Browse all** tab, or the details | Nothing | The project the scenario lives in, on the canvas. From an open dataflow with unsaved changes, Curio asks first. |
| **Drag onto the canvas** | A card in the canvas drawer's **Browse all** tab | The open dataflow: it gains a copy of the scenario, and the packages its nodes need | The scenario, collapsed where you dropped it, with its fixed context beside it and its saved results. See [4. Using a scenario in a dataflow](#4-using-a-scenario-in-a-dataflow). |
| **Run scenario**, **Edit scenario**, **Duplicate scenario**, **Delete** | A card in the canvas drawer's **In project** tab | The open dataflow's scenario | Its nodes run; the define panel opens on it; its nodes are copied into a new scenario of its set, which the define panel opens on at **Name & set**; or it is gone and its nodes stay. |
| **Rename, recolor, describe** | The details of a card in the **In project** tab | The open dataflow's scenario | Its new name, color or description, on its card and on the canvas. |

### Workflows

**I want to find a study I made.** Open the **Scenario Catalog** tab and search for the scenario's name, its description or its project's name.

**I want to change a scenario.** Click **Open source project**, change its nodes on the canvas, and save the dataflow. The catalog shows the change.

**I want to know what a scenario produced.** Click **View details**. Each outcome lists the output its project saved, by name, format and size. An outcome with **No saved output** has not run since the scenario was defined.

**I want to compare a scenario from another project with my own work.** Open the dataflow, click **Scenario** in the top bar, and drag the scenario's card onto the canvas. It arrives with its results. Double-click its box to see its nodes, and wire your own nodes into it where its fixed context was.

---

## 3. Reading a scenario

A scenario's details show its name, color, project, set and description, and its project's graph with the scenario's nodes marked in its color and its shared context outlined. Then three lists:

| List | Holds | Each node shows |
|---|---|---|
| **Shared context** | The nodes upstream of the scenario that it uses, as it keeps them | Its name, and the output its project saved |
| **Scenario-specific nodes** | The nodes in the scenario | Its name, and the output its project saved |
| **Shared outcomes** | The nodes downstream of the scenario that it feeds, as it keeps them; for a scenario that feeds nothing outside it, its own last nodes | Its name, and the output its project saved |

A chart or a Data Pool saves nothing itself, so its saved result is the output of the node feeding it.

---

## 4. Using a scenario in a dataflow

A scenario dragged from the canvas drawer onto the canvas arrives as a copy, and editing either one leaves the other as it is. A drag brings one scenario, with the nodes that feed it directly; dragging a whole set, with its outcome views, is not there yet.

- **Its own nodes** are copied with new ids. Each copy names the node it was copied from.
- **The context it reads directly** arrives as data. Each node feeding it becomes a **Data Loading** node that reads a copy of the output that node saved in its project, wired where the context was. The copy is this dataflow's own: running the source project again changes its own output, not the copy.
- **A context node with no saved output** runs first, on the server and in the scenario's project, which saves its output there; the drop then brings it. While it runs, a notice names it, such as "Running Buildings and Season in Chicago Loop shadow with towers removed or edited for Existing". When the run fails, the message says why and nothing is added.
- **Its outcomes** show the results its project saved, before anything runs.
- **Packages** its nodes use are added to the dataflow, as **Add** in the Node Catalog adds one.
- **The scenario** is collapsed where you dropped it, in its own color, and keeps its name and description.

A second scenario of the same project, dragged into the same dataflow, reads the context the first one brought, so the two share it as they did in their project.

To use your own data instead, double-click the box, delete the Data Loading node, and connect your node to the scenario node it fed. **Run scenario** then runs your node first.

A drop is refused, and nothing is added, when:

- a node feeding it has no saved output and cannot run on the server: only the browser runs it (an Autark compute node, for one), you are a guest on a hosted Curio, or Curio runs with `--no-project`. Run the scenario in its project and save it, then drag it again;
- its nodes need a package, a dataset or a model your account does not have, or a package your account cannot add; the message names it.

---

## 5. Importing, publishing, and sharing

Scenarios are not imported or published on their own: they travel with their dataflow. **Duplicate** on a project's card makes a copy whose scenarios stay as they are at that moment, while the original's go on changing; the catalog lists both. A dataflow someone shares with you lists its scenarios in your catalog once you save it to your projects with **File → Save dataflow**.

---

## See also

- [`docs/USAGE.md`](USAGE.md#scenarios): making scenarios on the canvas, the **In project** tab, and collapsing a scenario.
- [`docs/DATA-CATALOG.md`](DATA-CATALOG.md): where a project's saved outputs land.
- [`docs/ARCHITECTURE.md`](ARCHITECTURE.md#scenario-catalog): how the catalog reads projects, and its routes.
