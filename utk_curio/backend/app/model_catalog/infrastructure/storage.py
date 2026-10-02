"""Where models are on disk.

Laid out as the Data Catalog lays out datasets::

    <repo_root>/models/                 the models Curio ships
      <modelId>@<major>/
        manifest.json
        LICENSE
        files/...

    .curio/users/<user_key>/models/     the models a person downloaded
      <modelId>@<major>/...

A shipped model is used where it is, as a shipped dataset is read where it
is: nothing is copied to use one. ``CURIO_MODELS_ROOT`` moves the shipped
root, as ``CURIO_CATALOG_ROOT`` moves the datasets'.
"""

from __future__ import annotations

import os
from pathlib import Path

from utk_curio.backend.app.common.safe_paths import PathTraversalError, is_within
from utk_curio.backend.app.common.user_storage import user_key_segment, users_base
from utk_curio.backend.app.datasets.infrastructure.storage import DATASET_DIR_RE

#: A model's folder name: ``<modelId>@<major>``, the datasets' grammar.
MODEL_DIR_RE = DATASET_DIR_RE

ENV_ROOT = "CURIO_MODELS_ROOT"


def models_root() -> Path:
    """The shipped models: ``<repo_root>/models``, or ``CURIO_MODELS_ROOT``."""
    override = os.environ.get(ENV_ROOT)
    if override and override.strip():
        return Path(override).expanduser().resolve()
    # storage.py -> infrastructure/ -> model_catalog/ -> app/ -> backend/ -> utk_curio/ -> repo_root/
    return Path(__file__).resolve().parents[5] / "models"


def user_models_dir(user_key: str) -> Path:
    return users_base() / user_key_segment(user_key) / "models"


def user_model_dir(user_key: str, dir_name: str) -> Path:
    """One downloaded model's folder, contained in the user's store."""
    if not MODEL_DIR_RE.match(dir_name or ""):
        raise PathTraversalError(f"not a model folder name: {dir_name!r}")
    base = user_models_dir(user_key).resolve()
    target = (base / dir_name).resolve()
    if not is_within(target, base):
        raise PathTraversalError(f"model folder {target} escapes {base}")
    return target


def _folders(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    return [
        entry.resolve()
        for entry in sorted(root.iterdir())
        if entry.is_dir() and MODEL_DIR_RE.match(entry.name) and (entry / "manifest.json").is_file()
    ]


def list_shipped_models() -> list[Path]:
    return _folders(models_root())


def list_user_models(user_key: str) -> list[Path]:
    return _folders(user_models_dir(user_key))
