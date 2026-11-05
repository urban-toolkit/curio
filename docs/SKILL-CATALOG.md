# Skill Catalog

The Skill Catalog is where Curio keeps the **skills** its agents read. Each skill tells an agent how to do a specific task, such as writing a Map Editor node's edits, in the open [Agent Skills format](https://agentskills.io/specification). Curio ships its own, a node package can ship more, and you can import a skill written for any Agent Skills tool.

Curio has seven catalogs: the [Node Catalog](NODE-CATALOG.md) holds the nodes you drop on the canvas, the [Data Catalog](DATA-CATALOG.md) the datasets they read, the [Model Catalog](MODEL-CATALOG.md) the models they run, the [Agent Catalog](AGENT-CATALOG.md) the assistants you attach to them, the Skill Catalog the skills those assistants read, the [Discovery Catalog](DISCOVERY-CATALOG.md) the portals, storage, services and models you take datasets and models from, and the [Scenario Catalog](SCENARIO-CATALOG.md) the scenarios saved in your projects.

This guide is in six parts, plus operator notes:

- [1. What is the Skill Catalog?](#1-what-is-the-skill-catalog): skills, the ones Curio ships, those of node packages, and the storage layers.
- [2. Surfaces and workflows](#2-surfaces-and-workflows): the page, a skill's details, the action matrix, and walkthroughs.
- [3. Using a skill](#3-using-a-skill): how a call comes to hold a skill, naming one in your message, and the line under a reply.
- [4. Your own skills](#4-your-own-skills): the skills you import, and the name each one takes.
- [5. Importing, publishing, and sharing](#5-importing-publishing-and-sharing): the import and its review, exporting, publishing, and removing a skill.
- [6. The skill format](#6-the-skill-format): the fields of a skill's frontmatter and of its metadata.
- [Operator notes](#operator-notes): the publish switch.

---

## 1. What is the Skill Catalog?

### Concept

A **skill** is a folder, named as the skill, that holds a `SKILL.md`: YAML frontmatter that names the skill and says when to use it, then the body an agent reads, with instructions, procedural knowledge, reference facts and starter templates. A file the body links sits in the folder beside it:

```
street-trees/
  SKILL.md
  references/species.md
```

A skill does nothing on its own. An **agent** decides and acts, with its own tools, its model and its memory, the conversation of each chat, and reads a skill when a task needs it. One skill serves many agents, and an agent uses many skills. Which skills an agent holds is the agent's: its manifest names them, and you add and remove them in the agent's details ([Agent Catalog](AGENT-CATALOG.md#skills)).

A skill's name is its folder's, so no two skills you see share one ([4. Your own skills](#4-your-own-skills)).

### What ships with Curio

The skills Curio ships are the folders of its [`skills/`](../skills/), one skill each. Every call holds the three **core** skills, the first rows below. A run is handed the skills that serve the node it writes or checks, or, when it reads the whole dataflow, those that serve its nodes and features, and a chat the skills whose words your message holds. The five procedures several agents follow are handed by name, to the calls that follow them:

| Skill | It tells an agent how to | It serves |
|---|---|---|
| `nodes` | pick node types, knowing what each takes and gives | every call, in the preamble |
| `node-control` | change a node's content, settings and runs as Curio allows | every call, in the preamble |
| `compatibility` | connect outputs only to inputs that accept them | every call, in the preamble |
| `node-functions` | call Curio's `curio_*` functions from node code | nodes whose content is code: Data Loading, Python, JavaScript, Data Summary, Data Export and Map Editor |
| `catalogs` | find and load datasets, models and keys from the catalogs | nodes whose content is code |
| `widgets` | declare, place and set widgets, dataset widgets and values several nodes share | nodes whose content is code, Vega-Lite and Autark nodes |
| `selection-chips` | read a view's selections through selection tags | nodes whose content is code, Vega-Lite and Autark nodes |
| `vega-lite-starter` | start a Vega-Lite chart from its node's starter spec | Vega-Lite nodes |
| `vega-lite-maps` | draw a map with Vega-Lite | Vega-Lite nodes |
| `autark` | write an Autark document, from the grammar Curio ships | Autark nodes |
| `autark-starter` | start an Autark map from its node's starter document | Autark nodes |
| `map-edits` | write a Map Editor node's call and edits, keeping filters in their own node | Map Editor nodes |
| `interaction-edges` | link views with interaction edges and Data Pools | Data Pools, and dataflows with interaction edges |
| `scenarios` | work with scenario sets, each scenario's scenario-specific nodes, shared context and shared outcomes, and the chips and colors that compare them | dataflows with scenario boxes, and a chat message that says scenario, scenarios, what if or what-if |
| `dashboards` | keep a dataflow's pinned tiles working on its dashboard | dataflows with pinned tiles |
| `provenance` | read a node's history and the agents' entries in it | nothing: a chat loads it when a task needs it |
| `reuse-first` | choose a node type: a listed template, then a package to add, then a written package | by name: the Node Builder's and the Researcher's chats, the Node Builder building a node for another agent, Write a package and Recommend packages |
| `data-sources` | ground a data source before writing its loader: a typed path, a catalog dataset, a verified URL, a saved key, values the user typed, made-up data only when asked | by name: the Node Builder's chat, the Node Builder building a node for another agent, and Write a node's content |
| `package-contract` | write a package's backend to Curio's contract | by name: Write a package |
| `fact-checking` | check a fact against what was probed or fetched, labeling each finding | by name: the Researcher's chat and Check a fact |
| `research-notes` | turn findings into notes on the dataflow, and place them on a note template: the built-in Note, a package to enlist, or a notes package to write | by name: the Researcher's chat and Notes from search results |

Which of them each agent holds, and which its modes are handed, is in the [Agent Catalog](AGENT-CATALOG.md#skills).

### Skills from packages

A node package can ship skills of its own, in its `skills/` folder, such as Rasterization's `rasterization` and the Vega-Lite package's `vega-lite-charts` ([Node Catalog](NODE-CATALOG.md#6-the-manifest)). The Skill Catalog lists the skills of the packages you can add, each with its package: its card and its details say **From Rasterization**, and **Used by** reads *Agents on a dataflow that uses Rasterization*.

- Every agent on a dataflow that uses the package lists the package's skills after its own, and a call that writes one of the package's nodes holds the ones that serve it.
- A package's skill comes and goes with its package. It has no **Remove**, **Publish** or **Export**, and an agent's **Add skill** does not offer it.
- A name means one skill. When a package's skill has the name of a skill Curio ships or of one of yours, Curio's or yours comes first.

### Storage layers

Skills live in Curio's own `skills/` folder, in the node packages that ship them, and in files under `.curio/`:

| Layer | On disk | Written by |
|---|---|---|
| **Shipped skills**, the skills Curio ships | `skills/<name>/` beside `utk_curio/` (`utk_curio/_shipped/skills/` in a pip install) | Nothing: Curio reads them. |
| **Package skills**, the skills of a node package | `skills/<name>/` in the package's folder, `packages/<packageId>@<major>/skills/<name>/` | The package: its skills come with it and go with it. |
| **Your skills**, the ones you imported and your copies of published ones | `.curio/users/<user-key>/skills/<name>/` (`SKILL.md` and its other files); a hidden `.curio-skill.json` marks a copy of a published skill | **Import skill** adds one; **Add skill** with a published skill copies it here; **Remove from your skills** deletes one. |
| **Shared catalog**, published skills | `.curio/skills-catalog/<name>/`, each with its publisher's record, `.curio-publisher.json` | **Publish** on a skill you imported adds one; **Unpublish** removes it. |
| **Agent skills**, what you added to or removed from each agent | `.curio/users/<user-key>/agent-skills.json` | **Import skill** gives the skill to the agents left ticked; **Remove from your skills** takes it off every agent; an agent's **Add skill**, **Remove** and **Restore** change its entry ([Agent Catalog](AGENT-CATALOG.md#storage-layers)). |

---

## 2. Surfaces and workflows

There are two places you work with skills:

- **The `/catalog/skills` page** lists every skill you see. Reach it from **Skill Catalog** in the top bar of `/projects` and every catalog page, after **Agent Catalog**. Filter in the left rail by **All skills** (the skills Curio ships, your own, the published ones you can add, and those of the packages you can add) or **Core**, the three every call holds, and search with **Search skills…**, which matches a skill's name, its description and what it serves. **Import skill** is in the header.
- **An agent's details**, on the `/catalog/agents` page and in the Agent Catalog drawer on the canvas, list the agent's skills in their **Skills** section, with **Add skill**, **Remove** and **Restore** ([Agent Catalog](AGENT-CATALOG.md#skills)). A skill's name there opens the skill's details over the agent's. The canvas bar has no Skill Catalog button: on the canvas, you reach a skill through the **Agent Catalog** drawer, an agent's **View details**, then its **Skills**.

A skill's card gives its name, whose it is (its author, or Curio, you, the shared catalog or its package), its version, its description, what it serves and how many agents use it. Click a card to describe it in the right-hand drawer:

- **Serves**: the kinds of node whose templates its `curio-behaviors` name, and the features of a dataflow its `curio-features` name.
- **From**, whose it is; **Shared catalog**, for a published skill; then its license, its compatibility and its files.
- **Used by**: the agents that use it, each one you gave it marked *added by you*.
- **Remove from your skills**, for a skill you hold, and the **Publish** or **Unpublish** pill, for one you imported.
- **View details**.

Right-clicking a card offers **View details** too.

**View details** opens the skill's details window: its description, **Serves**, **Used by**, **Skill info** (its name, whose it is, its version, author, license and compatibility), its **Text**, what an agent reads, collapsed until you open it, and its other **Files**. **Export** is in its header.

### Action matrix

| Action | Where | What it changes | What you see |
|---|---|---|---|
| **View details** | A card, its right-click menu, the drawer, or a skill's name in an agent's details | Nothing | The skill's details window. |
| **Import skill** | The `/catalog/skills` header | Your skills, and your agent skills for the agents left ticked | A review first ([Importing a skill](#importing-a-skill)), then the skill joins your skills and the agents left ticked hold it. |
| **Export** | A skill's details | Nothing | `<name>.zip` downloads, holding `<name>/SKILL.md` and its other files. |
| **Publish** | The drawer of a skill you imported | The shared catalog of skills | Every account on this install sees the skill and can give it to an agent with **Add skill**. |
| **Unpublish** | The drawer of a skill you published | The shared catalog of skills | It leaves the shared catalog. Accounts that added it keep their copy. |
| **Remove from your skills** | The drawer of a skill you hold | Your skills and your agent skills | The skill is deleted, and no agent of yours holds it. Refused while one of your agents holds it as its own. |

**Remove from your skills** is the one action here that deletes a skill. An agent's **Add skill**, **Remove** and **Restore** are in the Agent Catalog's [action matrix](AGENT-CATALOG.md#action-matrix).

### Workflows

**I want to read what a skill says.** Open the **Skill Catalog** page and click **View details** on the skill. Its details open on what it is for, what it serves and the agents that use it, and its **Text** section holds what an agent reads, collapsed until you open it.

**I want to know which agents use a skill.** Click its card: **Used by**, in the drawer, names them. To give the skill to another agent, open that agent's details in the Agent Catalog and click **Add skill** in its **Skills** section.

**I want my agents to use a skill written for another tool.** On the **Skill Catalog** page, click **Import skill** and pick the skill's folder, its files or a `.zip` of it. Read the review, untick each agent that should go without it, and click **Import**. **Publish** in its drawer offers it to everyone on the install, and **Export** in its details saves it to use elsewhere.

**I want an agent to use a skill someone published.** Open the agent's details in the Agent Catalog, click **Add skill** and pick the skill. Your account keeps a copy of it, and the agent holds it from its next run.

---

## 3. Using a skill

How a call holds its skills:

- **The core skills,** `nodes`, `node-control` and `compatibility`, are in the preamble every agent Curio ships reads, so every call holds them.
- **In chat,** an agent lists its other skills, each by its name and description, and loads one with its tool **skill.read** when a task matches it. A chat holds the procedures its instruction follows from its first message, such as the Node Builder's `reuse-first` and `data-sources`, and a chat attached to a node also holds the skills of that kind of node. A skill a chat loaded stays for the rest of its conversation, and is never loaded twice. Loading a skill uses none of a reply's three tool rounds, for up to four skills a reply.
- **A mode** has no tools, so Curio hands it the skills its task needs, with no extra call: the skills of the node it writes or checks, those of node code when it writes a package or builds a node for another agent, those of the kinds of node and the features of the dataflow when it reads the whole dataflow, and the mode's own procedures, such as `package-contract` for Write a package. A call another agent asks for that has no prompt of its own, such as the Node Builder building a node for the Dataset Finder, follows the agent's chat instruction, so it holds that instruction's procedures too. In Solve, the attempt after a check refused the one before is also handed the skill that answers that check: `map-edits` for the Map Editor's check, `vega-lite-starter` or `autark` for the check of a chart's or a map's document, `node-functions` for a function Curio does not give node code, `catalogs` for a source no catalog holds, and `dashboards` for a pinned tile that loads its own data.
- **Named in your message,** `/<name>` at the start of a message hands that skill to the chat's run with the message, and the rest of the conversation keeps it, as it keeps a skill the chat loaded. Type `/` at the start of a message to list the chat's skills, then pick one or keep typing its name: `/map-edits remove the two tallest towers`. A skill the chat holds already is not handed again.
- **Asked for in your message,** a word a skill names for itself (its `curio-asks`, [6. The skill format](#6-the-skill-format)) hands that skill to the chat's run the same way, and the rest of the conversation keeps it: `scenarios` comes with a message that says scenario, scenarios, what if or what-if, such as "What if the speed limit dropped to 20?". A word counts whole and in any case, never inside a longer one, and only in a message a person typed, never in the task one agent hands another.

The skills an agent's calls may hold are the agent's list: its manifest names them, and you change the list in its details ([Agent Catalog](AGENT-CATALOG.md#skills)). The skills of the packages a dataflow uses reach every agent on it ([Skills from packages](#skills-from-packages)). On a dataflow you edit at its owner's invitation, the agents hold the owner's skills ([Invited editors](AGENT-CATALOG.md#invited-editors)).

**The skills a reply used.** A line under each chat reply names the skills its run held or loaded: those it was handed for the node the chat is on or the procedures its instruction follows, those your message named, those its words asked for, those earlier turns of the conversation took in, then those it loaded. Hovering a name says which. The core skills, which every call holds, are not named.

---

## 4. Your own skills

Your skills are those you imported and your copies of published skills, which **Add skill** keeps when you give one to an agent. They are yours alone: another account sees one only when you publish it. An agent holds one when its manifest names it, when the skill's import review left the agent ticked, or when **Add skill** gave it the skill ([Add skills and agents](AGENT-CATALOG.md#add-skills-and-agents)).

**A skill's name** is its folder's, so no two skills you see share one. An import is refused when its name is that of a skill Curio ships, a skill of a package you can add, or one of your skills. The review says whose skill has the name and offers another one: the name you check and keep becomes the skill's folder and its `name` together. A newer `version` in its `metadata` replaces your skill of that name: the review says so, **Import** reads **Replace**, and the agents that used your skill keep it.

---

## 5. Importing, publishing, and sharing

### Importing a skill

**Import skill**, in the `/catalog/skills` header, takes a skill written for any Agent Skills tool: its folder, its `SKILL.md` and its other files, or a `.zip` of its folder. Before anything is kept, a review shows the skill as Curio read it:

- its name and description;
- what does not follow the [format](https://agentskills.io/specification), under **Read anyway: not in the format**;
- what keeping it in the format leaves out, under **Left out**;
- its **Files**;
- **Agents that use it**, each one ticked: the four catalog agents and the other agents in all your projects.

Curio reads the skill leniently, as other Agent Skills tools do. It refuses a skill only when its frontmatter is no YAML mapping, it has no description, its description runs past 1,024 characters or its compatibility past 500. A value that holds `: ` is read as quoted text, with a warning. Curio keeps the skill in the format: its frontmatter is written anew with the format's fields alone, and a field the format does not define moves into its `metadata` when it holds one value. Untick an agent to leave it without the skill, then click **Import**: the skill joins your skills, and the agents left ticked hold it as a skill given with **Add skill** is.

### Exporting a skill

**Export**, in a skill's details, saves the skill as `<name>.zip`, which holds `<name>/SKILL.md` and its other files, as any Agent Skills tool reads them. A skill Curio ships has its `{{...}}` markers filled in, as an agent reads it, and the same skill exports to the same bytes every time. A skill's evaluations, its `evals/` folder, stay out of the zip, as they stay out of what an agent is offered.

### Publishing a skill

**Publish**, in the drawer of a skill you imported, offers it to every account on this Curio, as an agent is published. Only you, its publisher, can publish over it or unpublish it. Another account gives a published skill to one of its agents with **Add skill**, which keeps a copy of it in that account: the copy keeps working after you unpublish, it is never that account's to publish, and a newer `version` you publish replaces it the next time that account adds the skill to an agent. Only a skill you imported is published: never Curio's, a package's or a copy of a published one. When the operator starts Curio with `--no-allow-publish`, **Publish** and **Unpublish** are refused and hidden ([Operator notes](#operator-notes)).

### Removing a skill

**Remove from your skills**, in the drawer of a skill you hold, deletes it and takes it off every agent's list, so a later skill of that name joins none until you add it. It is refused while one of your agents' chat instruction, one of its modes or a call another agent asks it for names the skill as its own. A skill you published stays in the shared catalog until you unpublish it.

A guest on a hosted Curio imports, removes, publishes and unpublishes no skill, and the page answers each with *Sign in with an account to …*.

---

## 6. The skill format

A `SKILL.md` opens with its frontmatter, YAML between two `---` lines, then its body. The frontmatter of the skill of [Add skills and agents](AGENT-CATALOG.md#add-skills-and-agents):

```yaml
---
name: street-trees
description: "Use this skill when: a dataflow counts or maps the city's street trees"
metadata:
  author: parks-team
---
```

| Field | Required | What it holds |
|---|---|---|
| `name` | Yes | The skill's name, its folder's: 1 to 64 lowercase letters, digits and hyphens, with no hyphen first or last and none twice in a row. |
| `description` | Yes | When to use the skill, in 1 to 1,024 characters. A chat lists each skill by its name and description, and loads the one whose description matches its task. |
| `license` | | The skill's license. |
| `compatibility` | | What the skill was written for, in at most 500 characters. |
| `metadata` | | Strings by string keys: Curio's facts about the skill (below), and any other key you give it. |
| `allowed-tools` | | The tools the skill expects, as the format defines them. |

The keys of `metadata` Curio reads:

| Key | What it says |
|---|---|
| `author`, `version` | Who wrote the skill, and its version, quoted so YAML reads it as text. A newer `version` replaces your skill of that name ([4. Your own skills](#4-your-own-skills)). |
| `curio-behaviors` | The node behaviors (a template's `behavior`, such as `code`, `vega`, `autk-grammar` or `edit-features`) whose nodes a run writing or checking one is handed the skill for, a space between each. |
| `curio-features` | The features of a dataflow (`scenario-boxes`, `interaction-edges`, `pinned-tiles`) that a run reading a dataflow with them, or writing a node that takes part in one, is handed the skill for, a space between each. |
| `curio-refusals` | The kinds a Solve check records when it refuses an attempt, whose next attempt is handed the skill, a space between each. |
| `curio-templates` | In a package's skill: templates of its own package, by their `id`, whose nodes a run writing or checking one is handed the skill for, a space between each. |
| `curio-asks` | Words or phrases of a person's chat message that hand the skill to that turn, a comma between each ([3. Using a skill](#3-using-a-skill)). |

The body is the Markdown an agent reads. A file it links, such as `references/species.md`, sits one level below the skill's folder, and a chat reads it with **skill.read** when the body says to. Keep `SKILL.md` under 500 lines. [EXTENDING §9](EXTENDING.md#9-writing-a-skill) says how to write a skill and what its description says, and [Evaluating a skill](EXTENDING.md#evaluating-a-skill) how to test one.

---

## Operator notes

| Variable | Flag | Effect |
|---|---|---|
| `CURIO_ALLOW_FACTORY_CATALOG_PUBLISH` | `--allow-publish` (default), `--no-allow-publish` | Allows or forbids **Publish** and **Unpublish** of skills, as it does for node packages, datasets and agents. When forbidden, both are refused and their buttons are hidden on `/catalog/skills`. |

`curio.py start` sets this variable on every start, so `--no-allow-publish` is the way to turn publishing off ([NODE-CATALOG.md, Operator notes](NODE-CATALOG.md#operator-notes)).

**On a multi-user install, start with `--no-allow-publish`.** Otherwise any user signed in with an account can publish a skill they imported into the shared catalog.

---

## See also

- [`docs/AGENT-CATALOG.md`](AGENT-CATALOG.md): the agents, the skills each one holds, and **Add skill**, **Remove** and **Restore**.
- [`docs/EXTENDING.md`](EXTENDING.md#9-writing-a-skill): writing a skill, and evaluating one.
- [`docs/NODE-CATALOG.md`](NODE-CATALOG.md#6-the-manifest): the node packages whose skills come with them.
- [`docs/ARCHITECTURE.md`](ARCHITECTURE.md#agent-prompt-composition): how a run's skills are chosen, listed and handed; the skills' routes are under [Agent Routes](ARCHITECTURE.md#agent-routes).
- [`docs/examples/skills/street-trees/`](examples/skills/street-trees/SKILL.md): a skill of your own to import, with its agent in [`docs/examples/agents/`](examples/agents/agent.you.tree-counter@1/manifest.json).
- The [Agent Skills specification](https://agentskills.io/specification).
