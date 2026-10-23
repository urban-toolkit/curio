# Tools

What a run is told of each tool it is granted, one section per tool by its id. A section's first
paragraph is the tool's description; `### Native` replaces it for a run that calls tools natively;
`### Parameters` gives the text of each parameter, by its path in the tool's parameters (`nodes.ref`
is the `ref` of each entry of `nodes`, and `widgets[]` an entry of `widgets`). The section
`parameters` holds the texts of the parameters several tools take.

## dataflow.read

Read the project's saved dataflow, structure-first: every node (id, type, goal, content length, widgets, selection tags) and ALL edges, plus each node's last runtime status and the dataflow's scenarios with their levers, fixed context and outcomes. A scenario the user dragged in from another project names its source: that project's and that scenario's names, or the status "project-gone" or "scenario-gone" when that project, or that scenario in it, no longer exists. Node content is elided: use node.read for one node's content, or params {"include": ["content"]} for the full spec (large).

### Parameters

- include: Pass ["content"] for the full spec, node content included (large).

## web.fetch

Fetch one public https URL and return its status, content type, and a bounded body preview. Params: {"url": "https://..."}. Use it to VERIFY endpoints, dataset ids, and API shapes, never to crawl. Private/internal addresses are refused; at most {{egress.calls_per_run}} web calls per run.

### Parameters

- url: One public https URL.

## web.search

Search the web for factual verification. Params: {"q": "<query>"}. Returns bounded {title, url, snippet} rows from this deployment's search provider (DuckDuckGo unless the operator named another), or an error that says why it could not search. At most {{egress.calls_per_run}} web calls per run.

### Parameters

- q: The search query.

## node.runtime.read

Read one node's LAST execution outcome: status, error traceback tail, stdout tail, output metadata, and whether the node's content changed since that run. Params: {"nodeId": "..."} (defaults to the node this agent is attached to). A node that never ran reports status "never-executed".

## node.read

Read one node from the saved spec. Params: {"nodeId": "..."} (defaults to the node this agent is attached to).

## node.content.write

Propose replacing one node's content. Params: {"nodeId": "...", "content": "..."}. The user reviews the proposal before anything is applied; nothing changes without their explicit approval.

### Parameters

- content: The node's complete new content.

## catalog.search

Search the project's Data Catalog. Params (all optional): {"q": "<text>", "format": "<fmt>", "origin": "<origin>"}. Returns dataset rows with id, name, format, origin, installed state, and description. Catalog-lane candidates must come from these results only. Rows whose data file is resolved also carry `path` (the absolute file a node may open) and `loader` (the loader code for that path): the ONLY local paths generated node content may reference (dev/114).

### Parameters

- q: Text to search for.
- format: A dataset format.
- origin: A dataset origin.

## models.search

Search the Model Catalog: the trained models node code can run. Params (all optional): {"q": "<text>", "limit": <1 to {{models.search_max_rows}}>}; q matches a model's name, id, description and publisher. Returns model rows with id, name, task, runtime, origin, description, labels (the classes it answers, at most {{models.max_labels}}) and loader. Every row is a model this account has added, and so can run: origin "shipped" comes with Curio, "downloaded" is one of its own, added from the Discovery Catalog or imported. Copy the row's `loader` line into the node's code exactly as given (model = curio_load_model("<id>")); a model id that is not in these results does not run until the user adds it in the Model Catalog. Reads no network.

### Parameters

- q: Text to search for.
- limit: The most rows to return, 1 to {{models.search_max_rows}}.

## examples.read

Read Curio's worked examples: shipped dataflows that show how nodes, code and specs fit together. Params (optional): {"key": "<key from the list>"}. With no key, returns the list: each example's key, title and one line on what it shows. With a key, returns that example's line and its Trill (name, task, every node with its type and content, every edge), without layout. An unknown key is an error; call with no key for the keys. The datasets and node types a plan uses come from this project, not from an example. Reads no network.

### Parameters

- key: An example's key, from the list this tool returns with no key. Omit it for the list.

## scenarios.search

