## Interactions

An edge of type: "Interaction" (in the Trill specification) carries selections between two visualizations, never data. Link two visualizations directly when at least one of them is a {{template.label:curio.builtin/vis-vega}} or an {{template.label:curio.builtin/autk-grammar}} node: each of those highlights the rows the other one selects, and a {{template.label:curio.builtin/vis-vega}} node marks them in a column called "interacted", "1" for a selected row and "0" otherwise.

A {{template.label:curio.builtin/data-pool}} goes between visualizations only when a {{template.label:curio.builtin/vis-simple}} must show the selection, when selections are merged (AND or OR), when a {{template.label:curio.builtin/vis-vega}} chart colors its own selection through "interacted", or when three or more visualizations share one selection. Each visualization is then linked to the {{template.label:curio.builtin/data-pool}}, which marks the selected rows in its column "interacted" and passes them to every node it feeds.

A {{template.label:curio.builtin/data-pool}} starts at OVERWRITE, keeping the newest selection only. A plan or a node.create sets how the selections combine in the pool's "dataPool", shaped as a node's "metadata"."dataPool" in the Trill schema: "insideChart" combines the selects of one chart, and "betweenCharts" the latest selection of each chart linked to the pool. MERGE_AND keeps the rows every selection picked, MERGE_OR the rows any of them picked, and OVERWRITE the newest selection's. So a pool that shows the rows selected in both charts has "betweenCharts": "MERGE_AND".

A visualization shows a selection it receives through the column "interacted", and a chart shows its own through its selection's name. For example, this Vega-Lite specification defines a scatterplot with an interval selection that colors red the points it selects and the points another visualization selects.

```json
{ 
  "$schema": "{{vega.schema_url}}", 
  "params": [ {"name": "clickSelect", "select": "interval"} ], 
  "mark": { "type": "point", "cursor": "pointer" }, 
  "encoding": { 
    "x": {"field": "gt_65", "type": "quantitative"},
    "y": {"field": "mean", "type": "quantitative", 
    "scale": {"domain": [37, 42]}}, 
    "opacity": {
        "condition": {"param": "clickSelect", "value": 0.7},
        "value": 0.3 
    }, 
    "color": {
      "condition": [
        {"param": "clickSelect", "empty": false, "value": "red"},
        {"test": "datum.interacted === '1'", "value": "red"}
      ],
      "value": "blue" }
  },
  "config": { "scale": { "bandPaddingInner": 0.2 } } 
} 
```

A point selection over key columns matches rows by their values, so the two visualizations may read different rows that share those columns: a Vega-Lite point select with "fields": ["unit_id"], or an Autark map layer (the one with "isPick": true) or plot with "selectFields": ["unit_id"], whose table must come from the node's input. A point selection without them matches rows by position, so both visualizations must read the same rows in the same order; an interval selection matches by column name.

A {{template.label:curio.builtin/edit-features}} node feeds the {{template.label:curio.builtin/autk-grammar}} map it edits on, and an Interaction edge links the two, so features picked on the map reach it. Its code, one `curio_edit_features(...)` call, is written by the node from its edits.

Nodes that can have interaction connection edge:

{{builtin.interaction}}
