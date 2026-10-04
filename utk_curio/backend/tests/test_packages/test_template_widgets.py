"""A template declares the widgets a freshly dropped node starts with (#662).

The template's ``widgets`` are in the shape of a node's ``metadata.widgets``,
and its ``source`` places each one as a ``[!! name !!]`` reference. The
canvas copies them into the node it creates, so a package node opens with its
controls in the Widgets tab instead of an old ``[!! name$TYPE$default !!]``
marker in its code.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from utk_curio.backend.app.packages.domain.manifest import ManifestError, package_manifest_from_dict
from utk_curio.backend.app.packages.schemas.responses import package_payload
from utk_curio.backend.tests.test_packages.conftest import _manifest_dict

REPO_ROOT = Path(__file__).resolve().parents[4]
SCHEMA = json.loads((REPO_ROOT / "docs/schemas/node-package.v4.json").read_text(encoding="utf-8"))

WIDGETS = [
    {"name": "src", "type": "text", "label": "Raster path", "default": "./a.tif"},
    {"name": "season", "type": "choice", "default": "summer", "options": {"choices": ["summer", "winter"]}},
]


def _with_template(**extra) -> dict:
    raw = _manifest_dict()
    raw["templates"][0].update(extra)
    return raw


def _parse(raw: dict):
    return package_manifest_from_dict(raw, manifest_path=Path("manifest.json"), dir_name="ai.test.demo@1")


def test_declared_widgets_are_parsed_and_served():
    manifest = _parse(_with_template(widgets=WIDGETS))
    assert manifest.templates[0].widgets == WIDGETS
    assert package_payload(manifest)["templates"][0]["widgets"] == WIDGETS


def test_a_template_without_widgets_serves_none():
    manifest = _parse(_manifest_dict())
    assert manifest.templates[0].widgets is None
    assert package_payload(manifest)["templates"][0]["widgets"] is None


@pytest.mark.parametrize(
    "widgets",
    [
        {"name": "src", "type": "text"},
        ["src"],
        [{"type": "text", "default": ""}],
        [{"name": "src", "default": ""}],
    ],
    ids=["not a list", "not an object", "no name", "no type"],
)
def test_malformed_widgets_are_refused(widgets):
    with pytest.raises(ManifestError, match="widgets must be a list of objects"):
        _parse(_with_template(widgets=widgets))


class TestTheSchema:
    def _errors(self, widgets) -> list:
        return list(Draft202012Validator(SCHEMA).iter_errors(_with_template(widgets=widgets)))

    def test_declared_widgets_validate(self):
        assert not self._errors(WIDGETS)

    @pytest.mark.parametrize(
        "widget",
        [
            {"name": "has space", "type": "text", "default": ""},
            {"name": "src", "type": "INPUT_TEXT", "default": ""},
            {"name": "src", "type": "text", "default": "", "marker": "src$INPUT_TEXT$"},
            {"name": "src", "type": "choice", "default": "a", "options": {"choices": [1, 2]}},
        ],
        ids=["name with a space", "unknown type", "unknown key", "choices that are not text"],
    )
    def test_a_malformed_widget_is_refused(self, widget):
        assert self._errors([widget])
