"""#468: every way a Python node reaches the sandbox hands it the modules its
package ships beside its templates.

Play (``/processPythonCode``), a run on a thread of its own (what a server
run calls), and the headless runner (Solve and the agents) all send
``package_modules: {"root": <the package's sources folder>, "names": [...]}``
for a node of a package that ships modules, and nothing for any other node,
so every other request body is unchanged. The e2e ground-truth harness gets it
from ``/api/testing/dataset-paths``.

New code is imported inside each test, so a checkout without it fails each
test on its own instead of the whole module at collection.
"""

from __future__ import annotations

import io
import json
import zipfile

from utk_curio.backend.tests.test_datasets.computed_test_helpers import (
    auth_headers,
    create_project,
)

NODE_TYPE = "ai.test.heights/caller"

# A folder of modules with no __init__.py: a namespace package.
MODULES = {"building_height/convert_to_raster.py": "def convert_raster(value):\n    return value * 2\n"}


def _archive(package_id="ai.test.heights", modules=MODULES) -> bytes:
    manifest = {
        "id": package_id, "version": "1.0.0", "name": package_id, "publisher": "Test",
        "description": "Test package", "license": "MIT",
        "compatibility": {"curioRuntime": ">=0.5.0", "major": 1},
        "permissions": [], "dependencies": {"packages": {}, "python": {}, "js": {}},
        "createdAt": "2026-06-01T12:00:00Z",
        "templates": [{
            "id": "caller", "label": "Caller", "category": "computation", "engine": "python",
            "editor": "code", "hasCode": True, "hasWidgets": False, "hasGrammar": False,
            "inputPorts": [], "outputPorts": [{"types": ["JSON"], "cardinality": "1"}],
            "source": "sources/caller.py",
        }],
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w") as zf:
        zf.writestr("manifest.json", json.dumps(manifest))
        zf.writestr("sources/caller.py", "return 1\n")
        for relative, text in modules.items():
            zf.writestr(f"sources/{relative}", text)
    return buf.getvalue()


def _install(user_key: str) -> dict:
    """Install the package for *user_key* and return what a run is handed."""
    from utk_curio.backend.app.packages.application.store_install import install_package_from_archive
    from utk_curio.backend.app.packages.repositories.store import package_dir

    install_package_from_archive(user_key, _archive())
    return {
        "root": str(package_dir(user_key, "ai.test.heights@1") / "sources"),
        "names": ["building_height"],
    }


class _Reply:
    status_code = 200

    def json(self):
        return {"stdout": [], "stderr": "", "output": {"path": "art-1", "dataType": "int"}}


def _fake_sandbox(monkeypatch, sent):
    def fake(method, path, **kwargs):
        sent.append((path, json.loads(kwargs["data"])))
        return _Reply()

    monkeypatch.setattr("utk_curio.backend.app.execution.node_exec.sandbox_request", fake)


def _play(client, token, project_id, node_type):
    return client.post("/processPythonCode", data=json.dumps({
        "code": "    return 1\n", "nodeType": node_type, "nodeId": "n1",
        "dataflowId": project_id, "input": {"path": "", "dataType": "str"},
        "saveOutputDataset": False,
    }), headers=auth_headers(token))


def test_play_hands_a_package_node_its_modules(client, user_and_token, monkeypatch):
    from utk_curio.backend.app.projects.services import _user_dir_key

    user, token = user_and_token
    expected = _install(_user_dir_key(user))
    project_id = create_project(client, token, name="Package modules")
    sent = []
    _fake_sandbox(monkeypatch, sent)

    for node_type in (NODE_TYPE, f"{NODE_TYPE}@1"):
        assert _play(client, token, project_id, node_type).status_code == 200
    assert [body.get("package_modules") for _path, body in sent] == [expected, expected]


def test_play_sends_nothing_new_for_any_other_node(client, user_and_token, monkeypatch):
    from utk_curio.backend.app.projects.services import _user_dir_key

    user, token = user_and_token
    _install(_user_dir_key(user))
    project_id = create_project(client, token, name="Other nodes")
    sent = []
    _fake_sandbox(monkeypatch, sent)

    for node_type in ("curio.builtin/computation-analysis", "PYTHON_COMPUTATION", "ai.test.other/caller"):
        assert _play(client, token, project_id, node_type).status_code == 200
    assert all("package_modules" not in body for _path, body in sent)


def test_a_run_on_a_thread_of_its_own_sends_what_play_sends(app, client, user_and_token, monkeypatch):
    """``execute_python_node`` is what a run on the server calls for each node."""
    import threading

    from utk_curio.backend.app.execution import node_exec
    from utk_curio.backend.app.projects.services import _user_dir_key

    user, token = user_and_token
    expected = _install(_user_dir_key(user))
    sent = []
    _fake_sandbox(monkeypatch, sent)
    run = node_exec.NodeRun(code="    return 1\n", node_type=NODE_TYPE, node_id="n1", save_output_dataset=False)
    box = {}

    def work():
        with app.app_context():
            box["reply"] = node_exec.execute_python_node(user, token, run)

    thread = threading.Thread(target=work)
    thread.start()
    thread.join(timeout=60)
    assert box["reply"][1] == 200
    ((path, body),) = sent
    assert path == "/exec" and body["package_modules"] == expected


def test_the_headless_runner_sends_them_too(tmp_curio):
    from utk_curio.backend.app.execution import runner

    expected = _install("4242")
    calls = []

    def exec_fn(endpoint, payload):
        calls.append((endpoint, payload))
        return {"stdout": [], "stderr": "", "output": {"path": f"art-{len(calls)}", "dataType": "int"}}

    spec = {"dataflow": {"nodes": [
        {"id": "a", "type": "curio.builtin/computation-analysis", "content": "return 1"},
        {"id": "b", "type": NODE_TYPE, "content": "return arg"},
    ], "edges": [{"id": "e1", "source": "a", "target": "b"}]}}
    roster = {
        "curio.builtin/computation-analysis": {"executable": True, "engine": "python"},
        NODE_TYPE: {"executable": True, "engine": "python"},
    }
    report = runner.run_through_node("4242", "p-modules", spec, "b", exec_fn=exec_fn, templates=roster)
    assert report["ok"] is True, report
    (_, builtin), (_, package) = calls
    assert "package_modules" not in builtin
    assert package["package_modules"] == expected


def test_the_ground_truth_harness_is_handed_them(client, tmp_curio):
    from utk_curio.backend.app.common.user_storage import GUEST_KEY

    expected = _install(GUEST_KEY)
    resp = client.post(
        "/api/testing/dataset-paths",
        data=json.dumps({"code": "return 1", "nodeType": NODE_TYPE}),
        content_type="application/json",
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)
    assert resp.get_json()["packageModules"] == expected
