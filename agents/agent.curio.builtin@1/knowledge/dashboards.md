## Dashboards

A dataflow's dashboard is a page of its own that shows the nodes pinned to it, each as a tile, and anyone with its link can open it. A tile draws from the outputs saved with the dataflow: a chart or a map draws the saved output of the nodes that feed it, and a tile whose nodes have no saved output runs them on the server when the page opens. In `dataflow.read`, the row of a pinned node says "pinned": true; a node whose row does not say so is not on the dashboard.

Anyone viewing the dashboard can change the value of a pinned {{template.label:curio.builtin/parameter}} node, and of the widgets of a pinned node, except text, text list and file widgets. A change runs the nodes it reaches on the server with the owner's datasets, models and packages and no connection keys. A viewer never changes the dataflow, its saved outputs or the Data Catalog; what such a run makes is kept for 7 days for the next viewer who picks the same values. A node whose code reads a connection key stops on the dashboard. A pinned node's tile shows its widgets as controls: above a chart or a map, and in place of a code node's code. To let viewers try a value, make it a widget of a node the user pins.

The dashboard refuses to open, saying why and naming the nodes to change, in two cases:

- Its saved data is over 25 MB, the most a page carries. Aggregate or filter upstream of the heaviest tiles, or the user unpins them.
- A pinned {{template.label:curio.builtin/autk-grammar}} tile loads its own data: its spec has a "data" section, which it would fetch when the page draws. Move the "data" section into a node of its own upstream of the tile, such as an {{template.label:curio.builtin/autk-grammar}} node whose spec holds only that section, and draw that node's output in the tile. A spec an agent writes for a pinned tile with a "data" section is sent back.

The user pins and unpins a node with the pin in its header; an agent never pins or unpins a node. A plan that removes a pinned node takes its tile off the dashboard, and the plan's review card says so.
