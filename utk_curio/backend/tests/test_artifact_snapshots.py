"""Comparing two runs' outputs as stored, not as JSON.

``test_node_execution`` (test_frontend/test_workflows.py) runs each example
dataflow twice, once through the sandbox directly and once in the browser, and
compares every Python node's output. It read both through ``/get``'s JSON
envelope, where a list becomes one ``{"data", "dataType"}`` object per element:
example 09's grid of UTCI values took 7.3 GiB in the sandbox and 8.5 GiB in
pytest that way (#1154's runs), more than a 12 GB runner has free.
``snapshot_artifact`` reads the stored value instead, and
``artifact_differences`` compares two of them.

These pin both halves: what is read for each kind of artifact (never the JSON
envelope for a table, a list or a tuple), and that the comparison still tells
apart what the envelope told apart, with NaN equal to NaN as it had it.

Browser-free, so it lives in the unit sweep, as test_sandbox_url_resolution.py
does.
"""
from __future__ import annotations

import json
import zlib

import pyarrow as pa
import pytest
from requests.structures import CaseInsensitiveDict

from utk_curio.backend.tests.test_frontend.utils import artifact_differences, snapshot_artifact
from utk_curio.backend.tests.test_frontend.utils import sandbox as sandbox_utils

NAN = float("nan")
ARROW = "application/vnd.apache.arrow.stream"


def _table_snapshot(table, kind="dataframe", **headers):
    base = {
        "X-Curio-Kind": kind,
        "X-Curio-Rows": str(table.num_rows),
        "X-Curio-Schema": json.dumps({name: "float64" for name in table.schema.names}),
        "X-Curio-Encoded-Object-Columns": None,
        "X-Curio-Frame-Metadata": None,
    }
    return {"kind": kind, "table": table, "headers": {**base, **headers}}


# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------

def test_a_table_with_nan_in_the_same_places_matches():
    # pyarrow's own equals calls these different; the JSON envelope sent both as null.
    a = pa.table({"x": [1.0, NAN, None], "y": [2, 3, 4]})
    b = pa.table({"x": [1.0, NAN, None], "y": [2, 3, 4]})
    assert not a.equals(b)
    assert artifact_differences(_table_snapshot(a), _table_snapshot(b)) == []


def test_a_value_that_differs_is_found_and_its_column_named():
    a = pa.table({"x": [1.0, 2.0], "y": [1, 2]})
    b = pa.table({"x": [1.0, 2.0], "y": [1, 3]})
    assert artifact_differences(_table_snapshot(a), _table_snapshot(b)) == [
        "the output: the values differ in the columns ['y']"
    ]


def test_nan_against_a_number_or_a_null_differs():
    nan = pa.table({"x": [NAN]})
    assert artifact_differences(_table_snapshot(nan), _table_snapshot(pa.table({"x": [1.0]})))
    assert artifact_differences(_table_snapshot(nan), _table_snapshot(pa.table({"x": pa.array([None], pa.float64())})))


def test_the_same_rows_in_other_batches_match():
    whole = pa.table({"x": [1.0, NAN, 3.0]})
    batches = pa.Table.from_batches([
        pa.record_batch({"x": pa.array([1.0])}),
        pa.record_batch({"x": pa.array([NAN, 3.0])}),
    ])
    assert artifact_differences(_table_snapshot(batches), _table_snapshot(whole)) == []


def test_nested_values_compare_with_nan_equal_to_nan():
    a = pa.table({"x": [[1.0, NAN], [2.0]]})
    assert artifact_differences(_table_snapshot(a), _table_snapshot(pa.table({"x": [[1.0, NAN], [2.0]]}))) == []
    assert artifact_differences(_table_snapshot(a), _table_snapshot(pa.table({"x": [[1.0, NAN], [2.5]]})))


def test_columns_their_types_and_the_row_count_are_compared():
    base = pa.table({"x": [1.0, 2.0]})
    assert artifact_differences(_table_snapshot(base), _table_snapshot(pa.table({"z": [1.0, 2.0]})))
    assert artifact_differences(_table_snapshot(base), _table_snapshot(pa.table({"x": pa.array([1.0, 2.0], pa.float32())})))
    assert artifact_differences(_table_snapshot(base), _table_snapshot(pa.table({"x": [1.0, 2.0, 3.0]})))


def test_table_metadata_is_compared_as_values_not_as_bytes():
    meta = {"index_columns": [], "columns": [{"name": "x"}]}
    a = pa.table({"x": [1.0]}).replace_schema_metadata({b"pandas": json.dumps(meta)})
    reordered = pa.table({"x": [1.0]}).replace_schema_metadata(
        {b"pandas": json.dumps(dict(reversed(list(meta.items()))))}
    )
    other = pa.table({"x": [1.0]}).replace_schema_metadata(
        {b"pandas": json.dumps({**meta, "index_columns": ["i"]})}
    )
    assert artifact_differences(_table_snapshot(reordered), _table_snapshot(a)) == []
    assert artifact_differences(_table_snapshot(other), _table_snapshot(a)) == [
        "the output: the table's metadata (pandas, GeoParquet) differs"
    ]


