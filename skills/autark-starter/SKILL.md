---
name: autark-starter
description: >-
  Use this skill when writing an Autark document for a node whose input has already run. It gives
  the ladder Curio follows to write a starter document from the input's layers and their columns,
  so the document agrees with what the node would draw unless the user asks for something else,
  and says which inputs a map can draw.
license: MIT
compatibility: Written for Curio's agents, their tools and node code.
metadata:
  author: curio
  version: "1.0.0"
---
## The starter document an Autark node writes for itself

When an Autark node is connected to a node that has already run, and its
editor is still empty, Curio fills it with a starter document chosen from the
input's layers, the same way a Vega-Lite node fills itself. Generate documents
that agree with this ladder unless the user asks for something else. Each rule
names the layers with geometry it needs and the column roles each of them needs
(at least one column of each), then the family the document writes and what it
draws. First match wins:

{{autk.starter_ladder}}
- no geometry -> no document at all

A map draws only tables with geometry. A DataFrame input is read through its one
geometry column; one with no geometry column, or with several, cannot be drawn,
so have the upstream node return a GeoDataFrame with its active geometry set.
