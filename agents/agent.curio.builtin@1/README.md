# Curio's agent text

This folder is the base entry of the Agent Catalog: the pages every agent Curio ships reads, as [`packages/curio.builtin@1`](../../packages/curio.builtin@1/) is the base of the nodes. It is no agent: no catalog lists it and no agent delegates to it. Its `manifest.json` says `kind: base` and lists its pages.

- `default_preamble.md`: the preamble every agent Curio ships runs before its instruction.
- `examples.md`: the index of the dataflows Curio ships, from which a run gets its worked examples. Its links lead to the dataflows from this folder.
- `rules/`: text the agents' prompts include whole: the package backend contract, and the Researcher's rules for checking a fact and for writing notes.

An agent names a page as `curio:<path>`, its path in this folder, such as `curio:default_preamble.md`. A user's agent may name one too.

## Editing a page

A page, like each prompt in an agent's `prompts/` folder, is the text the agent reads, with a marker wherever it states a fact the code owns:

- `{{field}}` or `{{field:argument}}` is filled from `PROMPT_FIELDS` in [`contracts.py`](../../utk_curio/backend/app/agents/domain/contracts.py). For example, `{{agent.name:agent.curio.node-builder}}` is the Node Builder's name from its manifest.
- `{{include:<path>}}` puts another page of this folder in its place, whole, such as `{{include:rules/package_contract.md}}`.

To edit one:

1. Change the text, and leave the markers as they are, or add one where the text states a fact the code owns.
2. Run `python curio.py start --dev` and start a run: with `--dev`, each read renders the page as it is then. Without it, the backend renders every page and prompt once when it starts, so restart it to see an edit.
3. A new page goes in this folder and in `pages` in `manifest.json`. A page that another includes is named there by its path.
4. The backend suite renders every page and prompt (`test_agent_text.py`). A marker no field defines fails it, and so does a file no manifest lists.

A fact the code owns that no field states yet is a new field in `PROMPT_FIELDS`: a small function that reads the code that owns it.
