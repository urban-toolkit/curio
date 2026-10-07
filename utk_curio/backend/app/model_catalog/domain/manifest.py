"""A model's manifest: what it is, how to feed it, and what it answers.

A model is a folder, ``<modelId>@<major>/``, holding ``manifest.json``, its
files under ``files/`` and its license text. The manifest says everything a
node needs to run it, so the node hard-codes nothing:

- ``runtime``: ``onnx`` (one ``.onnx`` file, with any external data next to
  it) or ``transformers`` (a checkpoint folder ``from_pretrained`` reads);
- ``task``: ``semantic-segmentation``, one label per pixel,
  ``image-to-image``, images in and an image out, or ``node-regression``, a
  graph in (node features and edges) and values for each node out; the node
  that runs an ``image-to-image`` or ``node-regression`` model feeds it
  itself (``CurioModel.run``);
- ``entry``: the ``.onnx`` file, or the checkpoint folder, under the model's
  folder;
- ``labels``: the class of each output channel (a Transformers checkpoint
  may leave them to its ``config.json``); an ``image-to-image`` or
  ``node-regression`` model has none;
- ``input``: an ONNX image model's input (a ``node-regression`` model reads
  a graph of any size, so it has none), ``width`` x ``height`` in ``NCHW`` (or
  ``NHWC``, for an ``image-to-image`` model), as ``uint8`` pixels or as
  ``float32`` scaled by ``scale`` and then normalized by ``mean`` and ``std``;
- ``license``, and ``licenseFile`` for its text: required, since a model is
  someone's work.

A model from the Discovery Catalog also carries ``discoverySource``, where it
came from, as a dataset does, and ``dependencies.python``, the libraries its
runtime needs, declared as a package declares them and installed by the same
path when the model is added.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from utk_curio.backend.app.datasets.infrastructure.storage import DATASET_ID_RE

RUNTIMES = ("onnx", "transformers")
TASKS = ("semantic-segmentation", "image-to-image", "node-regression")
#: The tasks whose ONNX models read an image of the manifest's ``input`` size.
IMAGE_TASKS = ("semantic-segmentation", "image-to-image")
INPUT_DTYPES = ("uint8", "float32")
INPUT_LAYOUTS = ("NCHW", "NHWC")

#: The most labels a model may name, and the longest one.
MAX_LABELS = 1024
MAX_LABEL_LENGTH = 80

#: Keys a ``discoverySource`` block may hold, and its values' length, as the
#: Data Catalog bounds its own.
MAX_SOURCE_KEYS = 16
MAX_SOURCE_VALUE = 512

_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
_LIBRARY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


class ModelManifestError(ValueError):
    """A model manifest that cannot be read."""


@dataclass(frozen=True)
class ModelInput:
    width: int
    height: int
    dtype: str = "float32"
    layout: str = "NCHW"
    scale: float = 1.0
    mean: tuple[float, float, float] | None = None
    std: tuple[float, float, float] | None = None


@dataclass(frozen=True)
class ModelManifest:
    id: str
    major: int
    name: str
    version: str
    runtime: str
    task: str
    entry: str
    license: str
    description: str = ""
    publisher: str = ""
    homepage: str | None = None
    license_file: str | None = None
    labels: tuple[str, ...] = ()
    input: ModelInput | None = None
    tags: tuple[str, ...] = ()
    size_bytes: int = 0
    discovery_source: dict[str, Any] | None = None
    #: ``{library: version spec}``: what the runtime needs installed.
    python_deps: dict[str, str] = field(default_factory=dict)
    created_at: str | None = None
    updated_at: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def dir_name(self) -> str:
        return f"{self.id}@{self.major}"


def _str(raw: dict, key: str, *, required: bool = True) -> str:
    value = raw.get(key)
    if value is None and not required:
        return ""
    if not isinstance(value, str) or (required and not value.strip()):
        raise ModelManifestError(f"model manifest {key} must be a non-empty string")
    return value.strip()


def _relpath(value: object, key: str) -> str:
    """A path inside the model's folder: relative, no ``..``, no backslash."""
    if not isinstance(value, str) or not value.strip():
        raise ModelManifestError(f"model manifest {key} must be a path inside the model's folder")
    text = value.strip()
    path = PurePosixPath(text)
    if path.is_absolute() or "\\" in text or any(part in ("", "..") for part in text.split("/")):
        raise ModelManifestError(f"model manifest {key} must be a path inside the model's folder")
    return str(path)


