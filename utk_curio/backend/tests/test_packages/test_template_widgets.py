"""A template declares the widgets a freshly dropped node starts with (#662).

The template's ``widgets`` are in the shape of a node's ``metadata.widgets``,
and its ``source`` places each one as a ``[!! name !!]`` reference. The
canvas copies them into the node it creates, so a package node opens with its
controls in the Widgets tab instead of an old ``[!! name$TYPE$default !!]``
marker in its code.

A widget's name is letters, digits and underscores, not starting with a digit,
and not an input's name, ``input_0``, ``input_1`` and so on: a manifest that
breaks either rule is refused as the Widgets tab and a Parameter node refuse
the name, with the same words. Its type is one of the Widgets tab's kinds, and
no two widgets of a template share a name: a manifest that breaks either is
refused as the Widgets tab refuses the widget, with the same words.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from utk_curio.backend.app.execution.code_references import check_widget_def
from utk_curio.backend.app.packages.domain.manifest import ManifestError, package_manifest_from_dict
from utk_curio.backend.app.packages.repositories.archive import InstallerError
from utk_curio.backend.app.packages.repositories.manifests import load_package_manifest
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


def _number(name: str) -> dict:
    return {"name": name, "type": "number", "label": "K", "default": 1}


def _load(tmp_path: Path, raw: dict):
    """*raw* read from a package folder, as every install, listing and build
    reads a manifest."""
    root = tmp_path / "ai.test.demo@1"
    root.mkdir()
    (root / "manifest.json").write_text(json.dumps(raw), encoding="utf-8")
    return load_package_manifest(root)


@pytest.mark.parametrize("name", ["input_0", "input_12"])
def test_a_widget_named_as_an_input_is_read_is_refused_as_the_widgets_tab_refuses_it(tmp_path, name):
    """``check_widget_def`` is the Widgets tab's own check (``checkWidgetDef``),
    held to it by ``widgetChecks.cases.json``; a Parameter node's widget goes
    through the same check."""
    tab_says = check_widget_def(_number(name))
    assert tab_says
    with pytest.raises(ManifestError) as refused:
        _load(tmp_path, _with_template(hasWidgets=True, widgets=[WIDGETS[0], _number(name)]))
    assert str(refused.value).endswith(f".templates[0].widgets[1]: {tab_says}")


def test_a_package_declaring_one_is_not_installed(install_package):
    with pytest.raises(InstallerError) as refused:
        install_package("guest", _with_template(hasWidgets=True, widgets=[_number("input_0")]))
    assert str(refused.value).endswith(f".templates[0].widgets[0]: {check_widget_def(_number('input_0'))}")


@pytest.mark.parametrize("name", ["input", "inputs", "my_input_0"])
def test_a_name_that_only_looks_like_an_input_is_kept(tmp_path, name):
    """The Widgets tab takes these names, so a template may declare them."""
    assert check_widget_def(_number(name)) is None
    widgets = [_number(name)]
    assert _load(tmp_path, _with_template(hasWidgets=True, widgets=widgets)).templates[0].widgets == widgets


#: Names the schema's widget name pattern refuses, and the Widgets tab with its
#: sentence for a name's shape.
BADLY_SHAPED = {
    "a space": "has space",
    "a leading digit": "2x",
    "no name": "",
    "a dash": "rain-mm",
    "a letter outside A to Z": "café",
    "65 characters": "x" * 65,
}

#: The schema's pattern is ECMA-262, as an editor and the canvas read it, where
#: ``$`` ends the text, so it refuses a name that ends in a line break, and so
#: does the Widgets tab (``widgetChecks.cases.json``). Python's ``re.match``
#: lets one through, its ``$`` matching before a final line break, and so does
#: the Python ``jsonschema``, which reads the pattern with ``re.search``.
ENDS_IN_A_LINE_BREAK = "src\n"

#: Names of the widget shape, the longest included.
WELL_SHAPED = {
    "a leading underscore": "_x",
    "mixed case with a digit": "Rain_mm_2",
    "64 characters": "x" * 64,
}


@pytest.mark.parametrize(
    "name",
    [*BADLY_SHAPED.values(), ENDS_IN_A_LINE_BREAK],
    ids=[*BADLY_SHAPED, "a line break at its end"],
)
def test_a_badly_shaped_name_is_refused_as_the_widgets_tab_refuses_it(tmp_path, name):
    """The canvas drops a widget whose name has another shape, so the manifest
    is refused, with the words the Widgets tab and a Parameter node refuse the
    name with."""
    tab_says = check_widget_def(_number(name))
    assert tab_says
    with pytest.raises(ManifestError) as refused:
        _load(tmp_path, _with_template(hasWidgets=True, widgets=[WIDGETS[0], _number(name)]))
    assert str(refused.value).endswith(f".templates[0].widgets[1]: {tab_says}")


def test_a_package_declaring_a_badly_shaped_name_is_not_installed(install_package):
    with pytest.raises(InstallerError) as refused:
        install_package("guest", _with_template(hasWidgets=True, widgets=[_number("has space")]))
    assert str(refused.value).endswith(f".templates[0].widgets[0]: {check_widget_def(_number('has space'))}")


@pytest.mark.parametrize("name", list(WELL_SHAPED.values()), ids=list(WELL_SHAPED))
def test_a_well_shaped_name_is_kept(tmp_path, name):
    """The Widgets tab takes these names, so a template may declare them."""
    assert check_widget_def(_number(name)) is None
    widgets = [_number(name)]
    assert _load(tmp_path, _with_template(hasWidgets=True, widgets=widgets)).templates[0].widgets == widgets


#: Types outside the schema's widget ``type`` enum, which the Widgets tab
#: refuses and the canvas drops.
UNKNOWN_TYPES = {
    "the old marker's type": "INPUT_TEXT",
    "a control Curio has no widget for": "colour",
    "a kind in capitals": "Number",
    "an empty type": "",
}


@pytest.mark.parametrize("kind", list(UNKNOWN_TYPES.values()), ids=list(UNKNOWN_TYPES))
def test_a_widget_of_an_unknown_type_is_refused_as_the_widgets_tab_refuses_it(tmp_path, kind):
    """The canvas drops a widget whose type is not one of the Widgets tab's
    kinds, so the manifest is refused, with the words the Widgets tab refuses
    the type with. The widget has no default, which a manifest may leave out."""
    widget = {"name": "tint", "type": kind, "label": "Tint"}
    tab_says = check_widget_def(widget)
    assert tab_says
    with pytest.raises(ManifestError) as refused:
        _load(tmp_path, _with_template(hasWidgets=True, widgets=[WIDGETS[0], widget]))
    assert str(refused.value).endswith(f".templates[0].widgets[1]: {tab_says}")


def test_a_package_declaring_an_unknown_type_is_not_installed(install_package):
    widget = {"name": "tint", "type": "colour", "label": "Tint", "default": "red"}
    with pytest.raises(InstallerError) as refused:
        install_package("guest", _with_template(hasWidgets=True, widgets=[widget]))
    assert str(refused.value).endswith(f".templates[0].widgets[0]: {check_widget_def(widget)}")


@pytest.mark.parametrize("kind", SCHEMA["$defs"]["widget"]["properties"]["type"]["enum"])
def test_every_kind_the_schema_names_is_kept(tmp_path, kind):
    """The schema's kinds are the Widgets tab's (``test_the_widget_types`` in
    ``test_execution/test_code_references.py``): a template may declare a
    widget of any of them, without a default. Any other type is refused, above."""
    widgets = [{"name": "w", "type": kind}]
    assert _load(tmp_path, _with_template(hasWidgets=True, widgets=widgets)).templates[0].widgets == widgets


def test_two_widgets_of_one_name_are_refused_as_the_widgets_tab_refuses_the_second(tmp_path):
    """The canvas keeps the first of two widgets that share a name and drops
    the other, so the manifest is refused at the second, with the words the
    Widgets tab refuses a name the node already has with. Neither has a
    default, which a manifest may leave out."""
    first = {"name": "factor", "type": "number", "label": "Factor"}
    second = {"name": "factor", "type": "text", "label": "Factor as text"}
    tab_says = check_widget_def(second, [first])
    assert tab_says
    with pytest.raises(ManifestError) as refused:
        _load(tmp_path, _with_template(hasWidgets=True, widgets=[first, WIDGETS[0], second]))
    assert str(refused.value).endswith(f".templates[0].widgets[2]: {tab_says}")


def test_a_package_declaring_one_name_twice_is_not_installed(install_package):
    widgets = [_number("factor"), _number("factor")]
    with pytest.raises(InstallerError) as refused:
        install_package("guest", _with_template(hasWidgets=True, widgets=widgets))
    assert str(refused.value).endswith(f".templates[0].widgets[1]: {check_widget_def(widgets[1], widgets[:1])}")


def test_one_name_in_two_templates_is_kept(tmp_path):
    """Each template makes a node of its own, and a name is unique in its node."""
    raw = _with_template(hasWidgets=True, widgets=[_number("factor")])
    raw["templates"].append({**raw["templates"][0], "id": "other-kind", "label": "Other"})
    manifest = _load(tmp_path, raw)
    assert [template.widgets for template in manifest.templates] == [[_number("factor")], [_number("factor")]]


class TestTheSchema:
    def _errors(self, widgets) -> list:
        return list(Draft202012Validator(SCHEMA).iter_errors(_with_template(widgets=widgets)))

    def test_declared_widgets_validate(self):
        assert not self._errors(WIDGETS)

    def test_every_control_validates(self):
        assert not self._errors([
            {"name": "rain", "type": "slider", "default": 0, "options": {"min": 0, "max": 50, "step": 0.5, "units": "mm"}},
            {"name": "k", "type": "number", "default": 1, "options": {"min": 1, "max": 3}},
            {"name": "year", "type": "choice", "default": "2050", "options": {"choices": ["2050", "2100"], "display": "radio"}},
            {"name": "classes", "type": "checkbox-group", "default": ["water"], "options": {"choices": ["water", "forest"]}},
            {"name": "modes", "type": "multi-select", "default": [], "options": {"choices": ["walk", "bike"]}},
            {"name": "when", "type": "datetime", "default": "2026-06-21T12:00:00"},
            {"name": "origin", "type": "location", "default": {"lat": 41.8781, "lon": -87.6298}},
        ])

    def test_a_name_that_only_looks_like_an_input_validates(self):
        assert not self._errors([_number("input"), _number("inputs"), _number("my_input_0")])

    @pytest.mark.parametrize("name", list(BADLY_SHAPED.values()), ids=list(BADLY_SHAPED))
    def test_a_badly_shaped_name_is_refused(self, name):
        """The names a manifest is refused for, above."""
        assert self._errors([_number(name)])

    def test_a_well_shaped_name_validates(self):
        assert not self._errors([_number(name) for name in WELL_SHAPED.values()])

    @pytest.mark.parametrize(
        "widget",
        [
            {"name": "has space", "type": "text", "default": ""},
            {"name": "input_0", "type": "number", "default": 1},
            {"name": "input_12", "type": "number", "default": 1},
            {"name": "src", "type": "INPUT_TEXT", "default": ""},
            {"name": "src", "type": "text", "default": "", "marker": "src$INPUT_TEXT$"},
            {"name": "src", "type": "choice", "default": "a", "options": {"choices": [1, 2]}},
            {"name": "s", "type": "choice", "default": "a", "options": {"choices": ["a"], "display": "carousel"}},
            {"name": "s", "type": "slider", "default": 0, "options": {"min": 0, "max": 1, "step": 0}},
            {"name": "s", "type": "slider", "default": 0, "options": {"min": "0", "max": 1}},
            {"name": "s", "type": "slider", "default": 0, "options": {"units": 5}},
        ],
        ids=[
            "name with a space",
            "the name input 0 is read by",
            "the name input 12 is read by",
            "unknown type",
            "unknown key",
            "choices that are not text",
            "unknown display",
            "a step of zero",
            "a bound that is not a number",
            "units that are not text",
        ],
    )
    def test_a_malformed_widget_is_refused(self, widget):
        assert self._errors([widget])
