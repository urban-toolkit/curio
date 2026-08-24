"""#180: a Python Computation output with no artifact FILE must still install.

``curio.builtin/computation-analysis`` declares its output ports as
``[DATAFRAME, GEODATAFRAME, VALUE, LIST, JSON, RASTER]``, but only the first two
and RASTER ever write a file under ``artifacts/``. A scalar, a ``None``, or a
list/dict holding DataFrames lives entirely in the DuckDB ``artifacts`` row, so
``resolve_shared_output_path`` returned ``None``, ``install_node_output``
returned ``None``, and the save recorded "output artifact not found at save
time" - which the client raised as

    Dataset for "Python Computation" couldn't be generated. Re-run that node.

Re-running never helped, because nothing was missing.
``install_computed_bundle_for_node`` had always materialized exactly these kinds
correctly per bundle part; these tests pin the same symmetry for a single
output, and pin the two things that must NOT change with it: a genuinely absent
artifact still fails, and a ``str`` return value is stored as a value rather
than resolved as a path.

Artifacts are built through the real ``save_to_duckdb``, never hand-written
INSERTs: drift between the writer and the resolver is the bug itself.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from utk_curio.backend.app.datasets.domain.manifest import load_dataset_manifest
from utk_curio.backend.app.datasets.infrastructure.storage import dataset_dir
from utk_curio.backend.app.datasets.install.bundle import (
    install_node_output,
    resolve_output_bundle_parts,
)
from utk_curio.backend.app.datasets.install.installer import computed_dataset_id
from utk_curio.backend.tests.test_datasets.computed_test_helpers import (
    store_sandbox_artifact,
)

USER = "1"
DATAFLOW = "df-180"


def _install(art_id, *, node_id="py-1", data_type=None, node_name="Python Computation"):
    return install_node_output(
        USER,
        node_id=node_id,
        path_ref=art_id,
        data_type=data_type,
        node_name=node_name,
        dataflow_id=DATAFLOW,
        node_type="curio.builtin/computation-analysis",
    )


def _shared() -> Path:
    return Path(os.environ["CURIO_SHARED_DATA"])


def _data_path(node_id="py-1") -> Path:
    dest = dataset_dir(USER, f"{computed_dataset_id(node_id, DATAFLOW)}@1")
    return dest / load_dataset_manifest(dest).data_file


def _installed_json(node_id="py-1"):
    # A plain json.load, deliberately: this is the exact call the generated
    # loader snippet makes, so it fails the same way a Dataset node would.
    return json.loads(_data_path(node_id).read_text(encoding="utf-8"))


def _frames():
    import pandas as pd

    return pd.DataFrame({"a": [1]}), pd.DataFrame({"b": [2]})


# -- Group 1: file-less kinds install ---------------------------------------

@pytest.mark.parametrize(
    "value,data_type,expected",
    [
        (42, "int", 42),
        (3.5, "float", 3.5),
        # ``False`` is the load-bearing case. bool and int share value_int, so a
        # branch that checks int first emits ``{"value": 0}`` for a node that
        # returned False.
        (True, "bool", True),
        (False, "bool", False),
        ("hello", "str", "hello"),
        (None, "null", None),
    ],
    ids=["int", "float", "true", "false", "str", "null"],
)
def test_row_only_kinds_install_with_a_value_envelope(app, value, data_type, expected):
    art = store_sandbox_artifact(value)
    result = _install(art, data_type=data_type)

    assert result is not None, (
        "a {} output has no artifact file by design and used to be reported as "
        "missing (#180)".format(data_type)
    )
    assert result.manifest.format == "json"
    assert result.manifest.data_file == "data/{}.json".format(art)
    assert _installed_json() == {"value": expected}


def test_scalar_data_file_is_a_safe_single_segment(app):
    from utk_curio.backend.app.common.safe_paths import validate_component

    result = _install(store_sandbox_artifact(7), data_type="int")
    data_file = Path(result.manifest.data_file)

    assert data_file.parent.as_posix() == "data"
    assert data_file.suffix == ".json"
    # Raises PathTraversalError if the installer had built an unsafe name.
    assert validate_component(data_file.name, field="output filename") == data_file.name


def test_scalar_data_file_is_strict_valid_json(app):
    _install(store_sandbox_artifact(3.5), data_type="float")
    # allow_nan=False: NaN/Infinity are accepted by Python's lenient loads but
    # rejected by the browser's strict parser.
    json.dumps(_installed_json(), allow_nan=False)


# -- Group 2: the genuine failure is preserved ------------------------------

def test_missing_artifact_row_still_returns_none(app):
    # The case the warning exists for: a pruned artifact, or a restarted sandbox.
    assert _install("1790000000000_deadbeef", data_type="int") is None


def test_row_with_a_missing_file_still_returns_none(app):
    import pandas as pd

    art = store_sandbox_artifact(pd.DataFrame({"a": [1, 2]}))
    # Strand it the way an evicted scratch dir does: drop the bytes, keep the row.
    for path in (_shared() / "artifacts").glob(art + "*"):
        path.unlink()

    assert _install(art, data_type="dataframe") is None, (
        "a file-backed kind whose file vanished is genuinely re-runnable and must "
        "keep warning"
    )


def test_traversal_ref_never_reaches_the_row_lookup(app, monkeypatch):
    def _explode(*_a, **_k):
        raise AssertionError("the _bare_artifact_id gate did not short-circuit")

    monkeypatch.setattr(
        "utk_curio.backend.app.datasets.install.bundle._artifact_value_row", _explode
    )
    assert _install("../../../../etc/hosts", data_type="int") is None


def test_duckdb_unavailable_returns_none(app, monkeypatch):
    def _locked(*_a, **_k):
        raise OSError("Could not set lock on file")

    monkeypatch.setattr("utk_curio.sandbox.util.db.get_read_connection", _locked)
    assert _install("1790000000000_deadbeef", data_type="int") is None


# -- Group 3: decompression -------------------------------------------------

@pytest.mark.parametrize(
    "value,data_type",
    [({"hello": "world", "n": 3}, "dict"), ([1, 2, 3], "list")],
    ids=["dict", "list"],
)
def test_json_native_output_is_stored_decompressed(app, value, data_type):
    art = store_sandbox_artifact(value)
    # Sanity-check the premise: the sandbox really does write this compressed.
    assert (_shared() / "artifacts" / (art + ".json.zlib")).is_file()

    result = _install(art, data_type=data_type)

    assert result.manifest.format == "json"
    assert result.manifest.data_file.endswith(".json")
    assert not result.manifest.data_file.endswith(".zlib"), (
        "a hard-linked .json.zlib serves compressed bytes under a .json format, "
        "which Export streams verbatim and no client can parse (#180)"
    )
    assert _installed_json() == value


def test_installed_json_dataset_loads_with_the_generated_loader_snippet(app):
    from utk_curio.backend.app.datasets.domain.catalog_item import loader_snippet

    payload = {"city": "Chicago", "pm25": 12.5}
    _install(store_sandbox_artifact(payload), data_type="dict")

    snippet = loader_snippet("json", str(_data_path()))
    source = "\n".join(snippet["imports"] + [snippet["code"]])
    namespace: dict = {}
    exec(source, namespace)  # noqa: S102 - this is what a Dataset node runs
    assert namespace[snippet["returnVariable"]] == payload


def test_json_dataset_downloads_with_a_json_extension(app):
    from utk_curio.backend.app.datasets.application.export import (
        _DOWNLOAD_MIMETYPES,
        _download_extension,
    )

    _install(store_sandbox_artifact({"a": 1}), data_type="dict")

    extension = _download_extension(_data_path(), "json")
    assert extension == ".json"
    assert _DOWNLOAD_MIMETYPES[extension] == "application/json"


# -- Group 4: the str mis-resolution ----------------------------------------

def test_str_output_naming_a_real_file_stores_the_value_not_the_file(app):
    (_shared() / "cities.csv").write_text("name,pop\nChicago,3\n", encoding="utf-8")

    result = _install(store_sandbox_artifact("cities.csv"), data_type="str")

    assert result is not None
    assert _installed_json() == {"value": "cities.csv"}, (
        "a str artifact keeps the user's return value in value_str, so treating "
        "it as a path hard-links an unrelated file in as the node's dataset (#180)"
    )


# -- Group 6: the helper extraction is behaviour-preserving -----------------

def test_scalar_bundle_part_and_single_output_agree(app):
    bundle = _install(store_sandbox_artifact((1, "x")), node_id="tup", data_type="outputs")
    single = _install(store_sandbox_artifact(1), node_id="scalar", data_type="int")

    bundle_dir = dataset_dir(USER, bundle.manifest.dir_name)
    part = json.loads(
        (bundle_dir / "data" / "parts" / "00_int.json").read_text(encoding="utf-8")
    )
    assert part == _installed_json("scalar")
    assert single.manifest.format == "json"


def test_bundle_scalar_part_placeholder_when_the_row_is_missing(app, tmp_path):
    from utk_curio.backend.app.datasets.install.bundle import _serialize_scalar_part

    dest = tmp_path / "part.json"
    _serialize_scalar_part(dest, "int", "no-such-artifact")
    assert json.loads(dest.read_text(encoding="utf-8")) == {
        "artifactId": "no-such-artifact",
        "kind": "int",
    }


# -- Group 7: id containers install as bundles ------------------------------

def test_list_of_dataframes_installs_as_a_bundle(app):
    left, right = _frames()
    # detect_kind reports plain 'list'; only the DuckDB row knows it is
    # 'list_of_ids', which is why dispatch reads the row.
    result = _install(store_sandbox_artifact([left, right]), data_type="list")

    assert result.manifest.format == "bundle"
    spec = json.loads(_data_path().read_text(encoding="utf-8"))
    assert len(spec["parts"]) == 2
    dest = dataset_dir(USER, result.manifest.dir_name)
    for part in spec["parts"]:
        assert (dest / part["file"]).is_file()


def test_dict_of_dataframes_keeps_its_keys_as_part_labels(app):
    left, right = _frames()
    result = _install(
        store_sandbox_artifact({"roads": left, "blocks": right}), data_type="dict"
    )

    assert result.manifest.format == "bundle"
    spec = json.loads(_data_path().read_text(encoding="utf-8"))
    assert [part["label"] for part in spec["parts"]] == ["roads", "blocks"]


def test_tuple_output_still_installs_as_a_bundle(app):
    left, right = _frames()
    result = _install(store_sandbox_artifact((left, right)), data_type="outputs")

    assert result.manifest.format == "bundle"
    spec = json.loads(_data_path().read_text(encoding="utf-8"))
    assert len(spec["parts"]) == 2


def test_id_container_with_pruned_children_returns_none(app, monkeypatch):
    left, right = _frames()
    art = store_sandbox_artifact([left, right])
    monkeypatch.setattr(
        "utk_curio.backend.app.datasets.install.bundle.resolve_output_bundle_parts",
        lambda *_a, **_k: [],
    )
    assert _install(art, data_type="list") is None


def test_resolve_output_bundle_parts_rejects_an_unrelated_kind(app):
    assert resolve_output_bundle_parts(store_sandbox_artifact({"a": 1})) == []