def _input(raw: object) -> ModelInput:
    if not isinstance(raw, dict):
        raise ModelManifestError("model manifest input must be an object")
    try:
        width, height = int(raw["width"]), int(raw["height"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ModelManifestError("model manifest input needs a whole width and height") from exc
    if not (8 <= width <= 8192 and 8 <= height <= 8192):
        raise ModelManifestError("model manifest input width and height are 8 to 8192 pixels")
    dtype = raw.get("dtype", "float32")
    if dtype not in INPUT_DTYPES:
        raise ModelManifestError(f"model manifest input.dtype must be one of {list(INPUT_DTYPES)}")
    layout = raw.get("layout", "NCHW")
    if layout not in INPUT_LAYOUTS:
        raise ModelManifestError(f"model manifest input.layout must be one of {list(INPUT_LAYOUTS)}")

    def triple(key):
        value = raw.get(key)
        if value is None:
            return None
        if not isinstance(value, list) or len(value) != 3 or not all(
            isinstance(v, (int, float)) and not isinstance(v, bool) for v in value
        ):
            raise ModelManifestError(f"model manifest input.{key} must list three numbers")
        return tuple(float(v) for v in value)

    scale = raw.get("scale", 1.0)
    if isinstance(scale, bool) or not isinstance(scale, (int, float)) or scale <= 0:
        raise ModelManifestError("model manifest input.scale must be a positive number")
    std = triple("std")
    if std is not None and any(v == 0 for v in std):
        raise ModelManifestError("model manifest input.std may not hold a zero")
    return ModelInput(width=width, height=height, dtype=dtype, layout=layout, scale=float(scale),
                      mean=triple("mean"), std=std)


def parse_manifest(raw: object, *, dir_name: str | None = None) -> ModelManifest:
    """A checked :class:`ModelManifest` from *raw*, a parsed ``manifest.json``."""
    if not isinstance(raw, dict):
        raise ModelManifestError("model manifest must be an object")
    model_id = _str(raw, "id")
    if not DATASET_ID_RE.match(model_id):
        raise ModelManifestError(f"model manifest id {model_id!r} is not a model id (dotted lowercase names)")
    try:
        major = int((raw.get("compatibility") or {}).get("major"))
    except (TypeError, ValueError) as exc:
        raise ModelManifestError("model manifest compatibility.major must be a whole number") from exc
    if dir_name is not None and dir_name != f"{model_id}@{major}":
        raise ModelManifestError(f"a model's folder is named <id>@<major>; {dir_name!r} holds {model_id}@{major}")
    version = _str(raw, "version")
    if not _VERSION_RE.match(version):
        raise ModelManifestError("model manifest version must look like 1.0.0")
    runtime = _str(raw, "runtime")
    if runtime not in RUNTIMES:
        raise ModelManifestError(f"model manifest runtime must be one of {list(RUNTIMES)}")
    task = _str(raw, "task")
    if task not in TASKS:
        raise ModelManifestError(f"model manifest task must be one of {list(TASKS)}")
    entry = _relpath(raw.get("entry"), "entry")
    if runtime == "onnx" and not entry.endswith(".onnx"):
        raise ModelManifestError("an onnx model's entry is its .onnx file")

    labels_raw = raw.get("labels") or []
    if not isinstance(labels_raw, list) or len(labels_raw) > MAX_LABELS or not all(
        isinstance(label, str) and 0 < len(label.strip()) <= MAX_LABEL_LENGTH for label in labels_raw
    ):
        raise ModelManifestError(f"model manifest labels must list up to {MAX_LABELS} short names")
    labels = tuple(label.strip() for label in labels_raw)
    if runtime == "onnx" and task == "semantic-segmentation" and not labels:
        raise ModelManifestError("an onnx model names its labels, one per output channel")
    model_input = _input(raw.get("input")) if runtime == "onnx" and task in IMAGE_TASKS else (
        _input(raw["input"]) if raw.get("input") is not None else None
    )
    if model_input is not None and model_input.layout != "NCHW" and task != "image-to-image":
        raise ModelManifestError("model manifest input.layout must be NCHW for this task")

    license_text = _str(raw, "license")
    license_file = raw.get("licenseFile")
    if license_file is not None:
        license_file = _relpath(license_file, "licenseFile")

    source = raw.get("discoverySource")
    if source is not None:
        if not isinstance(source, dict) or len(source) > MAX_SOURCE_KEYS:
            raise ModelManifestError(f"model manifest discoverySource holds up to {MAX_SOURCE_KEYS} keys")
        for key, value in source.items():
            if len(json.dumps(value, default=str)) > MAX_SOURCE_VALUE:
                raise ModelManifestError(f"model manifest discoverySource.{key} is too long")

    dependencies = raw.get("dependencies") or {}
    python_deps = dependencies.get("python") if isinstance(dependencies, dict) else None
    python_deps = python_deps or {}
    if not isinstance(python_deps, dict) or not all(
        isinstance(name, str) and _LIBRARY_RE.match(name) and isinstance(spec, str) and len(spec) <= 64
        for name, spec in python_deps.items()
    ):
        raise ModelManifestError("model manifest dependencies.python maps library names to version specs")

    tags = raw.get("tags") or []
    if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
        raise ModelManifestError("model manifest tags must be a list of strings")
    size = raw.get("sizeBytes", 0)
    if isinstance(size, bool) or not isinstance(size, int) or size < 0:
        raise ModelManifestError("model manifest sizeBytes must be a whole number of bytes")
    homepage = raw.get("homepage")
    if homepage is not None and not (isinstance(homepage, str) and homepage.startswith("https://")):
        raise ModelManifestError("model manifest homepage must be an https link")

    known = {
        "id", "name", "version", "compatibility", "description", "publisher", "homepage", "license",
        "licenseFile", "runtime", "task", "entry", "labels", "input", "tags", "sizeBytes",
        "discoverySource", "dependencies", "createdAt", "updatedAt",
    }
    return ModelManifest(
        id=model_id, major=major, name=_str(raw, "name"), version=version, runtime=runtime, task=task,
        entry=entry, license=license_text, description=_str(raw, "description", required=False),
        publisher=_str(raw, "publisher", required=False), homepage=homepage, license_file=license_file,
        labels=labels, input=model_input, tags=tuple(tags), size_bytes=size,
        discovery_source=dict(source) if source else None, python_deps=dict(python_deps),
        created_at=raw.get("createdAt"), updated_at=raw.get("updatedAt"),
        extra={k: v for k, v in raw.items() if k not in known},
    )


def manifest_dict(manifest: ModelManifest) -> dict[str, Any]:
    """*manifest* as ``manifest.json`` holds it."""
    out: dict[str, Any] = {
        "id": manifest.id,
        "name": manifest.name,
        "version": manifest.version,
        "compatibility": {"major": manifest.major},
        "description": manifest.description,
        "publisher": manifest.publisher,
        "license": manifest.license,
        "runtime": manifest.runtime,
        "task": manifest.task,
        "entry": manifest.entry,
        "labels": list(manifest.labels),
        "tags": list(manifest.tags),
        "sizeBytes": manifest.size_bytes,
    }
    if manifest.homepage:
        out["homepage"] = manifest.homepage
    if manifest.license_file:
        out["licenseFile"] = manifest.license_file
    if manifest.input is not None:
        spec = manifest.input
        out["input"] = {"width": spec.width, "height": spec.height, "dtype": spec.dtype,
                        "layout": spec.layout, "scale": spec.scale}
        if spec.mean is not None:
            out["input"]["mean"] = list(spec.mean)
        if spec.std is not None:
            out["input"]["std"] = list(spec.std)
    if manifest.discovery_source:
        out["discoverySource"] = dict(manifest.discovery_source)
    if manifest.python_deps:
        out["dependencies"] = {"python": dict(manifest.python_deps)}
    for key in ("created_at", "updated_at"):
        value = getattr(manifest, key)
        if value:
            out["createdAt" if key == "created_at" else "updatedAt"] = value
    return out


def load_manifest(folder: Path, *, fetched_on_first_use=None) -> ModelManifest:
    """The checked manifest of the model in *folder*, whose entry must exist.

    *fetched_on_first_use*, given the entry's path in the folder, says whether
    a missing entry is one the folder gets the first time a node runs the
    model: an ONNX entry the pip package leaves out, which a pip install
    downloads then. Such a model reads with its entry missing."""
    path = folder / "manifest.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ModelManifestError(f"{folder.name}: manifest.json could not be read ({exc})") from exc
    manifest = parse_manifest(raw, dir_name=folder.name)
    entry = folder / manifest.entry
    if manifest.runtime == "onnx" and not entry.is_file() and not (
        fetched_on_first_use is not None and fetched_on_first_use(manifest.entry)
    ):
        raise ModelManifestError(f"{folder.name}: its entry {manifest.entry} is not a file")
    if manifest.runtime == "transformers" and not (entry / "config.json").is_file():
        raise ModelManifestError(f"{folder.name}: its entry {manifest.entry} holds no config.json")
    return manifest
