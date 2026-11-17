"""SAM 3 on a collection's images: what each label names in each image, found
and outlined, how many objects of each label there are and how much of the
image they cover, and an overlay of the image with them drawn.

Segment Images calls :func:`find_in_images` with its settings and Curio's
plumbing: the model ``curio_load_model("model.curio.sam3")`` gives, whose
``path`` is the folder of SAM 3's weights, and ``curio_derived_file``, which
says where a file made from a collection's image or video is kept and served.
SAM 3 on images is Transformers' ``Sam3Model``, the detector of the video
checkpoint Track Objects reads, loaded from the same folder. It runs on the
device Track Objects picks and draws each object as Track Objects draws one
(``sam3_tracking``).
"""

import hashlib
import json
import os
import re
from dataclasses import dataclass

import pandas as pd
import torch
from PIL import Image
from transformers import Sam3Model, Sam3Processor
from transformers.modeling_outputs import BaseModelOutputWithPooling

from sam3_tracking import _colors, _device, _draw

#: What node code calls.
__all__ = ["find_in_images"]

#: How the tag of an image's overlay begins (``_tag``).
TAG = "sam3"
#: How many labels SAM 3 looks for at once in an image's features: more runs
#: faster and holds more memory at once.
LABELS_AT_ONCE = 8
#: Above how much SAM 3's mask of an object says a pixel is the object's.
MASK_THRESHOLD = 0.5
#: The id of a file ``curio_derived_file`` named, ``<fileId>@<t_ms>``, then
#: ``-<tag>`` and ``.<ext>`` when it has them: a frame a node sampled from a
#: video is named so after its video and its time. Segmentation's
#: ``semantic_segmentation`` names its overlays by the same rule.
_DERIVED_ID_RE = re.compile(r"^([0-9a-f]{16})@([0-9]{1,12})(?:-([0-9a-z]{1,32}))?(?:\.([0-9a-z]{1,8}))?$")


@dataclass(frozen=True)
class _Run:
    """SAM 3, loaded once, and what one call asked of it: the labels' text
    features are read once for every image."""

    processor: object
    sam3: object
    device: str
    dtype: object
    labels: list
    colors: dict
    words: object
    words_mask: object
    threshold: float
    width: int


def find_in_images(images, model, derived_file, *, labels, threshold=0.5, width=960, max_images=300):
    """Find what *labels* name, such as sidewalk or curb ramp, in each image of
    a collection with SAM 3: each image comes back with how many objects of
    each label it holds, how much of the image they cover, the label that
    covers the most, and an overlay of the image with each object drawn.

    *images* is a collection's rows, each with a ``path``, as
    ``curio_load_collection`` returns them, or the frames Sample Video Frames
    sampled from its videos. *model* is SAM 3 as
    ``curio_load_model("model.curio.sam3")`` gives it, and *derived_file* is
    ``curio_derived_file``. Each image is read at most *width* wide, and SAM 3
    keeps an object whose score is above *threshold*.

    Returns *images* with the results as its first columns, as Image
    Segmentation's are: ``dominant_class`` and ``dominant_pct``, the label
    whose objects cover the most of the image and that share in percent
    (missing and 0 where SAM 3 found nothing); for each label, ``<label>_pct``, the
    share of the image its objects cover together, and ``<label>_objects``,
    how many it found, a space written as ``_`` as Track Objects writes it;
    ``overlay_url``, the image with each object's mask, box and label drawn;
    and ``segment_error``. An overlay is a PNG written where *derived_file*
    says, named after the image, or after its video at its time for a frame
    Sample Video Frames sampled, as Image Segmentation names one, and after
    the labels, *threshold* and *width*, so calls that ask differently keep
    overlays of their own. Empty *labels*, a label named twice, more rows than
    *max_images* and rows with no ``path`` stop the call before SAM 3 loads;
    an image that is not on this machine, or cannot be read, gets no results
    and says why in ``segment_error``.
    """
    if not labels:
        raise ValueError("LABELS is empty: name at least one thing to look for")
    labels = [str(label) for label in labels]
    twice = sorted({label for label in labels if labels.count(label) > 1})
    if twice:
        raise ValueError(f"LABELS names {', '.join(map(repr, twice))} more than once")
    names = {label: (f"{label}_pct", label.replace(" ", "_") + "_objects") for label in labels}
    columns = ["dominant_class", "dominant_pct", *(name for pair in names.values() for name in pair)]
    shared = sorted({name for name in columns if columns.count(name) > 1})
    if shared:
        raise ValueError(f"LABELS would give two results one column: {', '.join(shared)}; rename a label")
    if "path" not in getattr(images, "columns", ()):
        raise ValueError("Segment Images reads rows with a path, as curio_load_collection gives them")
    if max_images < 1:
        raise ValueError(f"MAX_IMAGES is {max_images}: a run looks at one image at least, so set it to 1 or more")
    if len(images) > max_images:
        raise ValueError(
            f"Segment Images looks at {max_images} images in one run (MAX_IMAGES), and its input has "
            f"{len(images)}: sample fewer frames, keep fewer rows, or raise MAX_IMAGES"
        )
    results = {name: [] for name in columns}
    results["overlay_url"] = []
    results["segment_error"] = []
    if len(images):
        run = _loaded(model, labels, threshold, width)
        tag = _tag(labels, threshold, width)
        for _, row in images.iterrows():
            _look(run, row, derived_file, tag, names, results)
    # First, so a card's caption leads with what SAM 3 found. One join, not a
    # column at a time: 35 labels make 72 columns.
    rest = images.drop(columns=[c for c in results if c in images.columns])
    out = rest.join(pd.DataFrame(results, index=images.index))
    return out[[*results, *rest.columns]]


