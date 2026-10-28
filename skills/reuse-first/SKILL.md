---
name: reuse-first
description: >-
  Use this skill when a task needs a node type: a node to create, a plan step, a package to
  recommend, propose or write, or notes to place on the canvas. It gives the node type ladder, taken
  in order: a template the run is given, then a package to add, then a package the Node Builder
  writes.
license: MIT
compatibility: Written for Curio's agents, their tools and node code.
metadata:
  author: curio
  version: "1.0.0"
---
## Reuse first

Reuse first, and take the rungs of the node type ladder in order, stopping at the first that works. Writing a package is the LAST resort, never the first move.

### The node type ladder

1. A listed template. Choose a node's type ONLY from the "Available node templates" list the run is given: the closest existing template (built-in or from an installed package) that can execute or contain the required content. Never invent, guess, or abbreviate a template id. A run given no such list was not granted node creation and answers in plain text instead.

2. A package to add, only when NO listed template can adequately hold the task. A fitting package this project does not have yet is proposed for install, not only named, by a run that holds package.install, with a concrete one-line reason naming what needs it (the node, import, or plan step). Look for one in packages.catalog, and on the "Installed but NOT enlisted in this project" list, the packages the account has that this project has not declared, whose dirName is the one in parentheses, never the bare package id or the template id. Never author a package whose job an already-installed one does. A package this project already has, a builtin one among them, is stated, not proposed. Enrich a proposal with packages.resolve, never inventing its permissions, dependencies or conflicts: a conflict it reports is the user's to resolve in the package dialog, never force-resolved.

3. A written package, for any new node type (plain code, a custom look, several templates or dependencies), only when neither list offers a usable template: delegate the "node.kind.author" capability (or "package.build" for a new package, "package.extend" to extend an installed user-editable one) with the requirements as inputs, naming in them the closest listed templates you considered and why each is inadequate. The {{agent.name:agent.curio.node-builder}}'s package-writing mode drafts the package with that justification, which reaches the user as a package.draft.apply proposal.

Never present a draft, build, or install as done before the user applies it, and never pretend a package compiled or passed its checks.

### A run with no tools

A run with no tools, such as the package-writing or the recommending mode, takes the ladder from its "existingPackages" input, never from packages.catalog: each package's dirName, whether this project has it, and its template ids. It answers as its own instruction says, never with a tool request. The package-writing mode reads that input before authoring anything. When a package there already satisfies the need, it authors nothing, never a duplicate package, and answers as its build-request contract's "insteadOfAuthoring" says. It extends an existing package (mode "extend", naming its template ids) rather than write a near-duplicate, and writes something new only when nothing it was shown fits, or the request explicitly asks for a new package.

### Notes

A run that places notes takes the ladder for their template:

1. REUSE. Notes go on the built-in {{template.label:curio.builtin/note}} template, which the "Available node templates" list carries: one node.create per note, {"nodeType": "curio.builtin/note"} with the finding as its "content", and the title and color node.create asks a note for. Another notes template on that list, a presentation-only template whose behavior renders a note, takes the same params. Never build, duplicate, or extend a package just to add or recolor notes. Only ids on that list take note content: a node type you saw on the canvas or in dataflow.read is NOT a note template unless it appears there, and when the list says none is available, skip straight to step 2.

2. ENLIST. When nothing in "Available node templates" fits, enlist a package of the "Installed but NOT enlisted in this project" list: its package.install request also carries "notes", the findings themselves, one row per note, in the order research-notes gives them. The runtime enlists the package once the user applies the install, then creates the notes from those rows: you do not need a second turn. An install request without "notes" enlists a package and places nothing.

3. AUTHOR. Only when NEITHER list offers a usable template, delegate node.kind.author, the ladder's third rung: you never compose a package manifest, source file, or behavior code yourself, and your delegation inputs MUST carry both your findings and the look. "notes": the findings, one row per note ({"title", "content", "color"}), which the runtime copies into the created notes verbatim, the {{agent.name:agent.curio.node-builder}} styling them and never writing your findings; a delegation without notes places nothing. "requirements": the look the notes need, described precisely. Never claim a package, template, or note exists before the user applies the proposal.
