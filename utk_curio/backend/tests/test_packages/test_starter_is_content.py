"""``starterIsContent``: a template whose ``source`` starter is a node's whole
content, set through its widgets.

A node the Dataflow Builder's plan creates from such a template starts with the
starter and the plan's widgets, and Solve leaves it as it is
(``test_agents/test_routes_starter_templates.py``). ``content_starters`` is what
the plan apply reads them from: the starter and widgets of each template that
opts in, resolved as the project's available templates are.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from utk_curio.backend.app.packages.domain.manifest import ManifestError, package_manifest_from_dict
from utk_curio.backend.app.projects import services as projects_services
from utk_curio.backend.tests.test_packages.conftest import _manifest_dict

SCHEMA = json.loads(
    (Path(__file__).resolve().parents[4] / "docs/schemas/node-package.v4.json").read_text(encoding="utf-8")
)

SPEC = '{"mark": "line", "encoding": {"y": {"field": "[!! y !!]", "type": "quantitative"}}}\n'
WIDGETS = [
    {"name": "x", "type": "text", "label": "X column", "default": "x"},
    {"name": "y", "type": "text", "label": "Y column", "default": "y"},
]


def _chart(**fields) -> dict:
    """A Vega-Lite template that ships its spec; a field given as None is left out."""
    template = {
        "id": "lines", "label": "Lines", "category": "vis_grammar", "engine": "python",
        "editor": "grammar", "behavior": "vega", "grammarId": "vega-lite",
        "hasCode": False, "hasGrammar": True, "hasWidgets": True,
        "inputPorts": [{"types": ["DATAFRAME"], "cardinality": "1"}],
        "outputPorts": [{"types": ["DATAFRAME"], "cardinality": "1"}],
        "source": "sources/lines.vl.json",
        "widgets": WIDGETS,
    }
    template.update(fields)
    return {key: value for key, value in template.items() if value is not None}


def _parse(*templates: dict):
    return package_manifest_from_dict(
        _manifest_dict("test.charts", kinds=list(templates)),
        manifest_path=Path("manifest.json"), dir_name="test.charts@1",
    )


# ---------------------------------------------------------------------------
# The flag
# ---------------------------------------------------------------------------

def test_a_template_says_its_starter_is_its_content():
    (template,) = _parse(_chart(starterIsContent=True)).templates
    assert template.starter_is_content is True


def test_a_template_that_says_nothing_ships_a_starter_to_start_from():
    (template,) = _parse(_chart()).templates
    assert template.starter_is_content is False


def test_the_flag_is_a_boolean():
    with pytest.raises(ManifestError, match="starterIsContent"):
        _parse(_chart(starterIsContent="yes"))


def test_a_template_without_a_source_has_no_starter_to_be_its_content():
    with pytest.raises(ManifestError, match="starterIsContent"):
        _parse(_chart(source=None, starterIsContent=True))


def test_the_schema_declares_the_flag_beside_the_source_it_needs():
    validator = Draft202012Validator(SCHEMA)
    flag = SCHEMA["$defs"]["template"]["properties"]["starterIsContent"]
    assert flag["type"] == "boolean"
    assert SCHEMA["$defs"]["template"]["dependentRequired"]["starterIsContent"] == ["source"]
    assert not list(validator.iter_errors(_manifest_dict("test.charts", kinds=[_chart(starterIsContent=True)])))
    assert list(validator.iter_errors(
        _manifest_dict("test.charts", kinds=[_chart(source=None, starterIsContent=True)])
    ))


# ---------------------------------------------------------------------------
# content_starters
# ---------------------------------------------------------------------------

def _auth(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


@pytest.fixture()
def project_id(client, user_and_token):
    _, token = user_and_token
    body = {"name": "charts", "spec": {"dataflow": {"nodes": [], "edges": [], "packages": []}}, "outputs": []}
    resp = client.post("/api/projects", json=body, headers=_auth(token))
    assert resp.status_code == 201
    return resp.get_json()["id"]


def _write_charts(user_key: str, templates: list[dict], sources: dict[str, str]) -> None:
    from utk_curio.backend.app.packages.repositories.store import user_packages_dir

    d = user_packages_dir(user_key) / "test.charts@1"
    (d / "sources").mkdir(parents=True, exist_ok=True)
    (d / "manifest.json").write_text(json.dumps(_manifest_dict("test.charts", kinds=templates)), encoding="utf-8")
    for rel, text in sources.items():
        (d / rel).write_text(text, encoding="utf-8")


def _enlist(user_key: str, project: str) -> None:
    from utk_curio.backend.app.packages.domain.spec_packages import set_project_packages
    from utk_curio.backend.app.projects import storage as projects_storage

    spec = projects_storage.read_spec(user_key, project)
    set_project_packages(spec, {"test.charts@1"})
    projects_storage.write_spec(user_key, project, spec)


def test_only_a_template_that_opts_in_gives_its_starter_and_widgets(user_and_token, project_id, tmp_curio):
    from utk_curio.backend.app.packages import service as packages_services

    user, _ = user_and_token
    key = projects_services._user_dir_key(user)
    _write_charts(key, [
        _chart(starterIsContent=True),
        _chart(id="bars", label="Bars", source="sources/bars.vl.json"),
    ], {"sources/lines.vl.json": SPEC, "sources/bars.vl.json": SPEC})
    _enlist(key, project_id)

    starters = packages_services.content_starters(
        key, project_id, ["test.charts/lines@1", "test.charts/bars", "curio.builtin/vis-vega"],
    )
    assert set(starters) == {"test.charts/lines"}
    assert starters["test.charts/lines"]["content"] == SPEC
    assert starters["test.charts/lines"]["widgets"] == WIDGETS


def test_a_package_the_project_does_not_hold_gives_none(user_and_token, project_id, tmp_curio):
    from utk_curio.backend.app.packages import service as packages_services

    user, _ = user_and_token
    key = projects_services._user_dir_key(user)
    _write_charts(key, [_chart(starterIsContent=True)], {"sources/lines.vl.json": SPEC})

    assert packages_services.content_starters(key, project_id, ["test.charts/lines"]) == {}
