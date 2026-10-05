"""``curio_segment``: run a Model Catalog model over a collection's images.

What the Image Segmentation node calls. A model (from ``curio_load_model``)
carries a manifest that says how to run it, so nothing here is fitted to one
model:

- ``onnx``: onnxruntime on the CPU. Each image is resized to the manifest's
  input, fed as ``uint8`` pixels or as ``float32`` scaled and normalized, and
  each pixel takes the channel the graph scores highest;
- ``transformers``: the checkpoint's own image processor and
  ``AutoModelForSemanticSegmentation``, read from the folder alone
  (``local_files_only``, safetensors only), with torch on the CPU.

For every image the result has, for each class asked for, its share of all
the image's pixels, in percent; ``dominant_class`` and ``dominant_pct``, the
largest of those; and, for an image from a collection, an ``overlay_url``: the
photo with each pixel tinted by its class, written beside the collection so
Simple View shows it.
"""

from __future__ import annotations

import colorsys
import json
import os

#: How strongly the class colours tint an overlay.
OVERLAY_ALPHA = 0.5


class _OnnxRunner:
    def __init__(self, folder: str, manifest: dict) -> None:
        try:
            import onnxruntime as ort
        except ImportError as exc:  # pragma: no cover - a package dependency
            raise RuntimeError(
                "This model runs on onnxruntime, which this Curio does not have: "
                "install the Street Vision package from the Node Catalog."
            ) from exc
        self.labels = list(manifest.get("labels") or [])
        self.input = manifest.get("input") or {}
        self.session = ort.InferenceSession(
            os.path.join(folder, manifest["entry"]), providers=["CPUExecutionProvider"]
        )
        self.input_name = self.session.get_inputs()[0].name

    def __call__(self, image):
        import numpy as np

        width, height = int(self.input["width"]), int(self.input["height"])
        pixels = np.asarray(image.resize((width, height)), dtype=np.uint8)
        if self.input.get("dtype") == "uint8":
            batch = pixels.transpose(2, 0, 1)[None]
        else:
            values = pixels.astype(np.float32) * float(self.input.get("scale", 1.0))
            if self.input.get("mean") and self.input.get("std"):
                values = (values - np.asarray(self.input["mean"], dtype=np.float32)) / np.asarray(
                    self.input["std"], dtype=np.float32
                )
            batch = values.transpose(2, 0, 1)[None].astype(np.float32)
        scores = self.session.run(None, {self.input_name: batch})[0]
        if scores.ndim != 4 or scores.shape[1] != len(self.labels):
            raise RuntimeError(
                f"the model answered {scores.shape[1] if scores.ndim == 4 else scores.shape} "
                f"classes; its manifest names {len(self.labels)}"
            )
        return scores[0].argmax(axis=0)


class _TransformersRunner:
    def __init__(self, folder: str, manifest: dict) -> None:
        try:
            import torch
            from transformers import AutoImageProcessor, AutoModelForSemanticSegmentation
        except ImportError as exc:
            raise RuntimeError(
                "This model runs on Transformers, and torch or transformers is not installed "
                "here: ask whoever runs this Curio to install torch, transformers and safetensors."
            ) from exc
        checkpoint = os.path.join(folder, manifest.get("entry") or "files")
        self.torch = torch
        self.processor = AutoImageProcessor.from_pretrained(checkpoint, local_files_only=True)
        self.model = AutoModelForSemanticSegmentation.from_pretrained(
            checkpoint, local_files_only=True, use_safetensors=True
        ).eval()
        id2label = getattr(self.model.config, "id2label", None) or {}
        self.labels = list(manifest.get("labels") or []) or [
            str(id2label.get(i, i)) for i in range(int(self.model.config.num_labels))
        ]

    def __call__(self, image):
        inputs = self.processor(images=image, return_tensors="pt")
        with self.torch.no_grad():
            logits = self.model(**inputs).logits
        return logits[0].argmax(dim=0).cpu().numpy()


def load_runner(model_dir: str):
    """The runner a model's manifest names."""
    path = os.path.join(str(model_dir), "manifest.json")
    try:
        with open(path, encoding="utf-8") as handle:
            manifest = json.load(handle)
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"{model_dir} is not a Model Catalog model: {exc}") from exc
    runtime = manifest.get("runtime")
    if runtime == "onnx":
        return _OnnxRunner(str(model_dir), manifest), manifest
    if runtime == "transformers":
        return _TransformersRunner(str(model_dir), manifest), manifest
    raise RuntimeError(f"Curio does not run {runtime!r} models")


#: The colours street classes are drawn in, the way segmentation maps of
#: street scenes conventionally draw them, so an overlay reads at a glance.
CLASS_COLOURS = {
    "road": (128, 64, 128), "sidewalk": (244, 35, 232), "building": (70, 70, 70),
    "house": (70, 70, 70), "wall": (102, 102, 156), "fence": (190, 153, 153),
    "pole": (153, 153, 153), "traffic light": (250, 170, 30), "traffic sign": (220, 220, 0),
    "vegetation": (107, 142, 35), "tree": (107, 142, 35), "plant": (107, 142, 35),
    "terrain": (152, 251, 152), "grass": (152, 251, 152), "earth": (152, 251, 152),
    "sky": (70, 130, 180), "person": (220, 20, 60), "rider": (255, 0, 0),
    "car": (0, 0, 142), "truck": (0, 0, 70), "bus": (0, 60, 100), "train": (0, 80, 100),
    "motorcycle": (0, 0, 230), "bicycle": (119, 11, 32), "water": (0, 105, 180),
}


