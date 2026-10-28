---
name: provenance
description: >-
  Use this skill when a task asks what changed in a node, when it changed or who changed it, or
  asks to bring back earlier code. It says what a node's history holds, the runs and edits in it,
  the entry an agent's applied change makes, how to read and compare entries, and that putting an
  entry back is the user's action.
license: MIT
compatibility: Written for Curio's agents, their tools and node code.
metadata:
  author: curio
  version: "1.0.0"
---
## Provenance

Every node keeps a history, which its Provenance drawer lists and the dataflow saves. Each entry is a run or an edit, and holds the node's code as the entry left it.

- A run holds the code that ran, when it started and ended, and the kinds of data it read and returned, or ERROR for a run that failed.
- An edit ran nothing: it reads and returns no data, and starts and ends at once. A change made in a {{template.label:curio.builtin/edit-features}} node's body is one, named by what it changed, such as "Remove building_id 12".
- A change an agent proposed and the user applied is an edit named after the agent, such as "{{agent.name:agent.curio.node-builder}}", which also holds the code it replaced when no entry before it does. A node an agent proposed with its code starts its history with such an edit once the user adds it; a node of a plan starts with none, and the code later written into it is its first edit.

Each entry descends from the one the node's code came from, so a history is a tree, and the node's next run or edit descends from the entry in use. An agent that has node.history.read reads a node's entries, newest first, and one entry's code. It says what changed by comparing two entries' code, or an entry's code with the node's code now (node.read), and names entries by when they were made, never by their ids. An entry made since the dataflow was last saved is not in the history it reads yet.

Putting an entry's code back in the node is the user's action, from the node's Provenance drawer: an agent never restores an entry. To bring an entry's code back, an agent that can change the node proposes that code as a change to its content (node.content.write), which the user reviews like any other.
