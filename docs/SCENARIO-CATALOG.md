# Scenario Catalog

The Scenario Catalog lists the **scenarios** saved in your projects, across every project you have. A scenario is a named selection of a dataflow's nodes, or the whole dataflow, made on the canvas (see [Scenarios](USAGE.md#scenarios)). The catalog shows what each one reads, what it changes and what it produces, with the results its project saved.

Curio has six catalogs: the [Node Catalog](NODE-CATALOG.md) holds the nodes you drop on the canvas, the [Data Catalog](DATA-CATALOG.md) the datasets they read, the [Model Catalog](MODEL-CATALOG.md) the models they run, the [Agent Catalog](AGENT-CATALOG.md) the assistants you attach to them, the [Discovery Catalog](DISCOVERY-CATALOG.md) the portals, storage, services and models you take datasets and models from, and the Scenario Catalog the scenarios saved in your projects.

This guide is in four parts, plus operator notes:

- [1. What is the Scenario Catalog?](#1-what-is-the-scenario-catalog): scenarios, and where they are kept.
- [2. Surfaces and workflows](#2-surfaces-and-workflows): the page, the canvas drawer, the action matrix, and walkthroughs.
- [3. Reading a scenario](#3-reading-a-scenario): its fixed context, levers and outcomes, and their saved results.
- [4. Importing, publishing, and sharing](#4-importing-publishing-and-sharing): copies and shared dataflows.
- [Operator notes](#operator-notes).

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
| **A project's scenarios** | `dataflow.scenarios` in the project's saved dataflow | **Save selection as scenario**, **Save dataflow as scenario**, **Duplicate as scenario** and the Scenarios panel, saved with the dataflow. |
| **Their saved results** | Your Data Catalog, as the project's saved outputs | Running the project: a scenario's fixed context and outcomes save their outputs. |

---

## 2. Surfaces and workflows

- **The `/catalog/scenarios` page** lists every scenario in your projects. Reach it from the **Scenario Catalog** tab. Search with **Search scenarios**, sort by **Recently edited**, **Name** or **Project**, and filter by **By project** or **By origin** (**Your dataflows** or **Examples**) in the left rail. Click a card to describe it in the right-hand drawer.
- **The Scenario Catalog drawer**, on the canvas. Open it from the **Scenario** button in the top bar.

Each card shows the scenario's name in its color, its project, how many nodes it holds, its description, and its project's graph.

### Action matrix

| Action | Where | What it changes | What you see |
|---|---|---|---|
| **View details** | A card, the drawer, or the canvas drawer | Nothing | The scenario's fixed context, levers and outcomes, with their saved results. |
| **Open source project** | A card, the drawer, the canvas drawer, or the details | Nothing | The project the scenario lives in, on the canvas. From an open dataflow with unsaved changes, Curio asks first. |

### Workflows

**I want to find a study I made.** Open the **Scenario Catalog** tab and search for the scenario's name, its description or its project's name.

**I want to change a scenario.** Click **Open source project**, change its nodes on the canvas, and save the dataflow. The catalog shows the change.

**I want to know what a scenario produced.** Click **View details**. Each outcome lists the output its project saved, by name, format and size. An outcome with **No saved output** has not run since the scenario was defined.

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

## 4. Importing, publishing, and sharing

Scenarios are not imported or published on their own: they travel with their dataflow. **Duplicate** on a project's card makes a copy whose scenarios stay as they are at that moment, while the original's go on changing; the catalog lists both. A dataflow someone shares with you lists its scenarios in your catalog once you save it to your projects with **File → Save dataflow**.

---

## Operator notes

The catalog reads each account's projects and needs no setting of its own.

---

## See also

- [`docs/USAGE.md`](USAGE.md#scenarios): making scenarios on the canvas, the Scenarios panel, and collapsing a scenario.
- [`docs/DATA-CATALOG.md`](DATA-CATALOG.md): where a project's saved outputs land.
- [`docs/ARCHITECTURE.md`](ARCHITECTURE.md#scenario-catalog): how the catalog reads projects, and its routes.