def _loaded(model, labels, threshold, width):
    """SAM 3's processor and image model from ``model.path``, on the device
    Track Objects picks, with the labels' text features read once."""
    device, dtype = _device()
    processor = Sam3Processor.from_pretrained(model.path, local_files_only=True)
    sam3 = Sam3Model.from_pretrained(model.path, local_files_only=True, dtype=dtype).to(device).eval()
    with torch.inference_mode():
        words = processor(text=labels, return_tensors="pt")
        mask = words["attention_mask"].to(device)
        text = sam3.get_text_features(input_ids=words["input_ids"].to(device), attention_mask=mask).pooler_output
    return _Run(
        processor=processor, sam3=sam3, device=device, dtype=dtype, labels=labels, colors=_colors(labels),
        words=text, words_mask=mask, threshold=float(threshold), width=int(width),
    )


def _look(run, row, derived_file, tag, names, results):
    """SAM 3 on *row*'s image: its results added to *results*, its overlay
    written where *derived_file* says."""
    path = row.get("path")
    if not isinstance(path, str) or not os.path.isfile(path):
        _skip(results, names, "the image is not on this machine")
        return
    # A file that is not an image, or is cut short, or decodes to more pixels
    # than Pillow allows, is that row's error; SAM 3's own errors stop the node.
    try:
        with Image.open(path) as source:
            image = _within(source.convert("RGB"), run.width)
    except (OSError, Image.DecompressionBombError):
        _skip(results, names, "the image could not be read")
        return
    found = _found(run, image)
    area = image.width * image.height
    best, best_share = None, 0.0
    for label in run.labels:
        masks = found[label]["masks"]
        share = round(float(masks.any(dim=0).sum()) * 100 / area, 2) if len(masks) else 0.0
        results[names[label][0]].append(share)
        results[names[label][1]].append(len(masks))
        if share > best_share:
            best, best_share = label, share
    results["dominant_class"].append(best)
    results["dominant_pct"].append(best_share)
    results["segment_error"].append(None)
    url = None
    source = _overlay_source(row) if row.get("dataset_id") and row.get("file_id") else None
    if source is not None:
        file_id, t_ms, kind = source
        derived = derived_file(row["dataset_id"], file_id, t_ms, "png", kind=kind, tag=tag)
        _drawn(run, image, found).save(derived["path"])
        url = derived.get("image_url")
    results["overlay_url"].append(url)


