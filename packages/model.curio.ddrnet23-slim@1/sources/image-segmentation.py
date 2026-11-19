"""Image Segmentation.

Input: a collection's rows, each with a ``path``, as a Data Loading node
gives them for street-level images from the Data or Discovery Catalog. To use
another model, drag it from the Model Catalog onto this node.

``classes`` are the model's labels to report; each becomes a
``<class>_pct`` column, its share of the image's pixels in percent. ``None``
reports every label. ``dominant_class`` and ``dominant_pct`` name the one of
them covering most, and ``overlay_url`` shows the image tinted by class.
"""

from semantic_segmentation import segment_images

model = curio_load_model("model.curio.ddrnet23-slim")
classes = None  # every class the model names

return segment_images(input_0, model, curio_derived_file, classes=classes)
