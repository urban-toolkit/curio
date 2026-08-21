"""Regression tests for JSON artifact serialization hardening.

list/dict artifacts used to be written with ``json.dumps`` defaults
(``allow_nan=True``), emitting bare ``NaN`` / ``Infinity`` tokens. Python's
lenient ``json.loads`` round-trips those, but they are *invalid* JSON: the
browser's strict parser (and any published bundle ``.json`` part derived from the
artifact) rejects them, breaking the dataset catalog preview. The writer now
scrubs non-finite floats to ``null`` and forbids NaN/Infinity at dump time.
"""
from __future__ import annotations

import json
import math
import zlib

import numpy as np

from utk_curio.sandbox.util.parsers import (
    _json_artifact_rel_path,
    _json_safe_value,
    _read_json_artifact,
    _write_json_artifact,
)


def test_json_safe_value_scrubs_non_finite():
    value = {
        "finite": [1.0, -2.5, 0.0],
        "nan": float("nan"),
        "inf": float("inf"),
        "ninf": float("-inf"),
        "nested": [[float("nan"), 3.0], {"x": float("inf")}],
        "np_f64_nan": np.float64("nan"),
        "np_f32_nan": np.float32("nan"),
        "np_f32_finite": np.float32(1.5),
        "str": "NaN-looking string stays",
        "int": 7,
        "none": None,
    }
    safe = _json_safe_value(value)

    assert safe["finite"] == [1.0, -2.5, 0.0]
    assert safe["nan"] is None
    assert safe["inf"] is None
    assert safe["ninf"] is None
    assert safe["nested"] == [[None, 3.0], {"x": None}]
    assert safe["np_f64_nan"] is None
    assert safe["np_f32_nan"] is None
    assert safe["np_f32_finite"] == 1.5
    assert safe["str"] == "NaN-looking string stays"
    assert safe["int"] == 7
    assert safe["none"] is None

    # The whole result must serialize under the STRICT parser the browser uses.
    json.dumps(safe, allow_nan=False)


def test_write_json_artifact_emits_strict_valid_json(tmp_path, monkeypatch):
    monkeypatch.setenv("CURIO_LAUNCH_CWD", str(tmp_path))
    monkeypatch.setenv("CURIO_SHARED_DATA", "./.curio/data/")

    value = [[float("nan"), 39.2, float("inf")], [1.0, float("-inf"), 2.0]]
    rel_path = _write_json_artifact("art_nan", value)

    # The bytes on disk must be strict-valid JSON (no bare NaN/Infinity tokens).
    full_path = (tmp_path / ".curio" / "data" / rel_path).resolve()
    raw = zlib.decompress(full_path.read_bytes()).decode("utf-8")
    assert "NaN" not in raw and "Infinity" not in raw
    json.loads(raw)  # strict parse must not raise

    # Round-trip preserves finite values and nulls the non-finite ones.
    loaded = _read_json_artifact(_json_artifact_rel_path("art_nan"))
    assert loaded == [[None, 39.2, None], [1.0, None, 2.0]]
