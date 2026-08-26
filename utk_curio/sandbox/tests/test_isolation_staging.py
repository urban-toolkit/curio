"""Artifacts crossing into and out of a child's scratch directory.

This is the data path minus the fork, and it runs on every platform. Two
round trips matter:

- **store -> scratch -> user code**: ``stage_input`` writes files a child can
  read, and ``child.rebuild_input`` turns them back into the object the node
  sees. If this loses a CRS or an object column, dataflows silently corrupt.
- **user code -> scratch -> store**: ``child.serialize_output`` writes files
  and ``persist_output`` files them away, after which ``load_from_duckdb``
  must return what the node returned.

Session scoping is tested here too, because it lives in the parent
deliberately: a compromised child cannot reach the check that stops it reading
another session's artifacts.
"""

import json
import os

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import Point

from utk_curio.sandbox.isolation import child, protocol
from utk_curio.sandbox.util import staging
from utk_curio.sandbox.util.db import init_db, release_connection
from utk_curio.sandbox.util.parsers import load_from_duckdb, save_to_duckdb


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    """A throwaway artifact store, the idiom from test_json_artifact_writer."""
    monkeypatch.setenv("CURIO_LAUNCH_CWD", str(tmp_path))
    monkeypatch.setenv("CURIO_SHARED_DATA", str(tmp_path / "data"))
    release_connection()
    init_db()
    yield tmp_path
    release_connection()


@pytest.fixture
def scratch(tmp_path):
    path = tmp_path / "scratch"
    path.mkdir(exist_ok=True)
    return path


# ---------------------------------------------------------------------------
# store -> scratch
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("value,expected_kind", [
    (None, "null"),
    (True, "bool"),
    (7, "int"),
    (1.5, "float"),
    ("text", "str"),
])
def test_scalars_stage_inline(workspace, scratch, value, expected_kind):
    """Scalars ride in the request; no file is needed."""
    art_id = save_to_duckdb(value)
    spec = staging.stage_input(art_id, scratch)
    assert spec["kind"] == expected_kind
    if expected_kind != "null":
        assert spec["value"] == value
    assert child.rebuild_input(spec, scratch) == value or value is None


def test_dataframe_round_trips_into_user_code(workspace, scratch):
    frame = pd.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]})
    art_id = save_to_duckdb(frame)

    spec = staging.stage_input(art_id, scratch)
    assert spec["kind"] == "dataframe"
    assert (scratch / spec["file"]).exists()

    rebuilt = child.rebuild_input(spec, scratch)
    pd.testing.assert_frame_equal(rebuilt, frame)


def test_geodataframe_keeps_crs_and_geometry(workspace, scratch):
    gdf = gpd.GeoDataFrame(
        {"a": [1, 2]},
        geometry=[Point(0, 0), Point(1, 1)],
        crs="EPSG:4326",
    )
    art_id = save_to_duckdb(gdf)

    rebuilt = child.rebuild_input(staging.stage_input(art_id, scratch), scratch)
    assert isinstance(rebuilt, gpd.GeoDataFrame)
    assert rebuilt.crs == gdf.crs
    assert rebuilt.geometry.equals(gdf.geometry)


def test_object_columns_survive_the_trip(workspace, scratch):
    """These are JSON-encoded for parquet; the spec has to carry which ones."""
    frame = pd.DataFrame({"payload": [{"k": 1}, [1, 2]]})
    art_id = save_to_duckdb(frame)

    spec = staging.stage_input(art_id, scratch)
    assert spec["encoded_object_columns"] == ["payload"]

    rebuilt = child.rebuild_input(spec, scratch)
    assert rebuilt["payload"].tolist() == [{"k": 1}, [1, 2]]


@pytest.mark.parametrize("value", [[1, 2, 3], {"a": 1, "b": [2]}])
def test_containers_stage_as_json(workspace, scratch, value):
    art_id = save_to_duckdb(value)
    spec = staging.stage_input(art_id, scratch)
    assert spec["kind"] == "json"
    assert child.rebuild_input(spec, scratch) == value


