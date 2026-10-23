## Nodes

Nodes in these dataflows either process data or visualize it. Each type of node has a different role.

A node's "type" is the id of the template it was made from. A run that can place or plan nodes receives a roster of the templates this dataflow can use, listed by id, and that roster is the authority on them. These are the built-in templates, by name:

{{builtin.nodes}}

A node that accepts more than one connection takes each one on its own input circle, numbered from 0 in the order they were connected. An edge names the circle it connects to in "targetHandle": {{inputs.handles}}, circle 0 first.

A {{template.label:curio.builtin/data-pool}} node is represented to the user as a table.

A {{template.label:curio.builtin/vis-simple}} node renders a table for DataFrames/GeoDataFrames, or a card per row when the frame carries images: one image plus that row's other values. A column holds images when at least {{image.threshold}} of its non-empty values are images; a value that is a list counts when any of its items is one. The columns named {{image.columns}} are checked first, in that order, and in them an image is a "data:image/" URI, an "/api/" path, any http(s) URL, or bare Base64 image bytes. When any of them holds images, those columns are the image columns and no other column is checked, except that {{image.column:image_url}} is left out when {{image.column:thumbnail}} holds images too, since the thumbnail is the small view of the same file. Otherwise every column is checked, and an image there is a "data:image/" URI, an "/api/" path, or an http(s) URL with an image extension ({{image.extensions}}) at its end or just before a "?" or "#"; bare Base64 does not count there. Both frame shapes work, so a GeoDataFrame whose features carry an image property displays as images too. Users can click on a card to select its row, and the selection reaches the nodes linked to it by an interaction edge. A card shows every image column of its row side by side; the node's Image column select narrows it to one, which a plan or a node.create names in the node's "simpleVis"."imageColumn" (a node's "metadata"."simpleVis" in the Trill schema). So to show only the overlays of a frame whose rows carry a photo and its overlay, name the overlay column there, and keep the frame as it is: a node that drops the photo column drops it for every node below too. A view already on the canvas changes its column through node.settings.write, its "simpleVis" naming the column, and {} shows every image column again.

A {{template.label:curio.builtin/data-loading}} node has no input: its python code brings data into the dataflow, such as a Data Catalog dataset through `curio_load_data("<id>")`, and returns it.

A {{template.label:curio.builtin/data-transformation}} node's python code reads its inputs and returns them transformed.

A {{template.label:curio.builtin/data-summary}} node starts with python code that returns a summary of the table on its input, its shape, dtypes, missing values and describe(), and shows that summary as tables.

A {{template.label:curio.builtin/js-computation}} node runs JavaScript in Node.js: each input circle is its own variable, input_0, input_1 and so on, and `return` passes its output on.

A {{template.label:curio.builtin/data-export}} node holds no code: it offers the data on its input as a file to download, a table as CSV, a GeoDataFrame as GeoJSON and anything else as JSON.

A {{template.label:curio.builtin/spatial-join}} node holds no code: it pairs the rows of the GeoDataFrames on its two input circles whose shapes meet. A plan or a node.create gives a new one its operation and output in "spatialJoin", and one already on the canvas changes them through node.settings.write.

A {{template.label:curio.builtin/note}} node is a note on the canvas, a title and a short markdown text on a color of its own; it connects to nothing and runs nothing.
