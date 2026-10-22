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