def test_a_tuple_stages_as_a_sequence(workspace, scratch):
    art_id = save_to_duckdb((1, "two", pd.DataFrame({"a": [1]})))
    spec = staging.stage_input(art_id, scratch)

    assert spec["kind"] == "sequence"
    assert spec["container"] == "tuple"
    assert [item["kind"] for item in spec["items"]] == ["int", "str", "dataframe"]

    rebuilt = child.rebuild_input(spec, scratch)
    assert isinstance(rebuilt, tuple)
    assert rebuilt[0] == 1 and rebuilt[1] == "two"
    pd.testing.assert_frame_equal(rebuilt[2], pd.DataFrame({"a": [1]}))


def test_staged_filenames_are_distinct_per_slot(workspace, scratch):
    """A merge node's inputs must not overwrite each other."""
    ids = [save_to_duckdb(pd.DataFrame({"a": [n]})) for n in range(3)]
    spec = staging.stage_outputs_list([{"path": i} for i in ids], scratch)

    names = [item["file"] for item in spec["items"]]
    assert len(set(names)) == 3, names
    rebuilt = child.rebuild_input(spec, scratch)
    assert [int(frame["a"][0]) for frame in rebuilt] == [0, 1, 2]


def test_every_staged_filename_is_one_the_parent_would_accept(workspace, scratch):
    """Staged names are reused as output names, so they must satisfy the check."""
    art_id = save_to_duckdb((pd.DataFrame({"a": [1]}), [1, 2], 3))
    spec = staging.stage_input(art_id, scratch)

    def check(node):
        if "file" in node:
            protocol.validate_scratch_filename(node["file"])
        for item in node.get("items", []) or []:
            check(item)

    check(spec)


# ---------------------------------------------------------------------------
# Session scoping stays in the parent
# ---------------------------------------------------------------------------

def test_another_sessions_artifact_cannot_be_staged(workspace, scratch):
    art_id = save_to_duckdb(pd.DataFrame({"a": [1]}), session_id="session-a")

    with pytest.raises(KeyError):
        staging.stage_input(art_id, scratch, session_id="session-b")


def test_the_owning_session_can_stage_it(workspace, scratch):
    art_id = save_to_duckdb(pd.DataFrame({"a": [1]}), session_id="session-a")
    spec = staging.stage_input(art_id, scratch, session_id="session-a")
    assert spec["kind"] == "dataframe"


def test_a_pre_isolation_artifact_is_still_readable(workspace, scratch):
    """Rows written before session tagging have session_id NULL."""
    art_id = save_to_duckdb(pd.DataFrame({"a": [1]}))
    spec = staging.stage_input(art_id, scratch, session_id="any-session")
    assert spec["kind"] == "dataframe"


def test_a_missing_artifact_reports_as_missing(workspace, scratch):
    with pytest.raises(KeyError):
        staging.stage_input("no-such-artifact", scratch)


# ---------------------------------------------------------------------------
# scratch -> store
# ---------------------------------------------------------------------------

def _run_and_persist(code, scratch, *, session_id=None, input_spec=None):
    """Run node code in-process and file its output away, as the parent would."""
    request = {
        "code": code,
        "node_type": "curio.builtin/computation-analysis",
        "data_type": "",
        "scratch_dir": str(scratch),
        "input": input_spec or {"kind": "none"},
        "dataset_paths": {},
        "session_imports": [],
        "limits": {},
    }

    def namespace_factory():
        import numpy as np
        return {"__builtins__": __builtins__, "pd": pd, "gpd": gpd, "np": np}

    manifest = child.run_node(request, namespace_factory)
    assert manifest["ok"], manifest["stderr"]

    child.write_result(manifest, scratch)
    from utk_curio.sandbox.isolation import supervisor
    validated = supervisor.read_child_manifest(scratch)

    art_id = staging.persist_output(validated["output"], session_id=session_id)
    return art_id