def _skip(results, names, reason):
    """No results for a row, and *reason* in its ``segment_error``."""
    for name in results:
        results[name].append(reason if name == "segment_error" else None)


def _within(image, width):
    """*image*, made at most *width* wide, its shape kept."""
    if image.width <= width:
        return image
    return image.resize((width, max(1, round(image.height * width / image.width))), Image.Resampling.BILINEAR)


def _found(run, image):
    """What each label names in *image*: ``{label: {masks, boxes, scores}}``,
    each object's mask as booleans the image's size. The image's features are
    read once, and the labels look at them ``LABELS_AT_ONCE`` at a time."""
    found = {}
    with torch.inference_mode():
        pixels = run.processor(images=image, return_tensors="pt")
        vision = run.sam3.get_vision_features(pixel_values=pixels["pixel_values"].to(run.device, run.dtype))
        size = [(image.height, image.width)]
        for start in range(0, len(run.labels), LABELS_AT_ONCE):
            chunk = run.labels[start:start + LABELS_AT_ONCE]
            outputs = run.sam3(
                vision_embeds=_repeated(vision, len(chunk)),
                text_embeds=BaseModelOutputWithPooling(pooler_output=run.words[start:start + len(chunk)]),
                attention_mask=run.words_mask[start:start + len(chunk)],
            )
            kept = run.processor.post_process_instance_segmentation(
                outputs, threshold=run.threshold, mask_threshold=MASK_THRESHOLD, target_sizes=size * len(chunk),
            )
            for label, result in zip(chunk, kept):
                found[label] = {"masks": result["masks"].bool(), "boxes": result["boxes"], "scores": result["scores"]}
    return found


def _repeated(vision, n):
    """One image's features, *vision*, as the batch of *n* the labels looked
    for at once read: the same tensors, seen *n* times, not copied."""
    if n == 1:
        return vision

    def batched(value):
        if torch.is_tensor(value):
            return value.expand(n, *value.shape[1:])
        if isinstance(value, tuple):
            return tuple(batched(item) for item in value)
        return value

    return type(vision)(**{key: batched(value) for key, value in vision.items()})


def _drawn(run, image, found):
    """*image* with each object's mask, box, label and number drawn, as Track
    Objects draws a frame's objects."""
    masks, boxes, label_of = [], [], {}
    for label in run.labels:
        for mask, box in zip(found[label]["masks"], found[label]["boxes"]):
            label_of[len(masks) + 1] = label
            masks.append(mask)
            boxes.append(box)
    if not masks:
        return image.copy()
    drawn = {
        "object_ids": torch.arange(1, len(masks) + 1),
        "masks": torch.stack(masks),
        "boxes": torch.stack(boxes).float(),
    }
    return _draw(run, image, drawn, label_of)


def _overlay_source(row):
    """``(file_id, t_ms, kind)``, as ``curio_derived_file`` takes them, of
    the file an overlay of *row*'s image is derived from: a collection's image
    or frame itself, or, for a frame a node sampled from a video
    (``<videoId>@<t_ms>``), that video at that time. None for any other
    derived file, which gets no overlay. Segmentation's rule, which a test
    holds this one to."""
    file_id = str(row["file_id"])
    sampled = _DERIVED_ID_RE.match(file_id)
    if sampled is None:
        return file_id, 0, "image"
    video, t_ms, tag, ext = sampled.groups()
    if row.get("kind") == "frame" and tag is None and ext is None:
        return video, int(t_ms), "video"
    return None


def _tag(labels, threshold, width):
    """The tag of an image's overlay: ``TAG``, then the first twelve hex digits
    of the SHA-256 of what the overlay depends on besides its image: the
    labels, the threshold and the width."""
    asked = [list(labels), float(threshold), int(width)]
    return TAG + hashlib.sha256(json.dumps(asked, separators=(",", ":")).encode("utf-8")).hexdigest()[:12]
