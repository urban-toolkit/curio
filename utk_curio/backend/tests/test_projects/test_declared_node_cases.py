"""The backend decides what a node is by what its template declares, as the
canvas does: ``registry/declaredNodes.cases.json`` holds the cases, and
``src/tests/registry/declaredNodesCases.test.ts`` runs the same cases through
the canvas's rules.

The case packages are written to a catalog of their own
(``CURIO_PACKAGES_ROOT``); ``curio.builtin@1`` is read where Curio ships it.
The rules are imported inside each test, so a checkout without one fails each
test on its own.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

CASES_FILE = (
    Path(__file__).resolve().parents[3]
    / "frontend" / "urban-workflows" / "src" / "registry" / "declaredNodes.cases.json"
)


def _cases():
    if not CASES_FILE.is_file():
        return [pytest.param(None, id="cases-file-missing")]
    cases = json.loads(CASES_FILE.read_text(encoding="utf-8"))["cases"]
    return [pytest.param(case, id=case["name"]) for case in cases]


@pytest.fixture
def catalog(tmp_path, monkeypatch) -> Path:
    """The case file's packages, in a catalog that holds nothing else."""
    root = tmp_path / "catalog"
    for manifest in json.loads(CASES_FILE.read_text(encoding="utf-8"))["packages"]:
        folder = root / f"{manifest['id']}@{manifest['compatibility']['major']}"
        folder.mkdir(parents=True)
        (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setenv("CURIO_PACKAGES_ROOT", str(root))
    return root


@pytest.mark.parametrize("case", _cases())
def test_the_backend_decides_each_case_as_the_canvas_does(catalog, case):
    assert case is not None, f"{CASES_FILE} is missing"
    from utk_curio.backend.app.datasets.application.export import loads_data
    from utk_curio.backend.app.projects.dashboard_payload import draws_its_own_output, passes_through
    from utk_curio.backend.app.projects.services import _is_sink_node_type
    from utk_curio.backend.app.projects.template_grammars import TemplateGrammars

    packages = TemplateGrammars.for_account(None)
    node = {"id": "n", "type": case["type"], "content": case.get("content", "")}
    assert {
        "passThrough": passes_through(node, packages),
        "selfDrawn": draws_its_own_output(node, packages),
        "nonProducing": _is_sink_node_type(case["type"], packages),
        "loadsData": loads_data(case["type"], packages),
    } == {
        "passThrough": case["passThrough"],
        "selfDrawn": case["selfDrawn"],
        "nonProducing": case["nonProducing"],
        "loadsData": case["loadsData"],
    }