def test_a_header_that_differs_is_named():
    table = pa.table({"x": [1.0]})
    a = _table_snapshot(table, "geodataframe", **{"X-Curio-Frame-Metadata": json.dumps({"name": "buildings"})})
    b = _table_snapshot(table, "geodataframe", **{"X-Curio-Frame-Metadata": json.dumps({"name": "parks"})})
    [line] = artifact_differences(a, b)
    assert line.startswith("the output: X-Curio-Frame-Metadata is ")


# ---------------------------------------------------------------------------
# Values, parts and kinds
# ---------------------------------------------------------------------------

def test_values_from_the_stored_row():
    assert artifact_differences({"kind": "float", "value": NAN}, {"kind": "float", "value": NAN}) == []
    assert artifact_differences({"kind": "int", "value": 2}, {"kind": "int", "value": 3}) == [
        "the output is 2, expected 3"
    ]
    assert artifact_differences({"kind": "int", "value": 2}, {"kind": "float", "value": 2.0}) == [
        "the output is a int, expected a float"
    ]


def test_parts_are_compared_one_by_one_and_named_by_place():
    table = pa.table({"x": [1.0]})
    actual = {"kind": "outputs", "parts": [{"kind": "int", "value": 1}, _table_snapshot(pa.table({"x": [2.0]}))]}
    expected = {"kind": "outputs", "parts": [{"kind": "int", "value": 1}, _table_snapshot(table)]}
    assert artifact_differences(actual, expected) == [
        "the output[1]: the values differ in the columns ['x']"
    ]
    shorter = {"kind": "outputs", "parts": [{"kind": "int", "value": 1}]}
    assert artifact_differences(shorter, expected) == ["the output has 1 values, expected 2"]


def test_named_parts_need_the_same_names():
    one = {"kind": "dict_of_ids", "parts": {"a": {"kind": "int", "value": 1}}}
    other = {"kind": "dict_of_ids", "parts": {"b": {"kind": "int", "value": 1}}}
    assert artifact_differences(one, other) == ["the output has the keys ['a'], expected ['b']"]
    assert artifact_differences(one, one) == []


# ---------------------------------------------------------------------------
# Stored JSON
# ---------------------------------------------------------------------------

def _json_file(path, value):
    path.write_bytes(zlib.compress(json.dumps(value).encode("utf-8")))
    return {"kind": "dict", "digest": "d-" + path.name, "path": str(path)}


def test_stored_json_with_the_same_digest_matches_without_reading_it(tmp_path):
    gone = str(tmp_path / "gone.json.zlib")
    same = {"kind": "list", "digest": "abc", "path": gone}
    assert artifact_differences(same, dict(same)) == []


def test_stored_json_with_other_bytes_is_compared_as_values(tmp_path):
    a = _json_file(tmp_path / "a.json.zlib", {"x": [1, 2], "y": "z"})
    reordered = _json_file(tmp_path / "b.json.zlib", {"y": "z", "x": [1, 2]})
    other = _json_file(tmp_path / "c.json.zlib", {"x": [1, 3], "y": "z"})
    assert artifact_differences(reordered, a) == []
    assert artifact_differences(other, a) == ["the output: the dict differs from the expected one"]


def test_stored_json_that_can_no_longer_be_read_is_reported(tmp_path):
    a = _json_file(tmp_path / "a.json.zlib", [1, 2])
    gone = {"kind": "dict", "digest": "other", "path": str(tmp_path / "gone.json.zlib")}
    [line] = artifact_differences(gone, a)
    assert "can no longer be read" in line


def test_one_side_read_as_json_and_the_other_as_stored_cannot_match():
    assert artifact_differences({"kind": "list", "envelope": {"data": []}}, {"kind": "list", "digest": "a"})


# ---------------------------------------------------------------------------
# What snapshot_artifact reads
# ---------------------------------------------------------------------------

class _Response:
    def __init__(self, status=200, *, body=None, content=b"", headers=None):
        self.status_code = status
        self.ok = status < 400
        self._body = body
        self.content = content
        self.text = json.dumps(body) if body is not None else ""
        self.headers = CaseInsensitiveDict(headers or {})

    def json(self):
        return self._body


class _Sandbox:
    """The three routes snapshot_artifact uses, and a log of the JSON /get calls."""

    def __init__(self, rows, tables=None, envelopes=None):
        self.rows = rows
        self.tables = tables or {}
        self.envelopes = envelopes or {}
        self.json_gets = []

    def get(self, url, params=None, headers=None, timeout=None):
        name = (params or {}).get("fileName")
        if url.endswith("/artifact-meta"):
            row = self.rows.get(name)
            return _Response(body=row) if row else _Response(404, body={"error": "not found"})
        assert url.endswith("/get"), url
        if (headers or {}).get("Accept") == ARROW:
            table, kind = self.tables[name]
            sink = pa.BufferOutputStream()
            with pa.ipc.new_stream(sink, table.schema) as writer:
                writer.write_table(table)
            return _Response(content=sink.getvalue().to_pybytes(), headers={
                "X-Curio-Kind": kind,
                "X-Curio-Rows": str(table.num_rows),
                "X-Curio-Filename": name,
            })
        self.json_gets.append(name)
        return _Response(body={**self.envelopes[name], "filename": name})


