"""A hosted guest's Run All reuses what their own copy of the example kept
(dataflow audit step 6, step 9).

A hosted guest's runs stay in the browser, one request per node. The
browser's Run All says ``reuseKept`` in each, and a node whose key holds an
output the guest's plays kept on their own copy answers with it and runs
nothing, as a dashboard visitor's step does. Another guest's requests reuse
none of it: their copy is their own. A request without the flag, a Play's,
runs. The sandbox is the fake ``test_guest_copy_leaks.py`` plays against.
"""
from __future__ import annotations

import json

import pytest

from utk_curio.backend.tests.test_datasets.computed_test_helpers import auth_headers
from utk_curio.backend.tests.test_projects.test_guest_copy_leaks import (  # noqa: F401 - fixtures
    CODE,
    VISITOR_A,
    VISITOR_B,
    _as_a_play_posts,
    _content,
    app,
    example,
    sandbox,
)


@pytest.fixture()
def sent(sandbox, monkeypatch):
    """The nodes the fake sandbox is asked to run from now on, in order."""
    from utk_curio.backend.app.execution import node_exec

    asked = node_exec.sandbox_request
    nodes: list[str] = []

    def counting(method, path, **kwargs):
        if path in ("/exec", "/execJs"):
            nodes.append(json.loads(kwargs["data"])["code"].split("# node ", 1)[1].split("\n", 1)[0])
        return asked(method, path, **kwargs)

    monkeypatch.setattr(node_exec, "sandbox_request", counting)
    return nodes


def _request(client, token, project_id, node, *, reuse) -> dict:
    """The guest signed in as *token* runs *node* as the canvas posts it, a
    request of the browser's Run All with *reuse*, a Play's without; the
    reply."""
    body = {
        "code": _as_a_play_posts(_content(node)), "nodeType": f"{CODE}@1", "nodeId": node,
        "dataflowId": project_id, "input": "", "saveOutputDataset": True,
    }
    if reuse:
        body["reuseKept"] = True
    resp = client.post("/processPythonCode", data=json.dumps(body), headers=auth_headers(token))
    assert resp.status_code == 200, resp.get_data(as_text=True)
    return resp.get_json()


def test_a_hosted_guests_run_all_reuses_what_their_copy_kept_and_another_guest_reuses_none_of_it(
    client, example, sent,
):
    first = _request(client, VISITOR_A, example, "a", reuse=True)

    again = _request(client, VISITOR_A, example, "a", reuse=True)

    assert sent == ["a"], "the guest's Run All ran again a node their copy kept"
    assert again["output"]["path"] == first["output"]["path"]
    assert (again.get("reused") or {}).get("madeAt"), again
    # A guest's output joins no Data Catalog, reused or not.
    assert again["installedDataset"] is None

    _request(client, VISITOR_B, example, "a", reuse=True)
    assert sent == ["a", "a"], "a guest's Run All reused what another guest's copy kept"


def test_a_hosted_guests_play_runs_though_their_copy_kept_its_output(client, example, sent):
    """guard: a Play's request, which says nothing of reuse, always runs."""
    _request(client, VISITOR_A, example, "a", reuse=True)

    _request(client, VISITOR_A, example, "a", reuse=False)

    assert sent == ["a", "a"]
