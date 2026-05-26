"""HuggingFace Hub search + lazy model loading.

`search_models` uses the lightweight `huggingface_hub` client to list public
models — no heavy ML deps. `load_model` and `get_cached_model` lazy-import
`transformers` / `ultralytics`; both raise ImportError if the streetvision
extras aren't installed, which the routes layer converts to a 503 response.
"""

import os
from typing import Dict, Optional, Tuple

# In-process model cache: model_id -> (model, processor_or_None, model_type)
_model_cache: Dict[str, Tuple] = {}

# Map our short task labels to HuggingFace's pipeline tag values.
TASK_MAP = {
    "segmentation": "image-segmentation",
    "detection": "object-detection",
    "classification": "image-classification",
}


def _hf_token() -> Optional[str]:
    return os.environ.get("HUGGINGFACE_TOKEN") or None


def _model_cache_dir() -> str:
    return os.environ.get("STREETVISION_MODEL_CACHE_DIR", "./model_cache")


def search_models(task: str, query: str, limit: int = 20) -> list:
    """Search HuggingFace Hub for public CV models. Returns a JSON-safe list."""
    from huggingface_hub import HfApi  # light dep; bundled with transformers

    api = HfApi()
    hf_task = TASK_MAP.get(task, task)
    models = api.list_models(
        filter=hf_task,
        search=query,
        sort="downloads",
        limit=limit,
    )
    results = []
    for m in models:
        results.append({
            "model_id": m.id,
            "name": m.id.split("/")[-1],
            "downloads": getattr(m, "downloads", None),
            "likes": getattr(m, "likes", None),
            "task": hf_task,
        })
    return results


def load_model(model_id: str, model_type: str) -> str:
    """Load a model into the in-process cache. Lazy-imports torch/transformers/ultralytics."""
    if model_id in _model_cache:
        return f"Model {model_id} already loaded (cached)"

    token = _hf_token()
    cache_dir = _model_cache_dir()

    if model_type == "segmentation":
        from transformers import AutoImageProcessor
        import transformers as _tf

        processor = AutoImageProcessor.from_pretrained(model_id, token=token, cache_dir=cache_dir)

        last_err = None
        model = None
        for auto_cls_name in (
            "AutoModelForSemanticSegmentation",
            "AutoModelForUniversalSegmentation",
            "AutoModelForInstanceSegmentation",
        ):
            auto_cls = getattr(_tf, auto_cls_name, None)
            if auto_cls is None:
                continue
            try:
                model = auto_cls.from_pretrained(model_id, token=token, cache_dir=cache_dir)
                break
            except Exception as e:
                last_err = e
                continue
        if model is None:
            raise RuntimeError(f"Could not load segmentation model {model_id}: {last_err}")
        model.eval()
        _model_cache[model_id] = (model, processor, model_type)

    elif model_type == "detection":
        from ultralytics import YOLO
        model = YOLO(model_id)
        _model_cache[model_id] = (model, None, model_type)

    elif model_type == "classification":
        from transformers import AutoImageProcessor, AutoModelForImageClassification
        processor = AutoImageProcessor.from_pretrained(model_id, token=token, cache_dir=cache_dir)
        model = AutoModelForImageClassification.from_pretrained(model_id, token=token, cache_dir=cache_dir)
        _model_cache[model_id] = (model, processor, model_type)

    else:
        raise ValueError(f"Unsupported model type: {model_type}")

    return f"Model {model_id} loaded successfully"


def get_cached_model(model_id: str) -> Optional[Tuple]:
    return _model_cache.get(model_id)
