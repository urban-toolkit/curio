"""HuggingFace Hub search + lazy model loading.

`search_models` uses the lightweight `huggingface_hub` client to list public
models — no heavy ML deps. `load_model` and `get_cached_model` lazy-import
`transformers` / `ultralytics`; both raise ImportError if the streetvision
extras aren't installed, which the routes layer converts to a 503 response.
"""

import hashlib
import os
from typing import Dict, Optional, Tuple

# In-process model cache: (model_id, token fingerprint) -> (model, processor
# or None, model_type).
#
# The token is part of the key on purpose. Keyed on model_id alone, the first
# user to download a *gated* model with their own entitlement would seed a
# cache entry that every later caller hit for free, including one whose account
# had never accepted that model's licence. Fingerprinted rather than raw so the
# token is not sitting in a dict key that any traceback could print.
_model_cache: Dict[Tuple[str, str], Tuple] = {}

# Map our short task labels to HuggingFace's pipeline tag values.
TASK_MAP = {
    "segmentation": "image-segmentation",
    "detection": "object-detection",
    "classification": "image-classification",
}


def _token_fingerprint(token: Optional[str]) -> str:
    """A stable, non-reversible cache-key component for a token."""
    if not token:
        return "anon"
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]


def resolve_hf_token() -> Optional[str]:
    """The HuggingFace token for the caller: their own, else the deployment's.

    Gated models are a per-person entitlement - you accept a model's licence
    with your own HuggingFace account - so one shared operator token could not
    represent what each user is allowed to download. A user sets theirs in AI
    Settings; ``curio.py start --huggingface-token`` supplies the fallback for
    everyone else.

    Must be called from a request context: the token is captured there and
    handed down, because model loading runs on a detached worker thread where
    ``g`` is gone.
    """
    try:
        from utk_curio.backend.app.users.dependencies import get_current_user

        user = get_current_user()
    except Exception:
        # No request context, no auth tables, or an expired session: fall back
        # rather than failing a search the deployment token can still answer.
        user = None
    own = getattr(user, "huggingface_token", None) if user is not None else None
    if own:
        return own
    return os.environ.get("CURIO_DEFAULT_HUGGINGFACE_TOKEN") or None


def _model_cache_dir() -> str:
    """Return the on-disk HuggingFace Hub model cache root.

    Defaults to ``$CURIO_LAUNCH_CWD/.curio/streetvision/model_cache`` so
    Curio's runtime state lives in the standard ``.curio/`` location —
    gitignored, easy to clear, and matches the convention used by the
    per-user package store + the SQLite DB. Override with
    ``STREETVISION_MODEL_CACHE_DIR`` for deployments that want a shared
    pre-warmed cache elsewhere.
    """
    override = os.environ.get("STREETVISION_MODEL_CACHE_DIR")
    if override:
        return override
    launch_cwd = os.environ.get("CURIO_LAUNCH_CWD") or os.getcwd()
    return os.path.join(launch_cwd, ".curio", "streetvision", "model_cache")


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


def load_model(model_id: str, model_type: str, token: Optional[str] = None) -> str:
    """Load a model into the in-process cache. Lazy-imports torch/transformers/ultralytics."""
    token = token if token is not None else resolve_hf_token()
    key = (model_id, _token_fingerprint(token))
    if key in _model_cache:
        return f"Model {model_id} already loaded (cached)"

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
        _model_cache[key] = (model, processor, model_type)

    elif model_type == "detection":
        from ultralytics import YOLO
        model = YOLO(model_id)
        _model_cache[key] = (model, None, model_type)

    elif model_type == "classification":
        from transformers import AutoImageProcessor, AutoModelForImageClassification
        processor = AutoImageProcessor.from_pretrained(model_id, token=token, cache_dir=cache_dir)
        model = AutoModelForImageClassification.from_pretrained(model_id, token=token, cache_dir=cache_dir)
        _model_cache[key] = (model, processor, model_type)

    else:
        raise ValueError(f"Unsupported model type: {model_type}")

    return f"Model {model_id} loaded successfully"


def get_cached_model(model_id: str, token: Optional[str] = None) -> Optional[Tuple]:
    """The cached entry for this model *as loaded with this token*.

    A caller with a different token misses, which is the point: a gated model
    one account is entitled to is not automatically another's to use.
    """
    return _model_cache.get((model_id, _token_fingerprint(token)))
