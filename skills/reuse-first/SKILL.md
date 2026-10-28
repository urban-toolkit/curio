---
name: reuse-first
description: >-
  Use this skill when a task needs a node type, such as a node to create, a plan step, a package to
  recommend, propose or write, or notes to place on the canvas. It gives the node type ladder, taken
  in order: a template the run is given, then a package to add to the project, then a package the
  Node Builder writes, with what each rung proposes, what a run with no tools reads instead, and
  what is never claimed before the user applies it.
license: MIT
compatibility: Written for Curio's agents, their tools and node code.
metadata:
  author: curio
  version: "1.0.0"
---
## Reuse first

Reuse first, and take the rungs of the node type ladder in order, stopping at the first that works. Writing a package is the LAST resort, never the first move.

### The node type ladder

1. A listed template. Choose a node's type ONLY from the "Available node templates" list the run is given: prefer the closest existing template (built-in or from an installed package) that can execute or contain the required content. Never invent, guess, or abbreviate a template id. A run given no such list was not granted node creation and answers in plain text instead.

2. A package to add, only when NO listed template can adequately hold the task. A fitting package that this project does not have yet is proposed for install, not only named, by a run that holds package.install: ONE package.install tool request per package, with its dirName and a concrete one-line reason naming what needs it (the node, import, or plan step).
   - A package of the Node Catalog: read packages.catalog for a package whose templates do the work, and take its dirName from the packages.catalog results.
   - A package the user's account already has: its templates are on the "Installed but NOT enlisted in this project" list, which this project simply has not declared. Its dirName is the exact value shown in parentheses after "(package …)" on that list (the versioned dirName, e.g. curio.notes@1, never the bare package id and never the template id). Never author a package whose job an already-installed one does.
   - A package this project already has is stated, not proposed. Rows marked builtin are always present: they are answers ("already available via the built-in package"), never proposals.
   - Enrich a package you propose with packages.resolve, and never invent its permissions, dependencies or conflicts. A conflict packages.resolve reports is a finding: the user resolves conflicts in the package dialog; you never force-resolve.
   - Never present an install as done: every proposal awaits the user's review in the package install dialog.

3. A written package, for any new node type (plain code, a custom look, several templates or dependencies), only when neither list offers a usable template: delegate the "node.kind.author" capability (or "package.build" for a new package, "package.extend" to extend an installed user-editable one) with the requirements as inputs, and name in them the closest listed templates you considered and why each is inadequate. The {{agent.name:agent.curio.node-builder}}'s package-writing mode drafts the package with that justification, and the runtime turns the draft into a reviewed package.draft.apply proposal: the user judges the justification and reviews the diff, dependencies and preview before anything installs. A new template with the label of a listed template is refused: use that template instead.

Never present a draft, build, or install as done before the user applies it, and never pretend a package compiled or passed its checks.

### A run with no tools

A run with no tools, such as the package-writing or the recommending mode, takes the ladder from its "existingPackages" input, never from packages.catalog: it carries each package's dirName, whether this project has it installed, and its template ids. It answers as its own instruction says, never with a tool request.

The package-writing mode reads that input before authoring anything. When one of those packages already satisfies the need, say so and author nothing: that is your whole answer, never a duplicate package. Say it in the shape the build-request contract's "insteadOfAuthoring" names, so the caller can act on it. Prefer extending an existing package (mode "extend", naming its template ids) over creating a near-duplicate. Author something new only when nothing you were shown fits, or the request explicitly asks for a new package.

### Notes

A run that places notes takes the ladder for their template:

1. REUSE. Notes go on the built-in {{template.label:curio.builtin/note}} template, curio.builtin/note, which the "Available node templates" list carries. Emit one node.create tool request per note with exactly these params: {"nodeType": "curio.builtin/note", "title": "<short header>", "content": "<the finding text>", "appearance": {"backgroundColor": "<palette name or #rrggbb>"}}; the note renders title and backgroundColor, so never omit them. Another notes template on that list, a presentation-only template whose behavior renders a note, takes the same params. Never build, duplicate, or extend a package just to add or recolor notes. Only ids on that list can take note content: a node type you saw on the canvas or in dataflow.read is NOT a note template unless it appears there, and when the list says none is available, skip straight to step 2.

2. ENLIST. When nothing in "Available node templates" fits, check the "Installed but NOT enlisted in this project" list. The package.install tool request of the ladder's second rung, its "dirName" and its "reason", also carries "notes": the findings themselves, one row per note, in the reference order: [{"title": "Question", "content": "<the user's question verbatim>", "color": "yellow"}, {"title": "<subject>", "content": "<the answer as markdown>", "color": "green"}, ...]. When the user applies the install, the runtime enlists the package and then creates your notes from those rows, one after another, below the install card; you do not need a second turn. An install request without "notes" enlists a package and places nothing.

3. AUTHOR. Only when NEITHER list offers a usable template, delegate package authoring: emit a delegate request for the node.kind.author capability (the package.create-or-extend intent). You never compose a package manifest, source file, or behavior code yourself: the {{agent.name:agent.curio.node-builder}} writes packages; your job is the requirements AND the findings. Your delegation inputs MUST carry both:

   - "notes": the findings themselves, one row per note: [{"title": "...", "content": "<the finding text, verbatim or faithfully condensed>", "color": "<palette name or #rrggbb>"}]. The note content is the answer the user asked for; a delegation without notes places nothing. The runtime copies these rows into the created nodes verbatim; the {{agent.name:agent.curio.node-builder}} styles the note, it never writes your findings.
   - "requirements": the look the notes need, described precisely.

   The requested notes are created only after the user applies the draft's proposal, which the third rung of the ladder says how the user reviews. Never claim a package, template, or note exists before the user applies the proposal.
