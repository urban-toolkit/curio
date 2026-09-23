"""A node that reads an installed dataset must not get a computed copy of it.

The dashboard needs an output ref for every node feeding a pinned tile, so a
reload can hand the tile its data. That now includes a Data Catalog palette
node, whose "output" is the installed dataset it loaded. Recording the ref is
right: ``storage._installed_file_for_node`` resolves it, so
``persisted_output_refs`` keeps it and ``hydrate_outputs`` restores it.

Installing it would not be. The bytes are already in the account's dataset
store under the dataset's own id; a second copy titled after the reading node
is the duplicate the palette's forced-off Save toggle used to prevent. Both
installers therefore skip a node whose output is a dataset the account already
holds, and keep the ref.
"""
import pytest

from utk_curio.backend.app.datasets.application.auto_install import (
    auto_install_node_output,
)
from utk_curio.backend.app.datasets.infrastructure.storage import dataset_dir
from utk_curio.backend.app.datasets.install.installer import (
    install_computed_file_for_node,
)
from utk_curio.backend.app.projects import services, storage
from utk_curio.backend.app.projects.schemas import OutputRef

USER_KEY = "1"
DATAFLOW_ID = "proj-palette"
#: The node that loads the dataset, and the node that computes something new.
LOADER = "loader-node"
PRODUCER = "producer-node"


def _install_a_dataset_the_loader_reads():
    """An installed dataset, plus the spec ref that binds it to LOADER."""
    install_computed_file_for_node(
        USER_KEY,
        b"city,count\nChicago,10\n",
        "upstream_out.csv",
        "csv",
        node_id="some-other-node",
        dataflow_id=DATAFLOW_ID,
    )
    dir_name = f"computed.{DATAFLOW_ID}.some-other-node@1"
    spec = {
        "dataflow": {
            "nodes": [
                {"id": LOADER, "type": "curio.builtin/data-loading"},
                {"id": PRODUCER, "type": "curio.builtin/computation-analysis"},
            ],
            "datasets": [{
                "datasetId": f"computed.{DATAFLOW_ID}.some-other-node",
                "dirName": dir_name,
                "origin": "computed",
                "producerNodeId": LOADER,
            }],
        },
    }
    # On disk too: the run-time installer reads the spec from there, not from
    # the request.
    storage.write_spec(USER_KEY, DATAFLOW_ID, spec)
    return spec


def test_the_resolver_finds_the_dataset_a_node_reads(tmp_curio):
    spec = _install_a_dataset_the_loader_reads()

    found = storage.installed_dataset_file_for_node(USER_KEY, spec, LOADER)

    assert found is not None and found.is_file()
    assert storage.installed_dataset_file_for_node(USER_KEY, spec, PRODUCER) is None
    assert storage.installed_dataset_file_for_node(USER_KEY, None, LOADER) is None


def test_the_save_installer_skips_the_loader_and_still_installs_a_producer(tmp_curio):
    spec = _install_a_dataset_the_loader_reads()
    # The producer's artifact, where the installer looks for it.
    shared = storage._shared_data_dir()
    shared.mkdir(parents=True, exist_ok=True)
    (shared / "producer_out.csv").write_bytes(b"a,b\n1,2\n")

    failures: list[dict] = []
    services._auto_install_computed_outputs(
        USER_KEY,
        [
            OutputRef(node_id=LOADER, filename="upstream_out.csv", data_type="dataframe"),
            OutputRef(node_id=PRODUCER, filename="producer_out.csv", data_type="dataframe"),
        ],
        spec,
        failures,
        dataflow_id=DATAFLOW_ID,
    )

    assert not dataset_dir(USER_KEY, f"computed.{DATAFLOW_ID}.{LOADER}@1").exists(), (
        "the loader's output was installed as a second dataset; the account now "
        "holds two rows for one file"
    )
    assert dataset_dir(USER_KEY, f"computed.{DATAFLOW_ID}.{PRODUCER}@1").exists(), (
        "the guard stopped a genuine producer from being saved"
    )
    # A skip is not a failure: nothing to warn the user about.
    assert [f["node_id"] for f in failures] == []


def test_the_skipped_loaders_ref_is_still_restorable(tmp_curio):
    spec = _install_a_dataset_the_loader_reads()
    refs = [OutputRef(node_id=LOADER, filename="upstream_out.csv")]

    kept = storage.persisted_output_refs(USER_KEY, DATAFLOW_ID, refs, spec=spec)

    assert [r.node_id for r in kept] == [LOADER], (
        "the manifest would drop the ref, so a reload could not feed the tile"
    )
    hydrated = storage.hydrate_outputs(USER_KEY, DATAFLOW_ID, refs, spec=spec)
    assert [r.node_id for r in hydrated] == [LOADER]
    assert (storage._shared_data_dir() / "upstream_out.csv").is_file(), (
        "the output was not hydrated into the shared dir, so /get cannot serve it"
    )


def test_the_run_installer_reports_the_skip(app):
    # ``app`` for the dataset index's DB session, which the installer touches.
    spec = _install_a_dataset_the_loader_reads()

    class _User:
        id = 1
        is_guest = False
        username = "alice"

    diagnostic = auto_install_node_output(
        user=_User(),
        node_id=LOADER,
        sandbox_output={"path": "upstream_out.csv", "dataType": "dataframe"},
        dataflow_id=DATAFLOW_ID,
        node_type="curio.builtin/data-loading",
    )

    assert diagnostic["status"] == "skipped"
    assert "already holds" in diagnostic["reason"]
    assert not dataset_dir(USER_KEY, f"computed.{DATAFLOW_ID}.{LOADER}@1").exists()