Search the Scenario Catalog: the scenarios saved in this account's projects, this dataflow's own among them. Params (optional): {"q": "<text>"}; q matches a scenario's name, its description and its project's name. Returns scenario rows with key, name, description, project (the name of the project it is saved in), nodeCount and inThisDataflow (true for this dataflow's own scenarios); when it stops short, scenariosElided says how many rows it left out. A scenario of another project comes into this dataflow, with its saved results, when the user drags its card in from Scenario, Browse all: name the scenario and its project and tell the user so, rather than rebuilding it. Reads no network.

### Parameters

- q: Text a scenario's name, its description or its project's name contains.

## discovery.sources

List the data portals and storage this deployment connects to. Params: none. Returns rows with sourceId, name, provider, publisher, the formats it can deliver, whether it can be searched, and whether this account holds the credential the source needs - never the credential itself. Reads no network and costs no web budget. External-lane dataset candidates must name a sourceId from these results.

## discovery.search

Search connected data portals LIVE. Params: {"q": "<text>", "sourceId": "<sourceId@major from discovery.sources, optional>", "format": "<fmt, optional>"}. PREFER naming a sourceId: without one this searches every portal at once and is charged one web call PER PORTAL, which can spend the whole per-run budget of {{egress.calls_per_run}} in a single request. Returns resource rows with sourceId, resourceId, name, publisher, formats and last-updated date - candidates must carry the sourceId and resourceId these results returned, never an invented one.

### Parameters

- q: Text to search for.
- sourceId: A sourceId@major from discovery.sources. Without one, every portal is searched and each is charged one web call.
- format: A format the resource must offer.

## discovery.acquire

Propose downloading ONE resource from a connected data portal into the Data Catalog, where it becomes an ordinary dataset. Params: {"sourceId": "<sourceId@major>", "resourceId": "<id from discovery.search results>", "format": "<one of the formats that result listed, optional>"}. The user reviews the proposal; nothing is downloaded and nothing is added to the catalog without their approval. This never writes fetch code, and it never installs a dataset into a dataflow - that is dataset.install.

### Parameters

- sourceId: The portal's sourceId@major.
- resourceId: A resourceId from discovery.search results.
- format: One of the formats that result listed.

## packages.catalog

List the Nodes Catalog's node packages with this project's install state. Params (optional): {"q": "<text>"} substring filter. Returns rows with dirName, packageId, name, description, installed, and builtin. Recommendation candidates must come from these results only; builtin packages are always present and are never proposed.

### Parameters

- q: Text a package's name or description must contain.

## packages.resolve

Resolve one or more catalog packages against this account's installed set. Params: {"dirNames": ["<dirName from packages.catalog>", ...]}. Returns each package's requested permissions, its python/js dependencies, the packages it names in dependencies.packages (packageDeps), which adding it adds, and the public functions its modules define (functions: by module, each with its call and its docstring's first paragraph), which a template of the package, or of a package that names it in dependencies.packages, imports; plus any version conflicts. Use it to enrich an identify/recommend answer before proposing an install, and to find the functions a node's code can import.

### Parameters

- dirNames: dirNames from packages.catalog results.

## dataflow.plan.write

Propose a reviewed plan that changes the dataflow graph, by ending a reply with a dataflowPlan block (not a toolRequest): {"dataflowPlan": {"goal": "...", "nodes": [{"ref": "n1", "nodeType": "<packageId>/<templateId>", "title": "...", "intent": "...", "widgets": [...], "spatialJoin": {...}}], "edges": [{"from": "n1", "to": "<ref or existing node id>", "kind": "data"|"interaction"}], "scenarios": [...], "removeNodes": ["<existing node id>"], "removeEdges": ["<existing edge id>"]}}. {{include:rules/plan-rules.md}}

### Native

Propose a reviewed plan that changes the dataflow graph: its arguments are the plan. {{include:rules/plan-rules.md}}

### Parameters

- goal: What the plan achieves, in one line.
- nodes.ref: A short id, unique in this plan, that edges name.
- nodes.nodeType: A <packageId>/<templateId> id from the Available node templates list.
- nodes.title: A short title.
- nodes.intent: One line: what this step does and produces.
- nodes.expects: The input or output this step expects, in one line.
- edges.from: A ref from this plan, or an existing node's id.
- edges.to: A ref from this plan, or an existing node's id.
- edges.toHandle: The target's input circle: in, in_1, in_2, ... Data edges only.
- scenarios.name: The scenario's name.
- scenarios.nodes: A selection's nodes: refs of this plan or existing node ids.
- scenarios.duplicateOf: A duplicate: the name of a scenario earlier in this list, whose nodes it copies.
- scenarios.copies: A duplicate: each node of that scenario to the ref its copy takes.
- scenarios.values: A duplicate: a copy's ref to the widget values it changes, {name: value}.
- scenarios.description: What it changes, in one line.
- scenarios.color: A #RRGGBB color; the next free one when absent.
- removeNodes: Existing node ids to remove.
- removeEdges: Existing edge ids to remove.

## dataset.install

Propose installing ONE dataset from the Data Catalog into this project. Params: {"datasetId": "<id from catalog.search results>"}. The user reviews the proposal; nothing is installed without their approval, and this never installs an agent.

### Parameters

- datasetId: A dataset id from catalog.search results.

## package.install

Propose installing ONE node package from the Nodes Catalog into this project. Params: {"dirName": "<the versioned dirName, e.g. curio.notes@1, from packages.catalog results or shown in parentheses in the 'Installed but NOT enlisted in this project' list>", "reason": "why this work needs it", "notes": [{"title": "...", "content": "<one finding>", "color": "<palette name or #RRGGBB>"}]}. The notes are optional: at most {{notes.max}} findings, each in a few sentences, that become notes once the package is enlisted; keep dirName and reason short. The user reviews the proposal through the package install dialog (permissions, dependencies, conflicts); nothing is installed without their approval. Built-in packages are always present and must never be proposed.

### Parameters

- dirName: The versioned dirName, such as curio.notes@1, from packages.catalog results or the 'Installed but NOT enlisted in this project' list.
- reason: Why this work needs the package.
- notes: Findings to add as notes once the package is enlisted: at most {{notes.max}}, each in a few sentences.
- notes.title: The note's title.
- notes.content: The finding the note states.
- notes.color: A palette name or #RRGGBB.

## node.create

Propose adding ONE new node to the canvas. Params: {"nodeType": "<packageId>/<templateId>", "content": "...", "title": "<short header shown on the node>", "goal": "<one-line purpose>", "appearance": {"backgroundColor": "<palette name or #RRGGBB>"}, "widgets": [...], "spatialJoin": {...}}: title, goal, appearance, widgets and spatialJoin are optional; a note template renders title and backgroundColor, so give both for notes. A {{template.label:curio.builtin/parameter}} node holds no content and exactly one widget, whose name no other {{template.label:curio.builtin/parameter}} node's widget has. nodeType must be an id from the "Available node templates" list, never invented. The user reviews the proposal; nothing is added without their approval.

### Parameters

- nodeType: A <packageId>/<templateId> id from the Available node templates list.
- content: The node's content: empty for a node that holds none, such as a {{template.label:curio.builtin/spatial-join}} or a {{template.label:curio.builtin/parameter}}.
- title: A short header shown on the node.
- goal: The node's purpose, in one line.

## package.draft.apply

Propose ONE built node package as a reviewed draft. Params: the typed build request, {"mode": "create"|"extend", "baseDigest": "<64-hex, extend only>", "manifest": {...}, "files": {"<path>": {"text"|"base64": "..."}}, The draft's identity is manifest.id + compatibility.major; the package id MUST be reverse-DNS (two or more dot-separated segments, e.g. curio.notes, never a single segment like curio-notes). An optional "target": "<packageId>@<major>" may restate it but must agree. Other params: "behaviorEntries": ["sources/<entry>.tsx", ...], "dependencies": {"python"|"js"|"packages": {name: constraint}}, "previewTemplates": [...], "nodes": [{"templateId": "...", "title": "...", "content": "...", "appearance": {"backgroundColor": "<palette name or #RRGGBB>"}}], "justification": "<the closest existing templates and why each is inadequate>"}. A draft that adds a template (every template of a create, a new one in an extend) needs the justification, which the user judges during review, and gives each new template a label no existing template has: one that already does the job is reused, not drafted again. The build service compiles/validates/previews the draft; the user reviews the diff, dependencies, and preview before anything installs. Never claim the package exists before the user applies it.

### Native

Propose ONE built node package as a reviewed draft, from the typed build request in the params. Its identity is manifest.id + compatibility.major; the id MUST be reverse-DNS (two or more dot-separated segments: curio.notes, never curio-notes), and an optional "target": "<packageId>@<major>" must agree with it. A draft that adds a template (every template of a create, a new one in an extend) needs the "justification" and gives each new template a label no existing template has: one that already does the job is reused, not drafted again. The user reviews the built draft's diff, dependencies and preview before anything installs. Never claim the package exists before the user applies it.

### Parameters

- baseDigest: The installed target's 64-hex digest. Extend only.
- target: <packageId>@<major>, which must agree with the manifest.
- manifest: The package manifest.
- files: Each file path mapped to {"text": ...} or {"base64": ...}.
- behaviorEntries: The behavior sources, such as sources/<entry>.tsx.
- dependencies: {"python"|"js"|"packages": {name: constraint}}.
- previewTemplates: The ids of the templates to preview.
- nodes: Nodes to add once the package is applied.
- nodes.templateId: A template id from the manifest.
- nodes.title: The node's title.
- nodes.content: The node's content.
- justification: The closest existing templates, and why each is inadequate. Needed when the draft adds a template.

## delegate

Delegate one specialized capability to the agent that handles it, and receive its result. The capabilities you may delegate, and who handles each, are listed in your instructions.

### Parameters

- capability: The capability to delegate.
- inputs: What the delegate needs for the task.

## parameters

- nodeId: The node's id. Defaults to the node this agent is attached to.
- appearance.backgroundColor: A palette name or #RRGGBB.
- widgets: The node's widgets: values the user sets in its Widgets tab, which its code reads.
- widgets[]: A widget: name, type, label, default, and options (choices, display, min, max, step, units).
- widgets.name: Letters, digits and underscores: the code places it as {{widgets.reference:name}}.
- widgets.label: What the Widgets tab shows beside the control.
- spatialJoin: A Spatial Join node's operation and output; it holds no content.
