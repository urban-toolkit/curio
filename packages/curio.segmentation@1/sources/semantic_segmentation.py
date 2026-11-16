"""Segmentation's module: a Model Catalog model labels every pixel of a collection's images.

``segment_images`` is what a segmentation model's node calls with its
settings: DDRNet23-Slim's Image Segmentation, and the node of a segmentation
model added from the Discovery Catalog, whose packages name this one in
``dependencies.packages``. A model (from ``curio_load_model``) carries a
manifest that says how to run it, so nothing here is fitted to one model:

- ``onnx``: onnxruntime on the CPU. Each image is resized to the manifest's
  input, fed as ``uint8`` pixels or as ``float32`` scaled and normalized, and
  each pixel takes the channel the graph scores highest;
- ``transformers``: the checkpoint's own image processor and
  ``AutoModelForSemanticSegmentation``, read from the folder alone
  (``local_files_only``, safetensors only), with torch on the CPU.

A runtime is imported only when a model of it runs, and the model's package
declares it: onnxruntime, or torch, transformers and safetensors. The model's
weights are where ``model.path`` says, which is where ``curio_load_model``
found them.
"""

from __future__ import annotations

import colorsys
import hashlib
import os
import re

import numpy as np
import pandas as pd
from PIL import Image

#: What node code calls.
__all__ = ["segment_images"]

#: How strongly the class colours tint an overlay.
OVERLAY_ALPHA = 0.5

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

#: The id of a file ``curio_derived_file`` named, ``<fileId>@<t_ms>``, then
#: ``-<tag>`` and ``.<ext>`` when it has them: a frame a node sampled from a
#: video is named so after its video and its time.
_DERIVED_ID_RE = re.compile(r"^([0-9a-f]{16})@([0-9]{1,12})(?:-([0-9a-z]{1,32}))?(?:\.([0-9a-z]{1,8}))?$")


def model_tag(model) -> str:
    """What an overlay's name holds of the model that drew it: the first twelve
    hex digits of the SHA-1 of its id. Two models' overlays of one photo are
    then two files, each served under its own URL (#621)."""
    return hashlib.sha1(str(getattr(model, "id", "") or "").encode("utf-8")).hexdigest()[:12]


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


