# Curio's agent text

This folder is the base entry of the Agent Catalog: the pages every agent Curio ships reads, as [`packages/curio.builtin@1`](../../packages/curio.builtin@1/) is the base of the nodes. It is no agent: no catalog lists it and no agent delegates to it. Its `manifest.json` says `kind: base` and lists its pages.

- `default_preamble.md`: the preamble every agent Curio ships runs before its instruction. It includes the pages of `knowledge/`.
- `knowledge/`: one page per feature of Curio, such as its nodes, widgets, selection tags, scenarios, catalogs and the Map Edits node's code (`map-edits.md`). `knowledge/node-functions.md` lists every function node code calls, in fixed line shapes that [`node_functions.py`](../../utk_curio/backend/app/agents/domain/node_functions.py) reads for the agents' checks; the user guides link to it.
- `dataflow-block.md`: the words of the block a run that writes code is given of its dataflow, one section per line the runtime writes, which [`dataflow_block.py`](../../utk_curio/backend/app/agents/domain/dataflow_block.py) reads by name; the line that frames the block is the `dataflow-block` section of `frames.md`. `{count}` and `{tool}` stay where the runtime writes them.
- `examples.md`: the index of the dataflows Curio ships, from which a run gets its worked examples. Its links lead to the dataflows from this folder.
- `rules/`: text the agents' prompts and pages include whole: the package backend contract, the Researcher's rules for checking a fact and for writing notes, and the rules of a dataflow plan.
- `tools.md`: what a run is told of each tool it is granted: its description, the description a run on native tools gets in its place, and the text of each parameter.
- `protocol.md`: how a run replies: the follow-up prompts it may suggest, how it asks for a tool or a delegate, and the dataset candidates block.
- `frames.md`: the lines that frame what the runtime hands a run: the canvas context, the dataflow block, a delegated task's inputs, the configuration, the worked examples and the template rosters.
- `delegate-contracts.md`: what a delegated run is told to reply with: the build request, the notes reply, and the rule a delegated Dataset Finder answers to.
- `conversation-title.md`: the prompt of the call that titles a conversation.
- `keyword-types.md`: the keyword types Curio ships, the default of the Agent Catalog's Keyword types setting.
- `autark-grammar.md`: the words of the preamble's section on Autark documents, one section per line, which the runtime fills from the vendored Autark schema.
- `messages.md`: what a check tells a model when it refuses or corrects what the model wrote: a tool call the runtime does not run, a proposal it does not make, a plan, a request, code or a document it sends back for another attempt. One section per message, by its id.

An agent names a page as `curio:<path>`, its path in this folder, such as `curio:default_preamble.md`. A user's agent may name one too.

## Editing a page

A page, like each prompt in an agent's `prompts/` folder, is the text the agent reads, with a marker wherever it states a fact the code owns:

- `{{field}}` or `{{field:argument}}` is filled from `PROMPT_FIELDS` in [`contracts.py`](../../utk_curio/backend/app/agents/domain/contracts.py). For example, `{{agent.name:agent.curio.node-builder}}` is the Node Builder's name from its manifest.
- `{{include:<path>}}` puts another page of this folder in its place, whole, such as `{{include:rules/package_contract.md}}`.

The runtime composes a run's turns from the sections of `tools.md`, `protocol.md`, `frames.md` and `delegate-contracts.md`:

- A section is a `## <name>` line, then its text, up to the next such line. The runtime reads each by its name, so a section keeps its name; the text before the first one is for whoever edits the page.
- In `tools.md`, a section is named by its tool's id. Its first paragraph is the tool's description, `### Native` holds what a run on native tools gets in its place, and `### Parameters` holds one `- <path>: <text>` line per parameter, by its path in the tool's parameters: `nodes.ref` is the `ref` of each entry of `nodes`, and `widgets[]` an entry of `widgets`. The section `parameters` holds the texts several tools share.
- The runtime puts a run's own lists, such as its granted tools, its delegates or a roster's templates, on the lines after the sections that end in a colon. In `frames.md`'s `delegated-task`, `{parent}` and `{capability}` stand for the agent that delegates and the capability it asks for, once each, and in its `templates-left-out`, `{count}` for how many templates a roster did not list, once.
- In `messages.md`, a section's name is its message's id, which the check reads it by, and each `{name}` is a value the check fills when it says the message, such as a node's id or the problems it found. A section keeps a place for each value its check gives, and holds no other. The check keeps the separators around a message, such as the line break before a run's last note.
- A value an agent is given as JSON, a delegate contract or the keyword types, is one block fenced as `json`, and its markers render inside JSON strings.

To edit one:

1. Change the text, and leave the markers as they are, or add one where the text states a fact the code owns.
2. Run `python curio.py start --dev` and start a run: with `--dev`, each read renders the page as it is then. Without it, the backend renders every page and prompt once when it starts, so restart it to see an edit.
3. A new page goes in this folder and in `pages` in `manifest.json`. A page that another includes is named there by its path. A new feature of Curio gets a page in `knowledge/`, which the preamble includes.
4. `knowledge/node-functions.md` holds no markers, since the user guides link to it as written, and each function on it keeps its shape: its call as `### curio_<name>(<arguments>)`, written as Python writes a signature, then `Engines: python.` or `Engines: python, javascript.`, one line on what it does, and one bullet per argument, `` - `<name>`: <text> ``, or `` - `<name>` (<catalog phrase>): <text> `` for an argument that names a catalog's item, a blank line between each part. The catalog phrases are `CATALOG_PHRASES` in `node_functions.py`. A line of another shape fails the backend suite (`test_node_functions.py`), and so does a function whose call differs from what node code gets (`test_node_functions_sandbox.py`).
5. The backend suite renders every page and prompt (`test_agent_text.py`). A marker no field defines fails it, and so does a file no manifest lists. It also reads every section the runtime asks for, every tool text a tool's parameters use, and checks that no text of these pages is still a string in Python (`test_python_prose.py`). It reads every message a check says against `messages.md`: each names a section, and gives the values its section has places for (`test_messages.py`). And it fails on a string in `utk_curio/`'s Python whose words run past 200 characters unless it is a message to users or code (`test_prose_guard.py`).

A fact the code owns that no field states yet is a new field in `PROMPT_FIELDS`: a small function that reads the code that owns it.
