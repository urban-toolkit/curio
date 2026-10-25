"""Deleting a saved output from the Data Catalog deletes the dataflow's result.

A node's saved output is a dataset in the account's Data Catalog
(``computed.<dataflow>.<node>@1``). Deleting it drops the node's entry from the
dataflow's manifest and forgets what the runs of the node kept
(``projects/services.forget_saved_output``, ``runs/kept.forget_node``). Before,
the dataflow reopened showing the node's kept result for 7 days, and a
dashboard viewer's run reused it, though its saved output was gone.

The sandbox is the fake the reopen tests use: a run answers an artifact named
after its node and its turn.
"""
from __future__ import annotations

from utk_curio.backend.app.datasets.install.installer import computed_dataset_id
from utk_curio.backend.app.runs import kept
from utk_curio.backend.app.runs.models import KeptStepOutput
from utk_curio.backend.tests.test_datasets.computed_test_helpers import auth_headers
from utk_curio.backend.tests.test_runs.test_reopen_shows_last_results import (  # noqa: F401 - sandbox is a fixture
    _create,
    _node,
    _open,
    _play,
    _record_as_saved,
    sandbox,
)

SAVED = "1700000000000_5a7ed000"


def _delete(client, token, dataset_id):
    resp = client.delete(f"/api/datasets/{dataset_id}", headers=auth_headers(token))
    assert resp.status_code == 200, resp.get_data(as_text=True)
    return resp.get_json()


def _ran_and_saved(client, token, user):
    """A dataflow of two nodes the owner ran, the first's output saved."""
    project_id = _create(client, token, [_node("a"), _node("b")])
    _record_as_saved(user, project_id, "a", SAVED)
    made_a = _play(client, token, project_id, "a")
    made_b = _play(client, token, project_id, "b")
    assert _open(client, token, project_id) == {"a": (made_a, "dataframe"), "b": (made_b, "dataframe")}
    return project_id, made_b


def test_a_deleted_saved_output_leaves_its_node_with_no_result_on_reopen(client, user_and_token, sandbox):
    user, token = user_and_token
    project_id, made_b = _ran_and_saved(client, token, user)

    _delete(client, token, computed_dataset_id("a", project_id))

    assert _open(client, token, project_id) == {"b": (made_b, "dataframe")}
    assert KeptStepOutput.query.filter_by(project_id=project_id, node_id="a").count() == 0
    assert KeptStepOutput.query.filter_by(project_id=project_id, node_id="b").count() == 1


def test_the_dataflow_records_no_output_for_the_node_any_more(client, user_and_token, sandbox):
    from utk_curio.backend.app.projects import storage
    from utk_curio.backend.app.projects.services import _user_dir_key

    user, token = user_and_token
    project_id, _made_b = _ran_and_saved(client, token, user)

    _delete(client, token, computed_dataset_id("a", project_id))

    outputs = (storage.read_manifest(_user_dir_key(user), project_id) or {}).get("outputs") or []
    assert [entry.get("node_id") for entry in outputs] == []


def test_no_viewers_run_reuses_the_deleted_result(client, user_and_token, sandbox):
    """A dashboard viewer's run reuses an output kept under the same key,
    whoever made it (``kept.kept_output``): a tile on the node runs it again."""
    user, token = user_and_token
    project_id, _made_b = _ran_and_saved(client, token, user)
    key = KeptStepOutput.query.filter_by(project_id=project_id, node_id="a").one().step_key
    assert kept.kept_output(project_id, key) is not None

    _delete(client, token, computed_dataset_id("a", project_id))

    assert kept.kept_output(project_id, key) is None


def test_another_accounts_dataflow_is_left_as_it_is(client, db, user_and_token, sandbox):
    from utk_curio.backend.app.projects.services import forget_saved_output
    from utk_curio.backend.app.users.models import User

    user, token = user_and_token
    project_id, _made_b = _ran_and_saved(client, token, user)
    other = User(username="bob", name="Bob", email="bob@test.com")
    db.session.add(other)
    db.session.commit()

    assert forget_saved_output(other, project_id, "a") is False
    assert KeptStepOutput.query.filter_by(project_id=project_id, node_id="a").count() == 1