class _OnnxRunner:
    def __init__(self, path: str, manifest: dict) -> None:
        try:
            import onnxruntime as ort
        except ImportError as exc:  # pragma: no cover - a package dependency
            raise RuntimeError(
                "This model runs on onnxruntime, which this Curio does not have: "
                "add the model with Add in the Model Catalog, which installs it."
            ) from exc
        self.labels = list(manifest.get("labels") or [])
        self.input = manifest.get("input") or {}
        self.session = ort.InferenceSession(path, providers=["CPUExecutionProvider"])
        self.input_name = self.session.get_inputs()[0].name

    def __call__(self, image):
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
    def __init__(self, path: str, manifest: dict) -> None:
        try:
            import torch
            from transformers import AutoImageProcessor, AutoModelForSemanticSegmentation
        except ImportError as exc:
            raise RuntimeError(
                "This model runs on Transformers, and torch or transformers is not installed "
                "here: ask whoever runs this Curio to install torch, transformers and safetensors."
            ) from exc
        self.torch = torch
        self.processor = AutoImageProcessor.from_pretrained(path, local_files_only=True)
        self.model = AutoModelForSemanticSegmentation.from_pretrained(
            path, local_files_only=True, use_safetensors=True
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


def _runner(model):
    """What labels one image's pixels with *model*, on the runtime its
    manifest names, its weights read at ``model.path``; its ``labels`` are
    the classes it names, the manifest's, else the checkpoint's."""
    runtime = model.manifest.get("runtime")
    if runtime == "onnx":
        return _OnnxRunner(model.path, model.manifest)
    if runtime == "transformers":
        return _TransformersRunner(model.path, model.manifest)
    raise RuntimeError(f"Curio does not run {runtime!r} models")


def _overlay_source(row):
    """``(file_id, t_ms, kind)``, as ``curio_derived_file`` takes them, of
    the file an overlay of *row*'s image is derived from: a collection's image
    or frame itself, or, for a frame a node sampled from a video
    (``<videoId>@<t_ms>``), that video at that time. None for any other
    derived file, which gets no overlay."""
    file_id = str(row["file_id"])
    sampled = _DERIVED_ID_RE.match(file_id)
    if sampled is None:
        return file_id, 0, "image"
    video, t_ms, tag, ext = sampled.groups()
    if row.get("kind") == "frame" and tag is None and ext is None:
        return video, int(t_ms), "video"
    return None


def segment_images(images, model, derived_file, *, classes=None, overlays=True):
    """Label every pixel of each image in *images* with *model*, a segmentation
    model ``curio_load_model`` loaded, and give each image the share of its
    pixels each class covers, the class covering most and an overlay.

    *images* is a collection's rows, each with a ``path``, as
    ``curio_load_collection`` returns them; *classes* are the model's labels
    to report, every label it names when None. The model runs as its
    manifest says: an ``onnx`` graph on onnxruntime, a ``transformers``
    checkpoint with its own image processor and torch, both on the CPU.
    Returns *images* with the results as its first columns:
    ``dominant_class`` and ``dominant_pct``, a ``<class>_pct`` per class (its
    share of all the image's pixels, in percent), ``overlay_url`` and
    ``segment_error``. With *overlays*, each image's overlay, the image
    tinted by class, is a PNG written where *derived_file*
    (``curio_derived_file``) says, under a name that holds the image and the
    model; a frame a node sampled from a video gets its video's overlay at
    the frame's time, and *derived_file* None writes none. A row whose image
    is not on this machine, or cannot be read, gets no shares and says why
    in ``segment_error``; a class the model does not name stops the node.
    """
    manifest = getattr(model, "manifest", None)
    if not isinstance(manifest, dict) or not isinstance(getattr(model, "path", None), str):
        raise TypeError('segment_images runs a loaded model: pass curio_load_model("<id>")')
    task = manifest.get("task")
    if task == "image-to-image":
        raise ValueError(
            f"{getattr(model, 'id', 'This model')} makes images from images, so it does not label pixels: "
            "run it with a node made for it, not segment_images"
        )
    if task == "concept-segmentation":
        raise ValueError(
            f"{getattr(model, 'id', 'This model')} finds the things text prompts name, so it does not "
            "label pixels by class: run it with a node made for it, not segment_images"
        )
    runner = _runner(model)
    labels = runner.labels
    wanted = list(classes) if classes else list(labels)
    unknown = [name for name in wanted if name not in labels]
    if unknown:
        raise ValueError(
            f"the model has no class {', '.join(map(repr, unknown))}; it labels {', '.join(labels)}"
        )
    index = {name: labels.index(name) for name in wanted}
    colours = np.asarray(palette(labels), dtype=np.uint8)
    tag = model_tag(model)
    if "path" not in getattr(images, "columns", ()):
        raise ValueError("segment_images reads rows with a path, as curio_load_collection gives them")

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
        can_write = derived_file is not None and row.get("dataset_id") and row.get("file_id")
        source = _overlay_source(row) if overlays and can_write else None
        if source is not None:
            file_id, t_ms, kind = source
            mask = Image.fromarray(colours[ids.astype(np.int64)]).resize(image.size, Image.NEAREST)
            derived = derived_file(row["dataset_id"], file_id, t_ms, "png", kind=kind, tag=tag)
            Image.blend(image, mask, OVERLAY_ALPHA).save(derived["path"])
            url = derived.get("image_url")
        overlay_urls.append(url)

    # A share is `<class>_pct`, never the bare label: ADE20K, for one, has a
    # class called "path", which would overwrite the image's path.
    results = {"dominant_class": dominant, "dominant_pct": dominant_pct}
    results.update({f"{name}_pct": shares[name] for name in wanted})
    results["overlay_url"] = overlay_urls
    results["segment_error"] = errors
    # First, so a card's caption leads with what the model found. One join,
    # not a column at a time: a model can name 150 classes.
    rest = images.drop(columns=[c for c in results if c in images.columns])
    out = rest.join(pd.DataFrame(results, index=images.index))
    return out[[*results, *rest.columns]]