def palette(labels):
    """A colour per class: a street class's own, else hues spread so neighbours differ."""
    colours = []
    for index, label in enumerate(labels):
        fixed = CLASS_COLOURS.get(str(label).strip().lower())
        if fixed:
            colours.append(fixed)
            continue
        hue = (index * 0.618033988749895) % 1.0
        lightness = 0.45 if index % 2 else 0.6
        red, green, blue = colorsys.hls_to_rgb(hue, lightness, 0.75)
        colours.append((int(red * 255), int(green * 255), int(blue * 255)))
    return colours


def make_curio_segment(curio_derived_file=None):
    """``curio_segment`` for one execution; *curio_derived_file* is where an
    overlay is written (None writes none)."""

    def curio_segment(images, model, classes=None, *, overlays=True):
        """Segment every image of *images* (rows with a ``path``) with *model*,
        a model ``curio_load_model`` loaded; *classes* are the labels to report,
        all of them when None. Returns *images* with the results as its first columns:
        ``dominant_class``, ``dominant_pct``, a ``<class>_pct`` per class,
        ``overlay_url`` and ``segment_error``."""
        import numpy as np
        import pandas as pd
        from PIL import Image

        task = (getattr(model, "manifest", None) or {}).get("task")
        if task not in (None, "semantic-segmentation"):
            what = "makes images from images" if task == "image-to-image" else "reads a graph"
            raise ValueError(
                f"{getattr(model, 'id', 'This model')} {what}, so it does not label pixels: "
                "run it with a node made for it, not curio_segment"
            )
        runner = getattr(model, "runner", None)
        if runner is None:
            raise TypeError(
                "curio_segment runs a loaded model: pass curio_load_model(\"<id>\")"
            )
        labels = runner.labels
        wanted = list(classes) if classes else list(labels)
        unknown = [name for name in wanted if name not in labels]
        if unknown:
            raise ValueError(
                f"the model has no class {', '.join(map(repr, unknown))}; it labels {', '.join(labels)}"
            )
        index = {name: labels.index(name) for name in wanted}
        colours = np.asarray(palette(labels), dtype=np.uint8)
        if "path" not in getattr(images, "columns", ()):
            raise ValueError("curio_segment reads rows with a path, as curio_load_collection gives them")

        shares = {name: [] for name in wanted}
        dominant, dominant_pct, overlay_urls, errors = [], [], [], []

        def skip(reason):
            for name in wanted:
                shares[name].append(None)
            dominant.append(None)
            dominant_pct.append(None)
            overlay_urls.append(None)
            errors.append(reason)

        for _, row in images.iterrows():
            path = row.get("path")
            if not isinstance(path, str) or not os.path.isfile(path):
                skip("the image is not on this machine")
                continue
            # One file that is not an image, or is cut short, or decodes to more
            # pixels than Pillow allows, is that row's error; the model's own
            # errors still stop the node.
            try:
                with Image.open(path) as source:
                    image = source.convert("RGB")
            except (OSError, Image.DecompressionBombError):
                skip("the image could not be read")
                continue
            ids = np.asarray(runner(image))
            counts = np.bincount(ids.ravel().astype(np.int64), minlength=len(labels)) / ids.size
            for name in wanted:
                shares[name].append(round(float(counts[index[name]]) * 100, 2))
            best = max(wanted, key=lambda name: counts[index[name]])
            dominant.append(best)
            dominant_pct.append(round(float(counts[index[best]]) * 100, 2))
            errors.append(None)
            url = None
            can_write = curio_derived_file is not None and row.get("dataset_id") and row.get("file_id")
            if overlays and can_write:
                mask = Image.fromarray(colours[ids.astype(np.int64)]).resize(image.size, Image.NEAREST)
                derived = curio_derived_file(row["dataset_id"], row["file_id"], 0, "png", kind="image")
                Image.blend(image, mask, OVERLAY_ALPHA).save(derived["path"])
                url = derived.get("image_url")
            overlay_urls.append(url)

        # A share is `<class>_pct`, never the bare label: ADE20K, for one,
        # has a class called "path", which would overwrite the image's path.
        results = {"dominant_class": dominant, "dominant_pct": dominant_pct}
        results.update({f"{name}_pct": shares[name] for name in wanted})
        results["overlay_url"] = overlay_urls
        results["segment_error"] = errors
        # First, so a card's caption leads with what the model found. One
        # join, not a column at a time: a model can name 150 classes.
        rest = images.drop(columns=[c for c in results if c in images.columns])
        out = rest.join(pd.DataFrame(results, index=images.index))
        return out[[*results, *rest.columns]]

    return curio_segment