@pytest.fixture
def shared_data(tmp_path, monkeypatch):
    monkeypatch.setenv("CURIO_SHARED_DATA", str(tmp_path))
    (tmp_path / "artifacts").mkdir()
    return tmp_path


def test_a_tuple_of_a_list_and_a_table_is_read_without_any_json_envelope(shared_data, monkeypatch):
    (shared_data / "artifacts" / "grid.json.zlib").write_bytes(zlib.compress(b"[1.5, 2.5]"))
    table = pa.table({"x": [1.0, NAN]})
    sandbox = _Sandbox(
        rows={
            "out": {"kind": "outputs", "value_json": json.dumps(["grid", "frame", "shape"])},
            "grid": {"kind": "list", "value_str": "artifacts/grid.json.zlib"},
            "frame": {"kind": "geodataframe"},
            "shape": {"kind": "int", "value_int": 7},
        },
        tables={"frame": (table, "geodataframe")},
    )
    monkeypatch.setattr("requests.get", sandbox.get)

    snapshot = snapshot_artifact("out")

    assert sandbox.json_gets == []
    grid, frame, shape = snapshot["parts"]
    assert grid["kind"] == "list" and grid["path"].endswith("grid.json.zlib") and grid["digest"]
    assert frame["kind"] == "geodataframe" and frame["headers"]["X-Curio-Kind"] == "geodataframe"
    assert artifact_differences(frame, _table_snapshot(table, "geodataframe", **frame["headers"])) == []
    assert shape == {"kind": "int", "value": 7}
    # The same stored values snapshot the same way.
    assert artifact_differences(snapshot_artifact("out"), snapshot) == []


def test_a_kind_it_does_not_know_and_an_unseen_json_file_fall_back_to_the_envelope(shared_data, monkeypatch):
    sandbox = _Sandbox(
        rows={
            "odd": {"kind": "something-new"},
            "far": {"kind": "list", "value_str": "artifacts/not-on-this-machine.json.zlib"},
        },
        envelopes={"odd": {"data": 1, "dataType": "x"}, "far": {"data": [], "dataType": "list"}},
    )
    monkeypatch.setattr("requests.get", sandbox.get)

    assert snapshot_artifact("odd") == {"kind": "something-new", "envelope": {"data": 1, "dataType": "x"}}
    # A list read as JSON again is what this replaces, so it is said, not silent.
    with pytest.warns(UserWarning, match="reading its JSON envelope instead"):
        assert snapshot_artifact("far") == {"kind": "list", "envelope": {"data": [], "dataType": "list"}}
    assert sandbox.json_gets == ["odd", "far"]


def test_a_json_file_in_the_stacks_default_data_directory_is_found(tmp_path, monkeypatch):
    # CI's container runs its first stack without CURIO_SHARED_DATA, so it
    # writes under <repo>/.curio/data, while this process's conftest points
    # CURIO_SHARED_DATA at .curio/test/data (run 40215329366 on utk-desktop-02:
    # every list fell back to its envelope and example 09 lost its sandbox).
    repo = tmp_path / "repo"
    (repo / ".curio" / "data" / "artifacts").mkdir(parents=True)
    (repo / ".curio" / "data" / "artifacts" / "grid.json.zlib").write_bytes(zlib.compress(b"[1, 2]"))
    monkeypatch.setattr(sandbox_utils, "REPO_ROOT", str(repo))
    monkeypatch.setenv("CURIO_SHARED_DATA", str(tmp_path / "conftest-data"))
    sandbox = _Sandbox(rows={"grid": {"kind": "list", "value_str": "artifacts/grid.json.zlib"}})
    monkeypatch.setattr("requests.get", sandbox.get)

    snapshot = snapshot_artifact("grid")

    assert snapshot["path"] == str(repo / ".curio" / "data" / "artifacts" / "grid.json.zlib")
    assert sandbox.json_gets == []


def test_a_stream_cut_short_fails(shared_data, monkeypatch):
    sandbox = _Sandbox(rows={"t": {"kind": "dataframe"}}, tables={"t": (pa.table({"x": [1.0]}), "dataframe")})
    real_get = sandbox.get

    def short(url, params=None, headers=None, timeout=None):
        resp = real_get(url, params=params, headers=headers, timeout=timeout)
        if url.endswith("/get"):
            resp.headers["X-Curio-Rows"] = "2"
        return resp

    monkeypatch.setattr("requests.get", short)
    with pytest.raises(AssertionError, match="streamed 1 rows of 2"):
        snapshot_artifact("t")
