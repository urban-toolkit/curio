"""The built-in Data Loading node's Data widget, and what any template's
widgets and ``widgetsWithCode`` give its nodes.

A fresh Data Loading node opens with its starter, which loads the Data
Catalog dataset its Data widget holds, and shows the widget above its code
(``widgetsWithCode``). A node an agent creates from any template starts with
the widgets the template declares, as the roster names them to the agents
(``declared_widgets``), whatever writes its content.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from utk_curio.backend.app.packages.domain.manifest import ManifestError, TemplateManifest
from utk_curio.backend.app.projects import services as projects_services
from utk_curio.backend.tests.test_packages.conftest import _manifest_dict
from utk_curio.backend.tests.test_packages.test_starter_is_content import (  # noqa: F401
    SPEC,
    WIDGETS,
    _chart,
    _enlist,
    _write_charts,
    project_id,
)

REPO_ROOT = Path(__file__).resolve().parents[4]
BUILTIN = REPO_ROOT / "packages" / "curio.builtin@1"
SCHEMA = json.loads((REPO_ROOT / "docs/schemas/node-package.v4.json").read_text(encoding="utf-8"))
DATA = {"name": "data", "type": "dataset", "label": "Data", "default": ""}


def _auth(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _loader(**fields) -> dict:
    template = {
        "id": "fetch", "label": "Fetch", "category": "data", "engine": "python", "editor": "code",
        "inputPorts": [], "outputPorts": [{"types": ["DATAFRAME"], "cardinality": "1"}],
    }
    template.update(fields)
    return template


# ---------------------------------------------------------------------------
# widgetsWithCode
# ---------------------------------------------------------------------------

def test_the_parser_keeps_the_flag():
    assert TemplateManifest.from_json(_loader(widgetsWithCode=True), where="t").widgets_with_code is True
    assert TemplateManifest.from_json(_loader(), where="t").widgets_with_code is False


def test_the_parser_refuses_a_flag_that_is_not_a_boolean():
    with pytest.raises(ManifestError, match="widgetsWithCode"):
        TemplateManifest.from_json(_loader(widgetsWithCode="yes"), where="t")


def test_the_schema_describes_the_flag():
    flag = SCHEMA["$defs"]["template"]["properties"]["widgetsWithCode"]
    assert flag["type"] == "boolean" and flag["description"]
    validator = Draft202012Validator(SCHEMA)
    assert not list(validator.iter_errors(_manifest_dict("test.loaders", kinds=[_loader(widgetsWithCode=True)])))


def test_the_package_listing_carries_the_flag_and_the_data_widget():
    from utk_curio.backend.app.packages.repositories.manifests import load_package_manifest
    from utk_curio.backend.app.packages.schemas.responses import package_payload

    payload = package_payload(load_package_manifest(BUILTIN))
    by_id = {template["templateId"]: template for template in payload["templates"]}
    loading = by_id["data-loading"]
    assert loading["widgetsWithCode"] is True
    assert loading["source"] == "sources/data-loading.py"
    assert loading["widgets"] == [DATA]
    assert by_id["data-transformation"]["widgetsWithCode"] is False


# ---------------------------------------------------------------------------
# The starter
# ---------------------------------------------------------------------------

def test_the_starter_reads_the_data_widget_and_is_hashed():
    source = (BUILTIN / "sources" / "data-loading.py").read_text(encoding="utf-8")
    assert source == "data = curio_load_data([!! data !!])\nreturn data\n"
    integrity = json.loads((BUILTIN / "integrity.json").read_text(encoding="utf-8"))
    assert "sources/data-loading.py" in integrity["sha256"]


def test_a_fresh_data_loading_node_opens_with_its_starter(client, user_and_token):
    """The starters the canvas fills a fresh node from (``/starters``): Data
    Loading's, named for its file."""
    _, token = user_and_token
    assert client.get("/api/packages", headers=_auth(token)).status_code == 200
    starters = client.get("/starters", headers=_auth(token)).get_json()
    [starter] = [s for s in starters if s["type"] == "curio.builtin/data-loading@1"]
    assert starter["name"] == "data-loading"
    assert starter["code"] == (BUILTIN / "sources" / "data-loading.py").read_text(encoding="utf-8")


