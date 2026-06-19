"""Regression tests for review finding B6 — preview/export must honor the
parquet object-column decode sidecar (<file>.meta.json), not show/emit raw JSON.
"""
from __future__ import annotations

import json

import pandas as pd
import pytest

from utk_curio.sandbox.util import parsers


def _write_dataset(tmp_path, monkeypatch):
    monkeypatch.setattr(parsers, "_shared_data_dir", lambda: tmp_path)
    df = pd.DataFrame({"name": ["a", "b"], "tags": [{"k": "v"}, ["x", "y"]]})
    filename = parsers.save_dataset_parquet(df, "dataframe")
    assert filename is not None
    return tmp_path / filename


def test_preview_decodes_object_columns(tmp_path, monkeypatch):
    from utk_curio.sandbox.util.tabular_preview import load_parquet_frame

    path = _write_dataset(tmp_path, monkeypatch)
    frame, total = load_parquet_frame(path)
    assert total == 2
    assert frame["tags"].tolist()[0] == {"k": "v"}
    assert frame["tags"].tolist()[1] == ["x", "y"]


def test_export_csv_decodes_object_columns(tmp_path, monkeypatch):
    from utk_curio.backend.app.datasets.services.catalog_listing import (
        _serialize_parquet_for_export,
    )

    path = _write_dataset(tmp_path, monkeypatch)
    payload, ext, _mime = _serialize_parquet_for_export(path)
    assert ext == ".csv"
    text = payload.decode("utf-8")
    # The dict cell must not appear double-quoted/JSON-escaped as "{""k"":""v""}".
    assert '""' not in text
    assert "{'k': 'v'}" in text or '{"k": "v"}' in text
