---
name: provenance
description: >-
  Use this skill whenever the user asks about a node's past, even when node.history.read could
  answer: who or which agent changed it, when it changed or ran, what its code was before, how two
  versions differ, or how to undo a change or get an earlier version back. It says what a node's
  history holds, how to read and compare its entries, where the user puts one back, and what to
  answer without the history. It is about a node's own edits and runs, not about dates in its data.
license: MIT
compatibility: Written for Curio's agents, their tools and node code.
metadata:
  author: curio
  version: "1.0.0"
---
## Provenance

Every node keeps a history, which its Provenance drawer lists and Curio keeps with the dataflow as each entry is made. Each entry is a run or an edit, and holds the node's code as the entry left it.

- A run holds the code that ran, when it started and ended, and the kinds of data it read and returned, or ERROR for a run that failed.
- An edit ran nothing: it reads and returns no data, and starts and ends at once. A person's typing in the node, once they pause or leave its editor, is one, named after them, such as "Ana edited". A change made in a {{template.label:curio.builtin/edit-features}} node's body is one, named by what it changed, such as "Remove building_id 12".
- A change an agent made is an edit named after the agent, such as "{{agent.name:agent.curio.node-builder}}", which also holds the code it replaced.

Each entry descends from the one the node's code came from, so a history is a tree, and the node's next run or edit descends from the entry in use. An agent that has node.history.read reads a node's entries, newest first, and one entry's code. It says what changed by comparing two entries' code, or an entry's code with the node's code now (node.read), and names entries by when they were made, never by their ids.

An agent without node.history.read cannot see any node's history, so it neither calls that tool nor guesses who changed a node or what its code was. It says it cannot read the history, and points the user to the node's Provenance drawer, where they see each run and edit, who or what made it, and when.

Putting an entry back in the node is the user's action, from the node's Provenance drawer: an agent never restores an entry. When asked to bring back earlier code, an agent that can change the node and has that code, pasted by the user or read from an entry, writes it as a change to the node's content (node.content.write), which lands as the agent's change and the user can undo. Otherwise it says it cannot restore an entry and points the user to the node's Provenance drawer, where they put the entry back themselves, also when the history holds no entry the user means. A change an agent made can also be taken back with its **Undo** in that agent's chat.