@pytest.mark.parametrize("code,expected", [
    ("    return 42\n", 42),
    ("    return 'hello'\n", "hello"),
    ("    return True\n", True),
    ("    return 2.5\n", 2.5),
    ("    return [1, 2, 3]\n", [1, 2, 3]),
    ("    return {'a': 1}\n", {"a": 1}),
])
def test_child_output_becomes_a_loadable_artifact(workspace, scratch, code, expected):
    art_id = _run_and_persist(code, scratch)
    assert load_from_duckdb(art_id) == expected


def test_a_dataframe_output_round_trips_through_the_store(workspace, scratch):
    art_id = _run_and_persist(
        "    return pd.DataFrame({'a': [1, 2], 'b': ['x', 'y']})\n", scratch
    )
    pd.testing.assert_frame_equal(
        load_from_duckdb(art_id), pd.DataFrame({"a": [1, 2], "b": ["x", "y"]})
    )


def test_a_geodataframe_output_keeps_its_crs(workspace, scratch):
    art_id = _run_and_persist(
        "    from shapely.geometry import Point\n"
        "    return gpd.GeoDataFrame({'a': [1]}, geometry=[Point(3, 4)], crs='EPSG:4326')\n",
        scratch,
    )
    loaded = load_from_duckdb(art_id)
    assert isinstance(loaded, gpd.GeoDataFrame)
    assert loaded.crs == "EPSG:4326"
    assert loaded.geometry.iloc[0].x == 3


def test_a_tuple_output_round_trips(workspace, scratch):
    art_id = _run_and_persist("    return (1, 'two')\n", scratch)
    loaded = load_from_duckdb(art_id)
    assert loaded == (1, "two")


def test_the_output_is_tagged_with_the_session(workspace, scratch):
    art_id = _run_and_persist("    return 1\n", scratch, session_id="session-a")
    # The owning session reads it; another session must not.
    assert load_from_duckdb(art_id, session_id="session-a") == 1
    with pytest.raises(KeyError):
        load_from_duckdb(art_id, session_id="session-b")


def test_a_full_input_to_output_cycle(workspace, scratch):
    """One node's output becomes the next node's input, all through staging."""
    first = _run_and_persist("    return pd.DataFrame({'a': [1, 2, 3]})\n", scratch)

    downstream_scratch = scratch.parent / "scratch2"
    downstream_scratch.mkdir()
    spec = staging.stage_input(first, downstream_scratch)
    second = _run_and_persist(
        "    return int(arg['a'].sum())\n", downstream_scratch, input_spec=spec
    )
    assert load_from_duckdb(second) == 6


def test_persist_refuses_a_descriptor_naming_a_missing_file(workspace, scratch):
    with pytest.raises(staging.StagingError):
        staging.persist_output(
            {"kind": "dataframe", "file": "gone.parquet",
             "path": str(scratch / "gone.parquet")}
        )


def test_the_dataset_copy_must_happen_before_the_move(workspace, scratch):
    """persist_output moves the file, so the order in the supervisor matters."""
    manifest_descriptor = {"kind": "dataframe", "file": "out.parquet"}
    pd.DataFrame({"a": [1]}).to_parquet(scratch / "out.parquet")
    manifest_descriptor["path"] = str(scratch / "out.parquet")

    name = staging.copy_output_dataset(manifest_descriptor)
    assert name and name.endswith("_output.parquet")

    staging.persist_output(manifest_descriptor)
    # The scratch file is gone now, so a second copy attempt finds nothing.
    assert staging.copy_output_dataset(manifest_descriptor) is None


def test_staging_a_dataset_path_links_it_into_scratch(workspace, scratch):
    source = workspace / "some-dataset.parquet"
    pd.DataFrame({"a": [1]}).to_parquet(source)

    staged = staging.stage_dataset_paths({"my.dataset": str(source)}, scratch)
    assert "my.dataset" in staged
    assert (scratch / staged["my.dataset"]).exists()


