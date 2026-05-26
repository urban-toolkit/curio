"""Segmentation + detection inference loop.

Iterates a list of input images (each described by ``{image_id, image_url,
local_path?, latitude?, longitude?}``), runs the chosen HuggingFace model
or YOLO detector, and yields per-image result dicts. The caller (a worker
thread in ``jobs.py``) writes each yielded dict into the in-memory job store.

All heavy ML imports (``torch``, ``transformers``, ``ultralytics``,
``PIL.Image``, ``numpy``) are lazy at function entry so this module can be
imported on a Curio install without the streetvision extras — only callers
that actually invoke ``run_segmentation`` / ``run_detection`` need them.
"""

import os
from typing import Iterator, List, Optional

from . import cache

# Cityscapes-style color palette. Keep in sync with the frontend's CLASS_COLORS
# in cvGalleryLifecycle.tsx so the overlay PNGs match the gallery legend.
CITYSCAPES_COLORS = {
    0: (74, 144, 217), 1: (231, 76, 139), 2: (46, 204, 113), 3: (189, 195, 199),
    4: (155, 89, 182), 5: (0, 188, 212), 6: (241, 196, 15), 7: (241, 196, 15),
    8: (245, 166, 35), 9: (141, 110, 99), 10: (133, 193, 233), 11: (255, 105, 180),
    12: (255, 105, 180), 13: (231, 76, 60), 14: (255, 107, 53), 15: (211, 84, 0),
    16: (127, 140, 141), 17: (192, 57, 43), 18: (26, 188, 156),
}


def run_segmentation(model, processor, image_path: str, classes: List[str], image_id: str) -> dict:
    """Run semantic segmentation on a single image; return per-class pixel ratios.

    Supports both SegFormer-style models (direct ``logits`` head) and
    Mask2Former / OneFormer-style models (``post_process_semantic_segmentation``
    is preferred when available).
    """
    import numpy as np
    import torch
    from PIL import Image as PILImage

    image = PILImage.open(image_path).convert("RGB")
    orig_w, orig_h = image.size

    inputs = processor(images=image, return_tensors="pt")
    with torch.no_grad():
        outputs = model(**inputs)

    # post_process_semantic_segmentation handles Mask2Former / OneFormer /
    # MaskFormer / SegFormer uniformly and returns a (H, W) class-id map.
    if hasattr(processor, "post_process_semantic_segmentation"):
        seg_maps = processor.post_process_semantic_segmentation(
            outputs, target_sizes=[(orig_h, orig_w)],
        )
        pred = seg_maps[0].cpu().numpy()
    elif hasattr(outputs, "logits"):
        upsampled = torch.nn.functional.interpolate(
            outputs.logits, size=(orig_h, orig_w), mode="bilinear", align_corners=False,
        )
        pred = upsampled.argmax(dim=1).squeeze().cpu().numpy()
    else:
        raise ValueError(
            f"Cannot extract semantic segmentation from outputs of type "
            f"{type(outputs).__name__} — model is not a supported semantic-seg head"
        )

    total_pixels = pred.size
    unique, counts = np.unique(pred, return_counts=True)
    id2label = getattr(model.config, "id2label", {})
    class_ratios = {}
    for cls_id, count in zip(unique, counts):
        label = id2label.get(int(cls_id), f"class_{cls_id}")
        class_ratios[label] = round(float(count / total_pixels), 4)

    overlay = np.zeros((orig_h, orig_w, 3), dtype=np.uint8)
    for cls_id in np.unique(pred):
        color = CITYSCAPES_COLORS.get(int(cls_id), (128, 128, 128))
        overlay[pred == cls_id] = color
    stem = os.path.splitext(image_id)[0]
    overlay_target = os.path.join(cache.overlays_dir(), f"{stem}_overlay.png")
    PILImage.fromarray(overlay).save(overlay_target)

    # If the caller asked for a specific class set, filter + renormalize so
    # the percentages sum to ~1 over the requested classes only.
    if classes:
        class_ratios = {k: v for k, v in class_ratios.items() if k in classes}
        total = sum(class_ratios.values())
        if total > 0:
            class_ratios = {k: round(v / total, 4) for k, v in class_ratios.items()}

    return {
        "image_id": image_id,
        "image_url": image_path,
        "class_ratios": class_ratios,
    }


def run_detection(model, image_path: str, classes: List[str], image_id: str) -> dict:
    """Run YOLO object detection on a single image."""
    results = model(image_path, verbose=False)
    result = results[0]
    detections = []
    object_counts: dict = {}
    for box in result.boxes:
        cls_id = int(box.cls[0])
        label = result.names.get(cls_id, f"class_{cls_id}")
        conf = float(box.conf[0])
        xyxy = box.xyxy[0].tolist()
        if classes and label not in classes:
            continue
        detections.append({
            "label": label,
            "confidence": round(conf, 4),
            "bbox": [round(c, 1) for c in xyxy],
        })
        object_counts[label] = object_counts.get(label, 0) + 1
    return {
        "image_id": image_id,
        "image_url": image_path,
        "detections": detections,
        "object_counts": object_counts,
    }


def run_batch(
    images: List[dict],
    model_id: str,
    model_type: str,
    classes: List[str],
    progress_cb=None,
) -> Iterator[dict]:
    """Run inference over a list of images, yielding one result dict per image.

    Args:
        images: list of ``{image_id, image_url, local_path?, latitude?, longitude?}``.
            ``local_path`` is the on-disk JPEG to feed into the model;
            ``image_url`` is the URL the frontend displays in the gallery.
        model_id: HuggingFace model id (or YOLO checkpoint path).
        model_type: ``"segmentation"`` or ``"detection"``.
        classes: list of class-label strings to filter results by (empty = all).
        progress_cb: optional callable ``(processed:int, total:int)`` invoked
            after each image. Used by ``jobs.py`` to update the job store.
    """
    from . import huggingface as hf

    cached = hf.get_cached_model(model_id)
    if cached is None:
        hf.load_model(model_id, model_type)
        cached = hf.get_cached_model(model_id)
    model, processor, _ = cached

    total = len(images)
    for i, img in enumerate(images):
        local_path: Optional[str] = img.get("local_path")
        image_id = img.get("image_id") or os.path.basename(local_path or "")
        if not local_path:
            yield {"image_id": image_id, "error": "missing local_path"}
            if progress_cb:
                progress_cb(i + 1, total)
            continue
        try:
            if model_type == "segmentation":
                result = run_segmentation(model, processor, local_path, classes, image_id)
            elif model_type == "detection":
                result = run_detection(model, local_path, classes, image_id)
            else:
                yield {"image_id": image_id, "error": f"unsupported model_type: {model_type}"}
                if progress_cb:
                    progress_cb(i + 1, total)
                continue
            # Pass through the display URL and geo info from the input.
            result["image_url"] = img.get("image_url") or result["image_url"]
            if "latitude" in img:
                result["latitude"] = img["latitude"]
            if "longitude" in img:
                result["longitude"] = img["longitude"]
            yield result
        except Exception as e:
            yield {"image_id": image_id, "error": f"{type(e).__name__}: {e}"}
        if progress_cb:
            progress_cb(i + 1, total)
