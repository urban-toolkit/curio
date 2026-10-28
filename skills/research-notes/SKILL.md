---
name: research-notes
description: >-
  Use this skill when findings become notes on the dataflow, such as the answer to a question from
  the web or the findings of a search. It gives the order the notes follow, a yellow note with the
  question and then a green note per answer, the markdown their content is written in, the rule of
  one note per finding, written faithfully, and the template a chat places them on.
license: MIT
compatibility: Written for Curio's agents, their tools and node code.
metadata:
  author: curio
  version: "1.0.0"
---
## Notes from findings

Follow the reference conversation pattern for every answered question. The notes mirror the exchange, in sequence:

1. FIRST a yellow note carrying the user's question verbatim (title "Question", content the question text).
2. THEN one green note per answer (title names the subject, e.g. "Cool roofs in Chicago"); extra findings take further green notes. The user's explicitly requested colors override these defaults.

Compose every answer note's content as clean markdown (the notes render it): bold labels for facts ("**Where:** downtown Chicago"), "- " bullets for lists, [source](https://...) links for every web-gathered fact. Never dump an unformatted prose wall into a note, and never put markdown syntax errors in one.

One note per finding. A note's content is the finding text as given: condense long text faithfully, never invent facts, never restate a guess as a finding.

### Placing notes

A chat that places notes with its tools takes the node type ladder of the reuse-first skill for their template:

1. REUSE. Notes go on the built-in {{template.label:curio.builtin/note}} template, which the "Available node templates" list carries: one node.create per note, {"nodeType": "curio.builtin/note"} with the finding as its "content", and the title and color node.create asks a note for. Another notes template on that list, a presentation-only template whose behavior renders a note, takes the same params. Never build, duplicate, or extend a package just to add or recolor notes. Only ids on that list take note content: a node type you saw on the canvas or in dataflow.read is NOT a note template unless it appears there, and when the list says none is available, skip straight to step 2.

2. ENLIST. When nothing in "Available node templates" fits, enlist a package of the "Installed but NOT enlisted in this project" list: its package.install request also carries "notes", the findings themselves, one row per note, in the order above. The runtime enlists the package once the user applies the install, then creates the notes from those rows: you do not need a second turn. An install request without "notes" enlists a package and places nothing.

3. AUTHOR. Only when NEITHER list offers a usable template, delegate node.kind.author, the ladder's third rung: you never compose a package manifest, source file, or behavior code yourself, and your delegation inputs MUST carry both your findings and the look. "notes": the findings, one row per note ({"title", "content", "color"}), which the runtime copies into the created notes verbatim, the {{agent.name:agent.curio.node-builder}} styling them and never writing your findings; a delegation without notes places nothing. "requirements": the look the notes need, described precisely. Never claim a package, template, or note exists before the user applies the proposal.
