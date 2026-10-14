"""A model package's ``model`` block: how to run the weights it ships under ``models/``.

A package of kind ``model`` is a node package whose manifest carries this
block (``docs/schemas/node-package.v4.json``, ``$defs.model``). The package's
own ``license`` is its code's; the block's ``license`` is the weights':

- ``type``: ``semantic-segmentation``, one label per pixel; ``image-to-image``,
  images in and an image out; or ``node-regression``, a graph in (node
  features and edges) and values for each node out. The node that runs an
  ``image-to-image`` or ``node-regression`` model feeds it itself
  (``CurioModel.run``);
- ``runtime``: ``onnx`` (one ``.onnx`` file, with any external data beside it)
  or ``transformers`` (a checkpoint folder ``from_pretrained`` reads);
- ``entry``: the ``.onnx`` file, or the checkpoint folder, under ``models/``;
- ``input``: an ONNX image model's input, ``width`` x ``height`` in ``NCHW``
  (or ``NHWC``, for an ``image-to-image`` model), as ``uint8`` pixels or as
  ``float32`` scaled by ``scale`` and then normalized by ``mean`` and ``std``;
  a ``node-regression`` model reads a graph of any size and has none;
- ``labels``: the class of each output channel (a Transformers checkpoint may
  leave them to its ``config.json``); an ``image-to-image`` or
  ``node-regression`` model has none;
- ``sizeBytes``, ``discoverySource`` (where a downloaded model came from), and
  the weights' ``license``, ``licenseFile``, ``publisher`` and ``homepage``.

The Model Catalog shows these fields for each model package.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

#: The kinds of package: a node package, or a model package with its weights.
KINDS = ("node", "model")
#: The folder of a model package that holds its weights.
MODELS_DIR = "models"

RUNTIMES = ("onnx", "transformers")
TYPES = ("semantic-segmentation", "image-to-image", "node-regression")
#: The types whose ONNX models read an image of the block's ``input`` size.
IMAGE_TYPES = ("semantic-segmentation", "image-to-image")
INPUT_DTYPES = ("uint8", "float32")
INPUT_LAYOUTS = ("NCHW", "NHWC")

#: The most labels a model may name, and the longest one.
MAX_LABELS = 1024
MAX_LABEL_LENGTH = 80

#: Keys a ``discoverySource`` block may hold, and its values' length, as the
#: Data Catalog bounds its own.
MAX_SOURCE_KEYS = 16
MAX_SOURCE_VALUE = 512


class ModelBlockError(ValueError):
    """A ``model`` block that cannot be read; the manifest parser names where."""


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
class ModelBlock:
    type: str
    runtime: str
    entry: str
    license: str
    input: ModelInput | None = None
    labels: tuple[str, ...] = ()
    size_bytes: int = 0
    discovery_source: dict[str, Any] | None = None
    license_file: str | None = None
    publisher: str = ""
    homepage: str | None = None


def _text(raw: dict, key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ModelBlockError(f"{key} must be a non-empty string")
    return value.strip()


def _relpath(value: object, key: str) -> str:
    """A path inside the package: relative, no ``..``, no backslash."""
    if not isinstance(value, str) or not value.strip():
        raise ModelBlockError(f"{key} must be a path inside the package")
    text = value.strip()
    if PurePosixPath(text).is_absolute() or "\\" in text or any(part in ("", "..", ".") for part in text.split("/")):
        raise ModelBlockError(f"{key} must be a path inside the package")
    return text


def _entry(value: object, runtime: str) -> str:
    text = value.strip() if isinstance(value, str) else ""
    parts = text.split("/")
    if (
        len(parts) < 2 or parts[0] != MODELS_DIR or "\\" in text
        or any(part in ("", ".", "..") for part in parts)
    ):
        raise ModelBlockError(f"entry must be a path under {MODELS_DIR}/, such as {MODELS_DIR}/model.onnx")
    if runtime == "onnx" and not text.endswith(".onnx"):
        raise ModelBlockError("an onnx model's entry is its .onnx file")
    return text


def _triple(raw: dict, key: str):
    value = raw.get(key)
    if value is None:
        return None
    if not isinstance(value, list) or len(value) != 3 or not all(
        isinstance(v, (int, float)) and not isinstance(v, bool) for v in value
    ):
        raise ModelBlockError(f"input.{key} must list three numbers")
    return tuple(float(v) for v in value)


def _input(raw: object) -> ModelInput:
    if not isinstance(raw, dict):
        raise ModelBlockError("input must be an object")
    try:
        width, height = int(raw["width"]), int(raw["height"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ModelBlockError("input needs a whole width and height") from exc
    if not (8 <= width <= 8192 and 8 <= height <= 8192):
        raise ModelBlockError("input width and height are 8 to 8192 pixels")
    dtype = raw.get("dtype", "float32")
    if dtype not in INPUT_DTYPES:
        raise ModelBlockError(f"input.dtype must be one of {list(INPUT_DTYPES)}")
    layout = raw.get("layout", "NCHW")
    if layout not in INPUT_LAYOUTS:
        raise ModelBlockError(f"input.layout must be one of {list(INPUT_LAYOUTS)}")
    scale = raw.get("scale", 1.0)
    if isinstance(scale, bool) or not isinstance(scale, (int, float)) or scale <= 0:
        raise ModelBlockError("input.scale must be a positive number")
    std = _triple(raw, "std")
    if std is not None and any(v == 0 for v in std):
        raise ModelBlockError("input.std may not hold a zero")
    return ModelInput(width=width, height=height, dtype=dtype, layout=layout, scale=float(scale),
                      mean=_triple(raw, "mean"), std=std)


def _labels(raw: object) -> tuple[str, ...]:
    labels = raw if raw is not None else []
    if not isinstance(labels, list) or len(labels) > MAX_LABELS or not all(
        isinstance(label, str) and 0 < len(label.strip()) <= MAX_LABEL_LENGTH for label in labels
    ):
        raise ModelBlockError(f"labels must list up to {MAX_LABELS} short names")
    return tuple(label.strip() for label in labels)


def _discovery_source(raw: object) -> dict[str, Any] | None:
    if raw is None:
        return None
    if not isinstance(raw, dict) or len(raw) > MAX_SOURCE_KEYS:
        raise ModelBlockError(f"discoverySource holds up to {MAX_SOURCE_KEYS} keys")
    for key, value in raw.items():
        if len(json.dumps(value, default=str)) > MAX_SOURCE_VALUE:
            raise ModelBlockError(f"discoverySource.{key} is too long")
    return dict(raw) or None


def parse_model_block(raw: object) -> ModelBlock:
    """A checked :class:`ModelBlock` from *raw*, a manifest's ``model`` object."""
    if not isinstance(raw, dict):
        raise ModelBlockError("must be an object")
    model_type = _text(raw, "type")
    if model_type not in TYPES:
        raise ModelBlockError(f"type must be one of {list(TYPES)}")
    runtime = _text(raw, "runtime")
    if runtime not in RUNTIMES:
        raise ModelBlockError(f"runtime must be one of {list(RUNTIMES)}")
    entry = _entry(raw.get("entry"), runtime)
    labels = _labels(raw.get("labels"))
    if runtime == "onnx" and model_type == "semantic-segmentation" and not labels:
        raise ModelBlockError("an onnx segmentation model names its labels, one per output channel")
    if runtime == "onnx" and model_type in IMAGE_TYPES:
        model_input = _input(raw.get("input"))
    else:
        model_input = _input(raw["input"]) if raw.get("input") is not None else None
    if model_input is not None and model_input.layout != "NCHW" and model_type != "image-to-image":
        raise ModelBlockError("input.layout must be NCHW for this type")
    license_text = raw.get("license")
    if not isinstance(license_text, str) or not license_text.strip():
        raise ModelBlockError("license must be the weights' license, a non-empty string")
    license_file = raw.get("licenseFile")
    if license_file is not None:
        license_file = _relpath(license_file, "licenseFile")
    size = raw.get("sizeBytes", 0)
    if isinstance(size, bool) or not isinstance(size, int) or size < 0:
        raise ModelBlockError("sizeBytes must be a whole number of bytes")
    publisher = raw.get("publisher", "")
    if not isinstance(publisher, str):
        raise ModelBlockError("publisher must be a string")
    homepage = raw.get("homepage")
    if homepage is not None and not (isinstance(homepage, str) and homepage.startswith("https://")):
        raise ModelBlockError("homepage must be an https link")
    return ModelBlock(
        type=model_type, runtime=runtime, entry=entry, license=license_text.strip(), input=model_input,
        labels=labels, size_bytes=size, discovery_source=_discovery_source(raw.get("discoverySource")),
        license_file=license_file, publisher=publisher.strip(), homepage=homepage,
    )


def model_block_dict(block: ModelBlock) -> dict[str, Any]:
    """*block* as a manifest holds it, which is also how the wire carries it."""
    out: dict[str, Any] = {
        "type": block.type,
        "runtime": block.runtime,
        "entry": block.entry,
        "labels": list(block.labels),
        "sizeBytes": block.size_bytes,
        "license": block.license,
        "publisher": block.publisher,
    }
    if block.input is not None:
        spec = block.input
        out["input"] = {"width": spec.width, "height": spec.height, "dtype": spec.dtype,
                        "layout": spec.layout, "scale": spec.scale}
        if spec.mean is not None:
            out["input"]["mean"] = list(spec.mean)
        if spec.std is not None:
            out["input"]["std"] = list(spec.std)
    if block.license_file:
        out["licenseFile"] = block.license_file
    if block.homepage:
        out["homepage"] = block.homepage
    if block.discovery_source:
        out["discoverySource"] = dict(block.discovery_source)
    return out
