---
name: map-edits
description: >-
  Use this skill when a task changes an Autark map's features as a what-if in a Map Editor node,
  such as removing buildings, capping heights, reshaping or moving features, or drawing new ones
  and adding layers. It gives the node's one curio_edit_features call, each edit with its fields,
  the areas a map can draw, the words that make Solve write edits, and the rule that an analysis
  filter stays in the node that computes it.
license: MIT
compatibility: Written for Curio's agents, their tools and node code.
metadata:
  author: curio
  version: "1.0.0"
  curio-behaviors: edit-features
---
## {{template.label:curio.builtin/edit-features}}

A {{template.label:curio.builtin/edit-features}} node edits an Autark map's layers, as a what-if: it removes features, puts them back, changes their values, reshapes or moves them, draws new ones, and adds properties and layers. Its code is its only state: one call of `curio_edit_features`, which the node writes from its list of edits and reads back. Code of another shape still runs, but the node cannot read it, list it or edit it on the map, and Curio refuses it from an agent.

### The call

```python
return curio_edit_features(input_0, [
    {"op": "remove", "ids": [119, 136]},
    {"op": "set", "where": "height > 100", "column": "height", "value": 100},
], key="building_id", layer="table_osm_buildings")
```

- First the input: `input_0`, or, fed by several nodes, every circle's in order, `[input_0, input_1, ...]`, with `by_input=True`.
- Then the edits, in the order they are made, each a dict.
- Then, by name, each at most once: `key`, the column whose values identify a feature (`osm_id` or `building_id` on OpenStreetMap layers); `layer`, the layer the edits apply to; `keys`, the column of each other layer an edit names; `new_layers`; `crs`; `by_input`.
- Every value is written out: texts in single or double quotes, numbers, True, False, None, lists and dicts. The call is the code's only statement, from the start of its line to the end of the code, with comment lines above it and none inside it. It holds no chip, whose value the node cannot know before a run.

### The edits

An edit names its features by `ids`, values of its layer's key column, or by `where`, a condition on their properties (`height > 100 and levels >= 30`), never both. `ids` names every row that holds the id: OpenStreetMap's buildings are a row per part, each with its building's `building_id` and an `osm_id` of its own, so an edit by `building_id` changes every part of a building.

| op | fields |
|---|---|
| remove | ids or where |
| set | ids or where, column, value |
| restore | ids or where |
| scale | ids or where, column, value |
| offset | ids or where, column, value |
| expr | ids or where, column, value |
| add | id, geometry, crs, values |
| geometry | ids or where, geometry, crs |
| add_column | column, value |

Every edit may also hold `layer`, `label` and `enabled`.

- `set` writes a value: a text, a number, True, False or None. `scale` multiplies a number by `value`, `offset` adds `value` to it, and `expr` writes what an expression of the feature's properties makes (`min(height, 60)`).
- `geometry` and `add` take a GeoJSON geometry, and `add` an `id` and its `values`.
- The map's tools change a building's shape one part at a time, each part named by its own id, `where` its `building_id` and its `osm_id` both hold: `{"op": "geometry", "where": "building_id == 29623484 and osm_id == 236608503", "geometry": ...}`. The building's other parts keep their shapes. The node's form sets a value on one part the same way, `{"op": "set", "where": "building_id == 29623484 and osm_id == 236608503", "column": "height", "value": 60}`, and on all of them by `ids`.
- `add_column` adds a property, with `value`, to every feature that has none.

### The rule

- What-if changes go in {{template.label:curio.builtin/edit-features}}: a building removed, a height capped, a park drawn. An analysis filter, such as the parks over a size or the roads of one kind, stays in the node that computes it.
- An id is a value its layer's key column holds. A run prints each id no feature has, and Solve's round fails on that line.
- An area a `geometry` or `add` edit gives is one the map can draw: an outline that encloses some area and does not cross or touch itself, holes inside their outline and apart from each other, and parts that do not overlap. A run skips an edit that would give a feature any other area and prints why, and Solve's round fails on that line.
- Solve makes edits in an empty {{template.label:curio.builtin/edit-features}} node only when its goal names edits; otherwise it gives the node its call with no edits, as the node writes it when dropped, and the user makes the edits on the map. A goal names edits when one of its sentences or lines, or a clause after a colon, a semicolon or a dash between spaces, starts with one of these words: remove, delete, drop, restore, put back, set, change, scale, multiply, raise, lower, increase, decrease, cut, cap, compute, redraw, reshape, move, add, draw.
- So a plan's {{template.label:curio.builtin/edit-features}} node names its edits in its intent, a sentence each: "Remove the two tallest towers by their building_id", "Cut the parts around the parks down to 60 m". A goal that says what the node is for ("Read the map's layers and edit them on the map") names none.
