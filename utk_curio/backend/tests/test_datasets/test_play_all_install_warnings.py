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
        new_spec = _auto_install_computed_outputs("u", refs, spec, failures)

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
        _auto_install_computed_outputs("u", refs, spec, failures)

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
        new_spec = _auto_install_computed_outputs("u", refs, spec, failures)

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
        out = _auto_install_computed_outputs("u", refs, spec)
    assert out == spec
