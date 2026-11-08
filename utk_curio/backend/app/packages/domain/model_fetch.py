"""A model package's ``fetch`` block: weights its operator downloads, which never ship.

A model package whose weights stay out of git and the pip package (too big for
them, or gated by their publisher's terms) names them in its ``model`` block's
``fetch``, and ships without them:

- ``huggingface``: the repository on Hugging Face, ``<owner>/<name>``;
- ``revision``: the commit the files are read at, its full 40-digit hash;
- ``files``: each file, by its ``path`` in the repository, with the digest
  Hugging Face's model API lists for it: ``sha256`` for a file stored with Git
  LFS, ``gitSha1`` (the git blob hash) for any other.

The files land in the package's entry folder, ``models/<name>/``, a
Transformers checkpoint. ``scripts/fetch_model_weights.py`` downloads them
there, or into ``<folder>/<package id>@<major>/models/<name>/`` for the folder
``--model-weights-dir`` names (:func:`fetched_root`), where Curio then reads
them in place.

This module imports nothing but the standard library: the fetch script reads
it by its path, on a host that may hold no Curio dependencies.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

#: The folder of a model package that holds its weights.
MODELS_DIR = "models"
#: The runtime whose entry is a folder the files land in.
FETCHED_RUNTIME = "transformers"

#: The most files a block may list, and the longest path.
MAX_FILES = 1024
MAX_PATH_LENGTH = 512

_KEYS = frozenset({"huggingface", "revision", "files"})
_HEX = frozenset("0123456789abcdef")
#: One part of a Hugging Face repository id: letters, digits, ``-``, ``_``
#: and ``.``, neither starting nor ending with ``-`` or ``.``.
_REPO_PART = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]{0,94}[A-Za-z0-9])?$")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


class ModelFetchError(ValueError):
    """A ``fetch`` block that cannot be read; the model block's parser names where."""


@dataclass(frozen=True)
class FetchedFile:
    """One file of a ``fetch`` block: its path in the repository and its
    digest, ``sha256`` or ``git_sha1``, lowercase hex."""

    path: str
    sha256: str | None = None
    git_sha1: str | None = None


@dataclass(frozen=True)
class ModelFetch:
    huggingface: str
    revision: str
    files: tuple[FetchedFile, ...]


def is_commit(value: object) -> bool:
    """A full commit hash: 40 lowercase hexadecimal digits."""
    return isinstance(value, str) and len(value) == 40 and set(value) <= _HEX


def _is_hex(value: object, length: int) -> bool:
    return isinstance(value, str) and len(value) == length and set(value.lower()) <= _HEX


def _repository(value: object) -> str:
    parts = value.split("/") if isinstance(value, str) else []
    if len(parts) != 2 or not all(
        _REPO_PART.match(part) and "--" not in part and ".." not in part for part in parts
    ):
        raise ModelFetchError("huggingface must name a repository on Hugging Face, <owner>/<name>")
    return value


def _path(value: object) -> str:
    """A file's path in the repository: relative, ``/``-separated, with no
    ``..``, no part that starts with a dot, and no control character."""
    text = value if isinstance(value, str) else ""
    parts = text.split("/")
    if (
        not text or len(text) > MAX_PATH_LENGTH or "\\" in text or _CONTROL.search(text)
        or PurePosixPath(text).is_absolute()
        or any(not part or part.startswith(".") for part in parts)
    ):
        raise ModelFetchError(
            f"each file's path is relative, with no '..' and no part that starts with a dot, not {value!r}"
        )
    return text


def _file(raw: object) -> FetchedFile:
    if not isinstance(raw, dict) or "path" not in raw or set(raw) - {"path", "sha256", "gitSha1"}:
        raise ModelFetchError("each file is an object with a path and its sha256 or its gitSha1")
    path = _path(raw["path"])
    sha256, git_sha1 = raw.get("sha256"), raw.get("gitSha1")
    if (sha256 is None) == (git_sha1 is None):
        raise ModelFetchError(f"{path} names one digest: sha256 for a Git LFS file, gitSha1 for any other")
    if sha256 is not None and not _is_hex(sha256, 64):
        raise ModelFetchError(f"{path}: sha256 is 64 hexadecimal digits")
    if git_sha1 is not None and not _is_hex(git_sha1, 40):
        raise ModelFetchError(f"{path}: gitSha1 is 40 hexadecimal digits")
    return FetchedFile(
        path=path,
        sha256=sha256.lower() if sha256 is not None else None,
        git_sha1=git_sha1.lower() if git_sha1 is not None else None,
    )


def parse_fetch(raw: object) -> ModelFetch:
    """A checked :class:`ModelFetch` from *raw*, a model block's ``fetch``."""
    if not isinstance(raw, dict) or set(raw) - _KEYS:
        raise ModelFetchError(f"must be an object of {sorted(_KEYS)}")
    repository = _repository(raw.get("huggingface"))
    revision = raw.get("revision")
    if not is_commit(revision):
        raise ModelFetchError("revision must be a full commit hash, 40 lowercase hexadecimal digits")
    listed = raw.get("files")
    if not isinstance(listed, list) or not 0 < len(listed) <= MAX_FILES:
        raise ModelFetchError(f"files must list 1 to {MAX_FILES} files")
    files = tuple(_file(item) for item in listed)
    paths = [item.path for item in files]
    if len(set(paths)) != len(paths):
        raise ModelFetchError("files lists a path twice")
    folders = {"/".join(path.split("/")[:end]) for path in paths for end in range(1, path.count("/") + 1)}
    clash = sorted(folders & set(paths))
    if clash:
        raise ModelFetchError(f"files lists {clash[0]} as a file and as the folder of another")
    return ModelFetch(huggingface=repository, revision=revision, files=files)


def check_fetched_entry(entry: str, runtime: str) -> None:
    """Refuse an entry the fetched files cannot land in: a fetched model is a
    Transformers checkpoint, whose entry is a folder directly under
    ``models/``."""
    if runtime != FETCHED_RUNTIME:
        raise ModelFetchError(f"fetch fills a checkpoint folder: the model's runtime is {FETCHED_RUNTIME}")
    parts = entry.split("/")
    if len(parts) != 2 or parts[0] != MODELS_DIR or not parts[1] or parts[1].startswith("."):
        raise ModelFetchError(
            f"the entry of a fetched model is a folder directly under {MODELS_DIR}/, such as {MODELS_DIR}/checkpoint"
        )


def fetch_dict(fetch: ModelFetch) -> dict:
    """*fetch* as a manifest holds it."""
    files = []
    for item in fetch.files:
        entry = {"path": item.path}
        if item.sha256 is not None:
            entry["sha256"] = item.sha256
        else:
            entry["gitSha1"] = item.git_sha1
        files.append(entry)
    return {"huggingface": fetch.huggingface, "revision": fetch.revision, "files": files}


def fetched_root(weights_dir, package_id: str, major: int) -> Path:
    """The folder of ``--model-weights-dir`` (*weights_dir*) that holds the
    fetched weights of package *package_id* at *major*, laid out as the
    package's own folder: its entry, ``models/<name>/``, is under it."""
    return Path(weights_dir) / f"{package_id}@{major}"
