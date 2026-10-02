"""Label every pixel of each image with a Model Catalog model.

The input is a collection's rows, each with a ``path``, as a Data Loading
node gives them for street-level images from the Data or Discovery Catalog.
To use another model, drag it from the Model Catalog onto this node.

``classes`` are the model's labels to report; each becomes a
``<class>_pct`` column, its share of the image's pixels in percent. ``None``
reports every label.
``dominant_class`` and ``dominant_pct`` name the one of them covering most,
and ``overlay_url`` shows the image tinted by class.
"""

model = curio_model("model.curio.ddrnet23-slim")
classes = ["vegetation", "terrain", "sky", "road", "sidewalk", "building"]

return curio_segment(arg, model, classes)
