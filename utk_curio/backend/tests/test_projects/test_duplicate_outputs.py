"""A duplicated dataflow keeps every saved output its source can read.

Duplicate used to save the copy with the source's output names, so each output
was installed again from the sandbox's artifacts by name. The store keeps an
artifact only so long, so an output whose artifact had gone was left out of
the copy, though the source still showed it. Now each saved output's dataset is
copied as a scenario drop copies one: its folder, its files linked, its
manifest naming the copy's node and dataflow (``datasets/install/copy.py``).
"""
from __future__ import annotations

import os

import pandas as pd

from utk_curio.backend.app.datasets.domain.manifest import load_dataset_manifest
from utk_curio.backend.app.datasets.infrastructure.storage import dataset_dir
from utk_curio.backend.app.datasets.install.installer import computed_dataset_id
from utk_curio.backend.app.projects import services, storage
from utk_curio.backend.app.projects.schemas import OutputRef, ProjectCreate


def _spec(name: str) -> dict:
    return {"dataflow": {
        "name": name,
        "nodes": [{"id": "py-1", "type": "curio.builtin/computation-analysis"}],
        "edges": [],
    }}


def _saved_table(user) -> tuple[str, str]:
    """A dataflow whose node ``py-1`` saved a table, the table's artifact
    then gone from the store: ``(dataflow id, the output's name)``."""
    from utk_curio.sandbox.util.parsers import _shared_data_dir, save_to_duckdb

    art_id = save_to_duckdb(pd.DataFrame({"n": [1, 2, 3]}), node_id="py-1")
    detail = services.save_project(user, ProjectCreate(
        name="Source", spec=_spec("Source"), outputs=[OutputRef(node_id="py-1", filename=art_id)],
    ))
    assert [ref.filename for ref in detail.outputs] == [art_id]
    (_shared_data_dir() / "artifacts" / f"{art_id}.parquet").unlink()
    return detail.id, art_id


def test_a_duplicate_keeps_a_saved_output_whose_artifact_is_gone(app, db, user_and_token, tmp_curio):
    user, _ = user_and_token
    user_key = services._user_dir_key(user)
    source_id, art_id = _saved_table(user)
    source_file = storage.saved_output_file(user_key, source_id, art_id)
    assert source_file is not None

    copy = services.duplicate_project(user, source_id)

    assert [(ref.node_id, ref.filename) for ref in copy.outputs] == [("py-1", art_id)]
    loaded = services.load_project(user, copy.id)
    assert [entry["filename"] for entry in loaded["outputs"]] == [art_id]
    copied = storage.saved_output_file(user_key, copy.id, art_id)
    assert copied is not None
    assert copied.path != source_file.path
    assert os.path.samefile(copied.path, source_file.path)


def test_a_duplicate_keeps_an_output_read_from_an_installed_dataset(app, db, user_and_token, tmp_curio):
    """A node that loads an installed dataset has that dataset as its saved
    output. The copy's spec names the same dataset, so the copy records the
    output as it is and reads the same file."""
    from utk_curio.backend.app.datasets.install.installer import install_computed_file_for_node

    user, _ = user_and_token
    user_key = services._user_dir_key(user)
    install_computed_file_for_node(
        user_key, b"city,count\nChicago,10\n", "upstream_out.csv", "csv",
        node_id="other-node", dataflow_id="elsewhere",
    )
    source = services.save_project(user, ProjectCreate(name="Loader", spec=_spec("Loader")))
    spec = storage.read_spec(user_key, source.id)
    spec["dataflow"]["nodes"].append({"id": "loader", "type": "curio.builtin/data-loading"})
    spec["dataflow"]["datasets"] = [{
        "datasetId": "computed.elsewhere.other-node",
        "dirName": "computed.elsewhere.other-node@1",
        "origin": "computed",
        "producerNodeId": "loader",
    }]
    storage.write_spec(user_key, source.id, spec)
    storage.record_outputs(user_key, source.id, [{"node_id": "loader", "filename": "upstream_out.csv"}])
    source_file = storage.saved_output_file(user_key, source.id, "upstream_out.csv")
    assert source_file is not None

    copy = services.duplicate_project(user, source.id)

    assert [(ref.node_id, ref.filename) for ref in copy.outputs] == [("loader", "upstream_out.csv")]
    copied = storage.saved_output_file(user_key, copy.id, "upstream_out.csv")
    assert copied is not None and copied.path == source_file.path


def test_the_copied_output_is_the_duplicates_own(app, db, user_and_token, tmp_curio):
    """Its dataset is the copy's node's in the copy's dataflow, so a later run
    of the source installs into the source's dataset and never this one."""
    user, _ = user_and_token
    user_key = services._user_dir_key(user)
    source_id, _art_id = _saved_table(user)

    copy = services.duplicate_project(user, source_id)

    copied = load_dataset_manifest(dataset_dir(user_key, f"{computed_dataset_id('py-1', copy.id)}@1"))
    assert copied.producer_node_id == "py-1"
    assert copied.producer_dataflow_id == copy.id
    assert copied.producer_dataflow_name == "Source (copy)"
    source = load_dataset_manifest(dataset_dir(user_key, f"{computed_dataset_id('py-1', source_id)}@1"))
    assert source.producer_dataflow_id == source_id
