"""Save-time save warnings (the "Play All" account-store save path).

When a computed output can't be saved at save time — most commonly because its
artifact is missing on disk — ``_auto_install_computed_outputs`` skips it so one
bad output never blocks the whole save. These tests pin that the skip is no
longer SILENT: the failure is recorded in the ``failures`` list the caller
passes so the client can warn the user, while every healthy output is still
saved to the account store. (Computed outputs are account-level assets now — the
save writes no project ``dataflow.datasets`` ref.)
"""
from types import SimpleNamespace
from unittest import mock

from utk_curio.backend.app.projects.services import _auto_install_computed_outputs
from utk_curio.backend.app.projects.schemas import OutputRef


def _fake_result(node_id):
    manifest = SimpleNamespace(id=f"computed.{node_id}", dir_name=f"computed.{node_id}@1")
    return SimpleNamespace(manifest=manifest)


def test_failed_install_is_recorded_not_silent():
    def side_effect(user_key, *, node_id, path_ref, data_type, node_name, **kwargs):
        if node_id == "bad":
            raise RuntimeError("boom")
        return _fake_result(node_id)

    refs = [OutputRef(node_id="bad", filename="bad.parquet"),
            OutputRef(node_id="good", filename="good.parquet")]
    spec = {"dataflow": {"datasets": []}}
    failures: list = []

    with mock.patch(
        "utk_curio.backend.app.datasets.install.bundle.install_node_output",
        side_effect=side_effect,
    ):
        new_spec = _auto_install_computed_outputs("u", refs, spec, failures, dataflow_id="df")

    # No project ref is written (account-level save only) — the spec is unchanged.
    assert new_spec["dataflow"]["datasets"] == []
    assert [f["node_id"] for f in failures] == ["bad"]  # failure surfaced
    assert "boom" in failures[0]["reason"]


def test_missing_artifact_is_recorded():
    # install_node_output returns None when the artifact isn't found at save time.
    def side_effect(user_key, *, node_id, path_ref, data_type, node_name, **kwargs):
        return None

    refs = [OutputRef(node_id="n1", filename="missing.parquet")]
    spec = {"dataflow": {"datasets": []}}
    failures: list = []

    with mock.patch(
        "utk_curio.backend.app.datasets.install.bundle.install_node_output",
        side_effect=side_effect,
    ):
        _auto_install_computed_outputs("u", refs, spec, failures, dataflow_id="df")

    assert len(failures) == 1
    assert failures[0]["node_id"] == "n1"
    assert "not found" in failures[0]["reason"]


def test_no_failures_when_all_install():
    def side_effect(user_key, *, node_id, path_ref, data_type, node_name, **kwargs):
        return _fake_result(node_id)

    refs = [OutputRef(node_id="a", filename="a.parquet"),
            OutputRef(node_id="b", filename="b.parquet")]
    spec = {"dataflow": {"datasets": []}}
    failures: list = []

    with mock.patch(
        "utk_curio.backend.app.datasets.install.bundle.install_node_output",
        side_effect=side_effect,
    ):
        new_spec = _auto_install_computed_outputs("u", refs, spec, failures, dataflow_id="df")

    assert failures == []
    # Account-level save writes no project refs.
    assert new_spec["dataflow"]["datasets"] == []


def test_failures_param_optional_back_compat():
    # Callers that don't care about warnings can still omit the param.
    def side_effect(user_key, *, node_id, path_ref, data_type, node_name, **kwargs):
        raise RuntimeError("x")

    refs = [OutputRef(node_id="bad", filename="bad.parquet")]
    spec = {"dataflow": {"datasets": []}}

    with mock.patch(
        "utk_curio.backend.app.datasets.install.bundle.install_node_output",
        side_effect=side_effect,
    ):
        # Must not raise even without a failures list.
        out = _auto_install_computed_outputs("u", refs, spec, dataflow_id="df")
    assert out == spec


def test_missing_dataflow_id_records_failures_and_writes_nothing():
    # Defensive guard (#166): without a dataflow id nothing may be persisted —
    # a legacy un-namespaced dir would permanently duplicate the namespaced one.
    called = []

    refs = [OutputRef(node_id="n1", filename="a.parquet")]
    spec = {"dataflow": {"datasets": []}}
    failures: list = []

    with mock.patch(
        "utk_curio.backend.app.datasets.install.bundle.install_node_output",
        side_effect=lambda *a, **k: called.append(1),
    ):
        out = _auto_install_computed_outputs("u", refs, spec, failures)

    assert out is spec
    assert called == []  # installer never invoked
    assert len(failures) == 1
    assert "dataflow id" in failures[0]["reason"]


# ---------------------------------------------------------------------------
# #180: the reported symptom, at the save boundary.
#
# These deliberately do NOT mock ``install_node_output`` - the real one is the
# subject. A Python Computation returning a scalar has no artifact file at all,
# which used to be recorded as "output artifact not found at save time" and
# raised at the user as ``Dataset for "Python Computation" couldn't be
# generated. Re-run that node.`` The second test is the one that stops the fix
# from degenerating into blanket suppression.
# ---------------------------------------------------------------------------

def _analysis_spec(node_id):
    return {
        "dataflow": {
            "datasets": [],
            "nodes": [{"id": node_id, "type": "curio.builtin/computation-analysis"}],
        }
    }


def _ref(node_id, filename, data_type):
    return OutputRef(
        node_id=node_id,
        filename=filename,
        data_type=data_type,
        node_name="Python Computation",
    )


def test_scalar_output_records_no_install_warning(app):
    from utk_curio.backend.app.datasets.infrastructure.storage import dataset_dir
    from utk_curio.backend.app.datasets.install.installer import computed_dataset_id
    from utk_curio.backend.tests.test_datasets.computed_test_helpers import (
        store_sandbox_artifact,
    )

    art = store_sandbox_artifact(42)
    failures: list = []

    _auto_install_computed_outputs(
        "1", [_ref("py-1", art, "int")], _analysis_spec("py-1"), failures,
        dataflow_id="df-180",
    )

    assert failures == [], (
        "a scalar return value is a declared Python Computation output (VALUE) "
        "and must install, not be reported as a missing artifact (#180)"
    )
    dest = dataset_dir("1", computed_dataset_id("py-1", "df-180") + "@1")
    assert (dest / "manifest.json").is_file()


def test_genuinely_missing_artifact_still_records_a_warning(app):
    failures: list = []

    _auto_install_computed_outputs(
        "1", [_ref("py-1", "1790000000000_deadbeef", "int")], _analysis_spec("py-1"),
        failures, dataflow_id="df-180",
    )

    assert len(failures) == 1, (
        "an artifact with no DuckDB row really is gone, and re-running the node "
        "really does help - this warning must survive the #180 fix"
    )
    assert "not found" in failures[0]["reason"]


def test_dataframe_without_its_parquet_still_records_a_warning(app):
    import os
    from pathlib import Path

    import pandas as pd

    from utk_curio.backend.tests.test_datasets.computed_test_helpers import (
        store_sandbox_artifact,
    )

    art = store_sandbox_artifact(pd.DataFrame({"a": [1]}))
    shared = Path(os.environ["CURIO_SHARED_DATA"])
    for path in (shared / "artifacts").glob(art + "*"):
        path.unlink()

    failures: list = []
    _auto_install_computed_outputs(
        "1", [_ref("py-1", art, "dataframe")], _analysis_spec("py-1"), failures,
        dataflow_id="df-180",
    )

    assert [f["node_id"] for f in failures] == ["py-1"]