def test_the_starter_writes_the_id_the_widget_holds():
    from utk_curio.backend.app.execution.code_references import resolve_references

    source = (BUILTIN / "sources" / "data-loading.py").read_text(encoding="utf-8")
    code, problems = resolve_references(source, [{**DATA, "value": "data.utk.trees"}])
    assert problems == []
    assert code == 'data = curio_load_data("data.utk.trees")\nreturn data\n'
    code, problems = resolve_references(source, [DATA])
    assert code == source
    assert [p["message"] for p in problems] == [
        "[!! data !!]: drop a file or a Data Catalog dataset on Data first.",
    ]


def test_a_scan_reads_the_id_the_data_widget_holds():
    """The id a dataset widget holds is in no literal call until the run
    writes it in, so the scans for the datasets and collections a run reads
    look at the code as the run writes it (``node_run_code``)."""
    from utk_curio.backend.app.datasets.domain.code_refs import dataset_ids_in_code
    from utk_curio.backend.app.execution.code_references import node_run_code

    source = (BUILTIN / "sources" / "data-loading.py").read_text(encoding="utf-8")
    node = {"id": "load", "content": source, "metadata": {"widgets": [{**DATA, "value": "data.utk.trees"}]}}
    assert node_run_code(node) == 'data = curio_load_data("data.utk.trees")\nreturn data\n'
    assert dataset_ids_in_code(node_run_code(node)) == ["data.utk.trees"]
    # An empty widget and a reference to no widget stay as written.
    assert node_run_code({**node, "metadata": {"widgets": [DATA]}}) == source
    other = {**node, "content": "x = [!! other !!]\nreturn curio_load_data([!! data !!])"}
    assert node_run_code(other) == 'x = [!! other !!]\nreturn curio_load_data("data.utk.trees")'
    # Without widgets, the code; without code, nothing.
    assert node_run_code({"content": source}) == source
    assert node_run_code({"metadata": {"widgets": [DATA]}}) == ""
    assert node_run_code("not a node") == ""


# ---------------------------------------------------------------------------
# declared_widgets
# ---------------------------------------------------------------------------

def test_every_template_gives_the_widgets_it_declares(client, user_and_token, project_id, tmp_curio):
    from utk_curio.backend.app.packages import service as packages_services

    user, token = user_and_token
    key = projects_services._user_dir_key(user)
    # The listing seeds the account's built-in nodes, as a canvas's load does.
    assert client.get("/api/packages", headers=_auth(token)).status_code == 200
    _write_charts(key, [
        _chart(starterIsContent=True),
        _chart(id="bars", label="Bars", source="sources/bars.vl.json"),
        _chart(id="plain", label="Plain", source=None, widgets=None),
    ], {"sources/lines.vl.json": SPEC, "sources/bars.vl.json": SPEC})
    _enlist(key, project_id)

    declared = packages_services.declared_widgets(
        key, project_id, ["test.charts/lines@1", "test.charts/bars", "test.charts/plain", "curio.builtin/data-loading"],
    )
    assert declared == {
        "test.charts/lines": WIDGETS,
        "test.charts/bars": WIDGETS,
        "curio.builtin/data-loading": [DATA],
    }


def test_a_package_the_project_does_not_hold_gives_none(user_and_token, project_id, tmp_curio):
    from utk_curio.backend.app.packages import service as packages_services

    user, _ = user_and_token
    key = projects_services._user_dir_key(user)
    _write_charts(key, [_chart(id="bars", label="Bars", source="sources/bars.vl.json")], {"sources/bars.vl.json": SPEC})

    assert packages_services.declared_widgets(key, project_id, ["test.charts/bars"]) == {}


def test_a_planned_node_starts_with_its_templates_widgets_and_the_plans_set_over_them():
    from utk_curio.backend.app.agents.application.proposals.plan_scenarios import created_node_metadata

    plan_node = {"ref": "load", "widgets": [{"name": "data", "type": "dataset", "value": "data.utk.trees"}]}
    metadata = created_node_metadata(plan_node, {}, [], None, [DATA])
    assert metadata["widgets"] == [{**DATA, "value": "data.utk.trees"}]
    assert created_node_metadata({"ref": "load"}, {}, [], None, [DATA]) == {"widgets": [DATA]}
    assert created_node_metadata({"ref": "load"}, {}, [], None, None) == {}