def test_staging_a_missing_dataset_path_is_dropped_not_raised(workspace, scratch):
    """Resolution is documented as fail-open; the child raises a clear error."""
    staged = staging.stage_dataset_paths({"gone": str(workspace / "nope.parquet")},
                                         scratch)
    assert staged == {}


def test_input_staging_does_not_duplicate_large_payloads(workspace, scratch):
    """Staging should hardlink rather than copy where the filesystem allows it.

    Asserted by inode identity where available. On a filesystem or platform
    without hardlinks the fallback copy is correct too, so this only checks the
    contents there.
    """
    frame = pd.DataFrame({"a": list(range(1000))})
    art_id = save_to_duckdb(frame)
    spec = staging.stage_input(art_id, scratch)
    staged = scratch / spec["file"]

    from utk_curio.sandbox.util.parsers import (
        _resolve_stored_artifact_path,
        _stored_artifact_rel_path,
    )
    original = _resolve_stored_artifact_path(_stored_artifact_rel_path(art_id))

    staged_stat = os.stat(staged)
    original_stat = os.stat(original)
    if staged_stat.st_nlink > 1:
        assert staged_stat.st_ino == original_stat.st_ino
    else:
        assert staged.read_bytes() == original.read_bytes()


# ---------------------------------------------------------------------------
# The DuckDB write handle must not be held between executions
# ---------------------------------------------------------------------------

def test_persisting_releases_the_duckdb_write_handle(workspace, scratch):
    """DuckDB allows one cross-process writer, and the backend needs it.

    worker.execute_code releases per execution for this reason (its finally
    block spells out that the teardown is required, not wasteful). The isolated
    path bypasses execute_code entirely, so if it does not release, the first
    isolated node starves the backend's read-only opens for the life of the
    sandbox process. That failure would only show up as flaky catalog and
    auto-install errors on a real deployment, so it is pinned here.
    """
    from utk_curio.sandbox.isolation import runner
    from utk_curio.sandbox.util import db

    pd.DataFrame({"a": [1]}).to_parquet(scratch / "out.parquet")
    descriptor = {
        "kind": "dataframe",
        "file": "out.parquet",
        "path": str(scratch / "out.parquet"),
        "meta": {},
    }

    art_id, _dataset = runner._persist_and_release(
        descriptor, node_type="n", session_id=None, save_dataset=False
    )

    assert art_id
    assert db._connection is None, (
        "the isolated path kept the DuckDB write handle; the backend's "
        "read-only opens will now fail"
    )
    # And the artifact is genuinely there, i.e. releasing did not lose the write.
    pd.testing.assert_frame_equal(load_from_duckdb(art_id), pd.DataFrame({"a": [1]}))


def test_the_handle_is_released_even_when_persisting_fails(workspace, scratch):
    """A failed persist must not leave the lock held either."""
    from utk_curio.sandbox.isolation import runner
    from utk_curio.sandbox.util import db

    with pytest.raises(staging.StagingError):
        runner._persist_and_release(
            {"kind": "dataframe", "file": "missing.parquet",
             "path": str(scratch / "missing.parquet")},
            node_type="n", session_id=None, save_dataset=False,
        )
    assert db._connection is None


def test_the_dataset_copy_still_happens_before_the_move(workspace, scratch):
    """Ordering inside _persist_and_release, which the helper now owns."""
    from utk_curio.sandbox.isolation import runner

    pd.DataFrame({"a": [1]}).to_parquet(scratch / "out.parquet")
    descriptor = {
        "kind": "dataframe",
        "file": "out.parquet",
        "path": str(scratch / "out.parquet"),
        "meta": {},
    }
    _art_id, dataset_file = runner._persist_and_release(
        descriptor, node_type="n", session_id=None, save_dataset=True
    )
    assert dataset_file, "the dataset copy was skipped or ran after the move"
