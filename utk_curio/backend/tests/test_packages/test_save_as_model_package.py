"""Save as package node of a node that loads a model makes a model package of its own.

A new package saved from a canvas node whose code runs a model the account
holds (``curio_load_model("<id>")``) is a model package (kind ``model``): it
copies that model's weights and ``model`` block, declares the model's
libraries, and its node names the new package's id. So it runs, exports and
imports without the model it was copied from. A node that names no model the
account holds, and a node saved into a package already installed, make a node
package as before.
"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

from utk_curio.backend.app.packages.application.store_install import install_package_from_archive
from utk_curio.backend.app.packages.repositories.store import package_dir
from utk_curio.backend.app.projects import services as projects_services

LOCAL_RELIEF_ID = "model.example.local-relief"
LOCAL_RELIEF = f"{LOCAL_RELIEF_ID}@1"
LOCAL_RELIEF_FOLDER = Path(__file__).resolve().parents[4] / "docs" / "bring-your-own-model" / LOCAL_RELIEF
WEIGHTS = "models/local_relief.onnx"

NEW_ID = "curio.canvas.draft.relief"
NEW_DIR = f"{NEW_ID}@1"


def _auth(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _local_relief_archive() -> bytes:
    """Local Relief as an export writes it: its files at the root, its
    integrity record left out."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(LOCAL_RELIEF_FOLDER.rglob("*")):
            rel = path.relative_to(LOCAL_RELIEF_FOLDER).as_posix()
            if path.is_file() and rel != "integrity.json" and "__pycache__" not in rel:
                archive.write(path, rel)
    return buf.getvalue()


def _code(model_id: str) -> str:
    return (
        "import numpy as np\n"
        f'model = curio_load_model("{model_id}")\n'
        'return float(np.abs(model.run({"height": np.zeros((1, 1, 8, 8), dtype=np.float32)})[0]).sum())\n'
    )


def _draft(code: str, package_id: str = NEW_ID) -> dict:
    """What Save as package node sends for a new package holding one node."""
    return {
        "manifest": {
            "id": package_id,
            "version": "1.0.0",
            "name": "Relief from the canvas",
            "publisher": "Local palette",
            "description": "Created from canvas Save As.",
            "license": "MIT",
            "compatibility": {"curioRuntime": ">=0.5.0", "major": 1},
            "permissions": [],
            "dependencies": {"packages": {}, "python": {}, "js": {}},
            "templates": [{
                "id": "python-computation",
                "label": "Python Computation",
                "category": "computation",
                "engine": "python",
                "editor": "code",
                "hasCode": True,
                "hasWidgets": False,
                "hasGrammar": False,
                "inputPorts": [],
                "outputPorts": [{"types": ["VALUE"], "cardinality": "1"}],
                "source": "sources/python-computation.py",
            }],
        },
        "sources": {"python-computation": {"filename": "python-computation.py", "code": code}},
    }


def _manifest(folder: Path) -> dict:
    return json.loads((folder / "manifest.json").read_text(encoding="utf-8"))


def _source_model_block() -> dict:
    return _manifest(LOCAL_RELIEF_FOLDER)["model"]


def test_a_new_package_of_a_node_that_loads_a_model_is_a_model_package_with_a_copy_of_its_weights(tmp_curio):
    from utk_curio.backend.app.packages.application.factory_install import install_draft

    install_package_from_archive("guest", _local_relief_archive())

    built, _ = install_draft("guest", _draft(_code(LOCAL_RELIEF_ID)), replace=False)

    folder = package_dir("guest", NEW_DIR)
    manifest = _manifest(folder)
    assert (built.manifest.kind, manifest.get("kind")) == ("model", "model")
    assert manifest["model"] == _source_model_block()
    assert (folder / WEIGHTS).read_bytes() == (LOCAL_RELIEF_FOLDER / WEIGHTS).read_bytes()
    # The model's runtime is the package's library, beside what its code imports.
    assert manifest["dependencies"]["python"] == {"numpy": "*", "onnxruntime": ">=1.17"}
    # Its node names the new package.
    code = (folder / "sources" / "python-computation.py").read_text(encoding="utf-8")
    assert f'curio_load_model("{NEW_ID}")' in code
    assert LOCAL_RELIEF_ID not in code


