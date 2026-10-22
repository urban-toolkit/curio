## Selection tags

A selection tag gives a node's code the rows selected in a view: a brush or a click in a {{template.label:curio.builtin/vis-vega}} chart, or a pick or a brush in an {{template.label:curio.builtin/autk-grammar}} map or plot. A tag belongs to the node whose code reads it, and names the view and the column whose values identify the view's rows, such as osm_id or building_id. The user adds it in that node's Widgets tab. dataflow.read lists each node's tags under "selections", each with its view, its column and how many ids it holds.

The node's code places a tag where its ids are used, as its reference: `{{selections.reference:picked}}` for the tag named picked. A run replaces the reference with the list of the ids of the selected rows, each once, or an empty list when nothing is selected, so the code reads the rows of its input that hold them in that column:

```python
    rows = {{inputs.chip:0}}
    picked = {{selections.reference:picked}}

    return rows[rows["osm_id"].isin(picked)]
```

A tag holds at most {{selections.id_cap}} ids. Never place a reference to a tag the node does not have, and never type the ids into the code in its place.
