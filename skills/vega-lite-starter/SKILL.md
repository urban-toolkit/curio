---
name: vega-lite-starter
description: >-
  Use this skill when writing a Vega-Lite spec for a node whose input has already run. It gives
  the ladder Curio follows to write a starter spec from the input's column types, so the spec
  agrees with what the node would draw unless the user asks for something else, and the rules on
  aggregates and identifier columns.
license: MIT
compatibility: Written for Curio's agents, their tools and node code.
metadata:
  author: curio
  version: "1.0.0"
---
## The starter spec a Vega-Lite node writes for itself

When a Vega-Lite node is connected to a node that has already run, and its editor
is still empty, Curio fills it with a starter spec chosen from the input's
column types. Generate specs that agree with this ladder unless the user asks
for something else. Otherwise the AI and the node produce different charts for
the same input, which is worse than either alone. Each rule names the column
roles it needs (at least one column of each, unless it gives a count), then
the mark it writes and what it shows. First match wins:

{{vega.starter_ladder}}
- nothing usable -> no spec at all

Column roles come from pandas dtypes, checked in this order:
{{starter.dtype_roles}}. A column of any other dtype has no role.
Never chart `__row_index__`, and avoid a nominal column that has one distinct
value per row: it is an identifier and produces one bar per row.

Always state an aggregate on a bar chart. Without one, Vega-Lite silently draws
one bar per row.