def test_the_new_model_package_runs_without_the_model_it_was_copied_from(tmp_curio):
    from utk_curio.backend.app.packages.application.factory_install import install_draft
    from utk_curio.backend.app.packages.application.model_packages import resolve_model_dirs
    from utk_curio.backend.app.packages.application.store_install import remove_package

    install_package_from_archive("guest", _local_relief_archive())
    install_draft("guest", _draft(_code(LOCAL_RELIEF_ID)), replace=False)

    remove_package("guest", LOCAL_RELIEF)

    assert resolve_model_dirs("guest", [NEW_ID, LOCAL_RELIEF_ID]) == {NEW_ID: str(package_dir("guest", NEW_DIR))}


def test_the_install_route_says_which_model_it_copied(client, user_and_token):
    user, token = user_and_token
    install_package_from_archive(projects_services._user_dir_key(user), _local_relief_archive())

    resp = client.post("/api/packages/factory/install", data=json.dumps(_draft(_code(LOCAL_RELIEF_ID))),
                       headers=_auth(token))

    assert resp.status_code == 201, resp.get_data(as_text=True)
    body = resp.get_json()
    assert (body["package"]["kind"], body["package"]["dirName"], body.get("copiedModel")) == (
        "model", NEW_DIR, LOCAL_RELIEF_ID,
    )
    assert body["package"]["model"]["entry"] == WEIGHTS


def test_the_build_route_exports_the_same_model_package(client, user_and_token):
    user, token = user_and_token
    install_package_from_archive(projects_services._user_dir_key(user), _local_relief_archive())

    resp = client.post("/api/packages/factory/build", data=json.dumps(_draft(_code(LOCAL_RELIEF_ID))),
                       headers=_auth(token))

    assert resp.status_code == 200, resp.get_data(as_text=True)
    with zipfile.ZipFile(io.BytesIO(resp.data)) as archive:
        assert archive.read(WEIGHTS) == (LOCAL_RELIEF_FOLDER / WEIGHTS).read_bytes()
        manifest = json.loads(archive.read("manifest.json"))
        code = archive.read("sources/python-computation.py").decode("utf-8")
    assert (manifest["kind"], manifest["model"]) == ("model", _source_model_block())
    assert f'curio_load_model("{NEW_ID}")' in code


def test_a_node_whose_model_the_account_does_not_hold_makes_a_node_package(tmp_curio):
    from utk_curio.backend.app.packages.application.factory_install import install_draft

    built, _ = install_draft("guest", _draft(_code("model.example.nowhere")), replace=False)

    folder = package_dir("guest", NEW_DIR)
    assert (built.manifest.kind, "kind" in _manifest(folder)) == ("node", False)
    assert not (folder / "models").exists()
    assert 'curio_load_model("model.example.nowhere")' in (folder / "sources" / "python-computation.py").read_text(
        encoding="utf-8"
    )


def test_a_node_saved_into_an_installed_node_package_keeps_it_a_node_package(tmp_curio):
    from utk_curio.backend.app.packages.application.factory_install import install_draft

    install_package_from_archive("guest", _local_relief_archive())
    install_draft("guest", _draft("return 1\n", package_id="ai.test.tools"), replace=False)

    built, _ = install_draft("guest", _draft(_code(LOCAL_RELIEF_ID), package_id="ai.test.tools"), replace=True)

    folder = package_dir("guest", "ai.test.tools@1")
    assert (built.manifest.kind, "kind" in _manifest(folder)) == ("node", False)
    assert not (folder / "models").exists()
