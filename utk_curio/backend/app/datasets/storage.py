"""On-disk layout helpers for the dataset catalog and per-user dataset store.

Layout (anchored on ``CURIO_LAUNCH_CWD``)::

    <repo_root>/datasets/
      <datasetId>@<major>/
        manifest.json
        integrity.json   (optional)
        data/            (payload files referenced by manifest)

    .curio/
      users/
        <user_key>/
          datasets/
            <datasetId>@<major>/
              manifest.json
              data/...

The shared catalog at ``<repo_root>/datasets/`` is the install source (like
``<repo_root>/packages/`` for node packs). Installing copies a dataset into
the user's store and records a reference on the dataflow.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from utk_curio.backend.app.common.safe_paths import (
    PathTraversalError,
    is_within,
    validate_component,
)


DATASET_DIR_RE = re.compile(
    r"^[a-z][a-z0-9-]{0,62}(?:\.[a-z][a-z0-9-]{0,62}){1,5}@(?:0|[1-9][0-9]{0,3})$"
)


class DatasetIdError(ValueError):
    """Raised when a dataset directory name fails validation."""


@dataclass(frozen=True)
class DatasetId:
    dataset_id: str
    major: int

    @classmethod
    def parse_dir(cls, dir_name: str) -> "DatasetId":
        if not isinstance(dir_name, str) or not DATASET_DIR_RE.match(dir_name):
            raise DatasetIdError(
                f"invalid dataset directory name: {dir_name!r}; expected "
                f"'<datasetId>@<major>' matching {DATASET_DIR_RE.pattern}"
            )
        dataset_id, major_str = dir_name.rsplit("@", 1)
        return cls(dataset_id=dataset_id, major=int(major_str))

    @property
    def dir_name(self) -> str:
        return f"{self.dataset_id}@{self.major}"


def _launch_dir() -> Path:
    return Path(os.environ.get("CURIO_LAUNCH_CWD", os.getcwd()))


def _users_base() -> Path:
    return (_launch_dir() / ".curio" / "users").resolve()


_GUEST_KEY = "guest"


def _user_key_segment(user_key: str) -> str:
    if user_key == _GUEST_KEY or user_key.isdigit():
        return user_key
    raise ValueError(f"Invalid user key for storage: {user_key!r}")


def catalog_root() -> Path:
    """Return ``<repo_root>/datasets/`` — committed Data Hub catalog root."""
    # storage.py -> datasets/ -> app/ -> backend/ -> utk_curio/ -> repo_root/datasets/
    return Path(__file__).resolve().parents[4] / "datasets"


def user_datasets_dir(user_key: str) -> Path:
    """Return ``.../users/<user_key>/datasets/``."""
    return _users_base() / _user_key_segment(user_key) / "datasets"


def dataset_dir(user_key: str, dataset_dir_name: str) -> Path:
    """Resolve a single ``<datasetId>@<major>`` under a user's dataset store."""
    DatasetId.parse_dir(dataset_dir_name)
    base = user_datasets_dir(user_key).resolve()
    target = (base / dataset_dir_name).resolve()
    if not is_within(target, base):
        raise PathTraversalError(
            f"Path traversal blocked: dataset path {target!s} escapes base {base!s}"
        )
    return target


def dataset_asset_path(
    user_key: str,
    dataset_dir_name: str,
    *subpath: str,
    field: str = "dataset asset",
) -> Path:
    ddir = dataset_dir(user_key, dataset_dir_name).resolve()
    for seg in subpath:
        validate_component(seg, field=field)
    target = ddir.joinpath(*subpath).resolve()
    if not is_within(target, ddir):
        raise PathTraversalError(
            f"Path traversal blocked: {field} {target!s} escapes dataset {ddir!s}"
        )
    return target


def list_user_datasets(user_key: str) -> list[Path]:
    base = user_datasets_dir(user_key)
    if not base.is_dir():
        return []
    out: list[Path] = []
    for entry in sorted(base.iterdir()):
        if not entry.is_dir():
            continue
        if not DATASET_DIR_RE.match(entry.name):
            continue
        out.append(entry.resolve())
    return out


def list_catalog_datasets() -> list[Path]:
    root = catalog_root()
    if not root.is_dir():
        return []
    out: list[Path] = []
    for entry in sorted(root.iterdir()):
        if not entry.is_dir():
            continue
        if not DATASET_DIR_RE.match(entry.name):
            continue
        if not (entry / "manifest.json").is_file():
            continue
        out.append(entry.resolve())
    return out
