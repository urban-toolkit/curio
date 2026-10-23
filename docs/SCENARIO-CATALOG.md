# Scenario Catalog

The Scenario Catalog lists the **scenarios** saved in your projects, across every project you have. A scenario is a named selection of a dataflow's nodes, or the whole dataflow, made on the canvas (see [Scenarios](USAGE.md#scenarios)). The catalog shows what each one reads, what it changes and what it produces, with the results its project saved.

Curio has six catalogs: the [Node Catalog](NODE-CATALOG.md) holds the nodes you drop on the canvas, the [Data Catalog](DATA-CATALOG.md) the datasets they read, the [Model Catalog](MODEL-CATALOG.md) the models they run, the [Agent Catalog](AGENT-CATALOG.md) the assistants you attach to them, the [Discovery Catalog](DISCOVERY-CATALOG.md) the portals, storage, services and models you take datasets and models from, and the Scenario Catalog the scenarios saved in your projects.

This guide is in four parts:

- [1. What is the Scenario Catalog?](#1-what-is-the-scenario-catalog): scenarios, and where they are kept.
- [2. Surfaces and workflows](#2-surfaces-and-workflows): the page, the canvas drawer, the action matrix, and walkthroughs.
- [3. Reading a scenario](#3-reading-a-scenario): its fixed context, levers and outcomes, and their saved results.
- [4. Using a scenario in a dataflow](#4-using-a-scenario-in-a-dataflow): dragging one in, what arrives, and when a drop is refused.
- [5. Importing, publishing, and sharing](#5-importing-publishing-and-sharing): copies and shared dataflows.

---

## 1. What is the Scenario Catalog?

### Concept

A scenario splits its dataflow into three parts:

- **Fixed context:** the nodes outside the scenario that it reads, through an edge into it or through a Parameter node's tag its code uses.
- **Levers:** the nodes in the scenario, which is what an alternative changes.
- **Outcomes:** the outputs of the scenario's last nodes, which is what gets compared.

Scenarios live in their projects. The catalog lists them; it keeps no copy. Editing a project changes its scenarios in the catalog, and deleting a project removes them.

### What ships with Curio

No scenario ships with Curio. The catalog lists the scenarios in your own projects and in the examples seeded into your account.

### Storage layers

| Layer | On disk | Written by |
|---|---|---|
| **A project's scenarios** | `dataflow.scenarios` in the project's saved dataflow | **Save selection as scenario**, **Save dataflow as scenario**, **Duplicate as scenario**, a scenario dragged in from the catalog, and the canvas drawer's **In project** tab, saved with the dataflow. |
| **Their saved results** | Your Data Catalog, as the project's saved outputs | Running the project: a scenario's fixed context and outcomes save their outputs. A scenario dragged into a dataflow brings copies of them, saved as that dataflow's own. |

---

## 2. Surfaces and workflows

- **The `/catalog/scenarios` page** lists every scenario in your projects. Reach it from the **Scenario Catalog** tab. Search with **Search scenarios**, sort by **Recently edited**, **Name** or **Project**, and filter by **By project** or **By origin** (**Your dataflows** or **Examples**) in the left rail. Click a card to describe it in the right-hand drawer.
- **The Scenario Catalog drawer**, on the canvas. Open it from the **Scenario** button in the top bar. It has two tabs:
  - **Browse all** lists every scenario in your projects, under a heading for each project: its name, and how many of the scenarios listed come from it. The sort orders the groups by their first card, and the cards within each group. Drag a card onto the canvas to bring the scenario into the open dataflow.
  - **In project** lists the open dataflow's own scenarios, saved or not, and the tab shows how many there are. Each card runs, collapses or expands its scenario, adds or removes the nodes selected on the canvas, or deletes it, and its details rename, recolor and describe it (see [Scenarios](USAGE.md#scenarios)).

Each card shows a square of the scenario's color before its name, then its project, how many nodes it holds, its description, and its project's graph; in the **In project** tab the graph marks the scenario's nodes. On the `/catalog/scenarios` page, the strip at the top is the same on every card.

Agents find your scenarios too: asked for a scenario of another project, the [Dataflow Builder](AGENT-CATALOG.md#widgets-and-scenarios) names it and its project for you to drag in from **Browse all**, and an agent that reads your dataflow tells which project a scenario you dragged in came from.

### Action matrix

| Action | Where | What it changes | What you see |
|---|---|---|---|
| **View details** | A card, the drawer, or the canvas drawer | Nothing | The scenario's fixed context, levers and outcomes, with their saved results. In the **In project** tab, the nodes as the canvas holds them. |
| **Open source project** | A card, the drawer, the canvas drawer's **Browse all** tab, or the details | Nothing | The project the scenario lives in, on the canvas. From an open dataflow with unsaved changes, Curio asks first. |
| **Drag onto the canvas** | A card in the canvas drawer's **Browse all** tab | The open dataflow: it gains a copy of the scenario, and the packages its nodes need | The scenario, collapsed where you dropped it, with its fixed context beside it and its saved results. See [4. Using a scenario in a dataflow](#4-using-a-scenario-in-a-dataflow). |
| **Run scenario**, **Collapse** or **Expand**, **Add selected**, **Remove selected**, **Delete** | A card in the canvas drawer's **In project** tab | The open dataflow's scenario | Its levers run, its box closes or opens, its nodes change, or it is gone and its nodes stay. |
| **Rename, recolor, describe** | The details of a card in the **In project** tab | The open dataflow's scenario | Its new name, color or description, on its card and on the canvas. |

### Workflows

**I want to find a study I made.** Open the **Scenario Catalog** tab and search for the scenario's name, its description or its project's name.

**I want to change a scenario.** Click **Open source project**, change its nodes on the canvas, and save the dataflow. The catalog shows the change.

**I want to know what a scenario produced.** Click **View details**. Each outcome lists the output its project saved, by name, format and size. An outcome with **No saved output** has not run since the scenario was defined.

**I want to compare a scenario from another project with my own work.** Open the dataflow, click **Scenario** in the top bar, and drag the scenario's card onto the canvas. It arrives with its results. Double-click its box to see its nodes, and wire your own nodes into it where its fixed context was.

---

## 3. Reading a scenario

A scenario's details show its name, color, project and description, and its project's graph with the scenario's nodes marked in its color and its fixed context outlined. Then three lists:

| List | Holds | Each node shows |
|---|---|---|
| **Fixed context** | The nodes outside the scenario that it reads | Its name, the output its project saved, and for a Parameter node, its value |
| **Levers** | The nodes in the scenario | Its name, and the output its project saved |
| **Outcomes** | The scenario's last nodes | Its name, and the output its project saved |

A chart or a Data Pool saves nothing itself, so its saved result is the output of the node feeding it.

---

## 4. Using a scenario in a dataflow

A scenario dragged from the canvas drawer onto the canvas arrives as a copy, and editing either one leaves the other as it is:

- **Its levers** are copied with new ids. Each copy names the node it was copied from.
- **Its fixed context** arrives as data. Each node it reads becomes a **Data Loading** node that reads a copy of the output that node saved in its project, wired where the context was. The copy is this dataflow's own: running the source project again changes its own output, not the copy. A Parameter node of its context is copied with its value.
- **A context node with no saved output** runs first, on the server and in the scenario's project, which saves its output there; the drop then brings it. While it runs, a notice names it, such as "Running Buildings in Chicago Loop shadow with towers removed or edited for Existing". When the run fails, the message says why and nothing is added.
- **Its outcomes** show the results its project saved, before anything runs.
- **Packages** its nodes use are added to the dataflow, as **Add** in the Node Catalog adds one.
- **The scenario** is collapsed where you dropped it, in its own color, and keeps its name and description.

A second scenario of the same project, dragged into the same dataflow, reads the fixed context the first one brought, so the two share it as they did in their project.

To use your own data instead, double-click the box, delete the Data Loading node, and connect your node to the lever it fed. **Run scenario** then runs your node first.

A drop is refused, and nothing is added, when:

- a node of its fixed context has no saved output and cannot run on the server: only the browser runs it (an Autark compute node, for one), you are a guest on a hosted Curio, or Curio runs with `--no-project`. Run the scenario in its project and save it, then drag it again;
- its nodes need a package, a dataset or a model your account does not have, or a package your account cannot add; the message names it;
- it brings a Parameter node whose name the dataflow already uses: rename yours, then drag it again.

---

## 5. Importing, publishing, and sharing

Scenarios are not imported or published on their own: they travel with their dataflow. **Duplicate** on a project's card makes a copy whose scenarios stay as they are at that moment, while the original's go on changing; the catalog lists both. A dataflow someone shares with you lists its scenarios in your catalog once you save it to your projects with **File → Save dataflow**.

---

## See also

- [`docs/USAGE.md`](USAGE.md#scenarios): making scenarios on the canvas, the **In project** tab, and collapsing a scenario.
- [`docs/DATA-CATALOG.md`](DATA-CATALOG.md): where a project's saved outputs land.
- [`docs/ARCHITECTURE.md`](ARCHITECTURE.md#scenario-catalog): how the catalog reads projects, and its routes.
