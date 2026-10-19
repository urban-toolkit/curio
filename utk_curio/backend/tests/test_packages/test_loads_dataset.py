"""``loadsDataset``: a template whose nodes load a dataset into the dataflow.

The agents read this flag, not a template's name: an agent whose node target
requires it attaches to such a node, and Solve finds the node a source before
it writes its code (``test_agents/test_agents_by_capability.py``).
curio.builtin's Data Loading declares it, and a package's own loader may.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from utk_curio.backend.app.packages import service as packages_services
from utk_curio.backend.app.packages.domain.manifest import ManifestError, TemplateManifest
from utk_curio.backend.app.projects import services as projects_services
from utk_curio.backend.tests.test_packages.conftest import _manifest_dict
from utk_curio.backend.tests.test_packages.test_available_templates import (  # noqa: F401
    _lockfile_add,
    _template,
    _write_package,
    alice_project,
)

REPO_ROOT = Path(__file__).resolve().parents[4]
SCHEMA = json.loads((REPO_ROOT / "docs/schemas/node-package.v4.json").read_text(encoding="utf-8"))


def _loader(**fields) -> dict:
    template = {
        "id": "fetch-weather", "label": "Fetch weather", "category": "data",
        "engine": "python", "editor": "code", "inputPorts": [],
        "outputPorts": [{"types": ["DATAFRAME"], "cardinality": "1"}],
    }
    template.update(fields)
    return template


def test_the_parser_keeps_the_flag():
    assert TemplateManifest.from_json(_loader(loadsDataset=True), where="t").loads_dataset is True
    assert TemplateManifest.from_json(_loader(), where="t").loads_dataset is False


def test_the_parser_refuses_a_flag_that_is_not_a_boolean():
    with pytest.raises(ManifestError, match="loadsDataset"):
        TemplateManifest.from_json(_loader(loadsDataset="yes"), where="t")


def test_the_schema_describes_the_flag():
    flag = SCHEMA["$defs"]["template"]["properties"]["loadsDataset"]
    assert flag["type"] == "boolean" and flag["description"]
    validator = Draft202012Validator(SCHEMA)
    assert not list(validator.iter_errors(_manifest_dict("test.loaders", kinds=[_loader(loadsDataset=True)])))
    assert list(validator.iter_errors(_manifest_dict("test.loaders", kinds=[_loader(loadsDataset="yes")])))


def test_only_the_builtin_data_loading_declares_it_in_the_shipped_catalog():
    declared = set()
    for path in sorted((REPO_ROOT / "packages").glob("*/manifest.json")):
        manifest = json.loads(path.read_text(encoding="utf-8"))
        declared |= {
            f"{manifest['id']}/{template['id']}"
            for template in manifest.get("templates") or []
            if template.get("loadsDataset")
        }
    # The package loaders (curio.weather's, ai.utk.uhvi's) declare nothing, so
    # the nodes users already have keep the agents they get.
    assert declared == {"curio.builtin/data-loading"}


class TestTheRosterCarriesTheFlag:
    def test_a_template_that_declares_it_says_so_and_the_others_keep_their_shape(
        self, user_and_token, alice_project, tmp_curio
    ):
        user, _ = user_and_token
        key = projects_services._user_dir_key(user)
        _write_package(key, "ai.test.loaders", 1, [
            {**_template("fetch-weather", "Fetch weather"), "loadsDataset": True},
            _template("plot-weather", "Plot weather"),
        ])
        _lockfile_add(key, alice_project, "ai.test.loaders@1")
        rows = {t["id"]: t for t in packages_services.available_templates(key, alice_project)}
        assert rows["ai.test.loaders/fetch-weather"]["loadsDataset"] is True
        assert "loadsDataset" not in rows["ai.test.loaders/plot-weather"]
        snapshot = packages_services.roster_templates(key, alice_project)
        assert snapshot["ai.test.loaders/fetch-weather"]["loadsDataset"] is True
        assert set(snapshot["ai.test.loaders/plot-weather"]) == {"executable", "engine", "contentKind"}

    def test_a_template_declares_it_in_the_accounts_copy_or_the_catalogs(
        self, user_and_token, alice_project, tmp_curio
    ):
        """A package's copy in the account can be older than the catalog's,
        so either declaring the flag is enough."""
        user, _ = user_and_token
        key = projects_services._user_dir_key(user)
        # The account's curio.builtin, from before its Data Loading declared it.
        _write_package(key, "curio.builtin", 1, [_template("data-loading", "Data Loading")])
        _write_package(key, "ai.test.loaders", 1, [
            {**_template("fetch-weather", "Fetch weather"), "loadsDataset": True},
            _template("data-loading", "Named like the built-in loader"),
        ])
        _lockfile_add(key, alice_project, "ai.test.loaders@1")
        snapshot = packages_services.roster_templates(key, alice_project)
        flags = packages_services.template_flags
        for node_type in ("curio.builtin/data-loading", "curio.builtin/data-loading@1", "DATA_LOADING"):
            assert "loadsDataset" in flags(node_type, snapshot), node_type
            assert "loadsDataset" in flags(node_type, None), node_type
        assert "loadsDataset" in flags("ai.test.loaders/fetch-weather", snapshot)
        assert "loadsDataset" not in flags("ai.test.loaders/data-loading", snapshot)
        assert flags("curio.builtin/computation-analysis", snapshot) == frozenset()
        assert flags("", snapshot) == frozenset()
