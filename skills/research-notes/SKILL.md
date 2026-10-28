---
name: research-notes
description: >-
  Use this skill when findings become notes on the dataflow, such as the answer to a question from
  the web or the findings of a search. It gives the order the notes follow, a yellow note with the
  question and then a green note per answer, the markdown their content is written in, and the rule
  of one note per finding, written faithfully.
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
