"""The settings of eight package nodes are widgets, read by chip in their call.

A pinned node's widgets are its dashboard tile's controls, and a scenario
varies a node's widgets: a setting held only as a constant in a node's code
is neither. So these eight nodes declare each setting their one call takes as
a widget of their template, with the default the constant held, and the call
reads it by chip, as Rasterization's Rasterize Buildings does
(``zoom=int([!! zoom !!])``):

- Media: Sample Video Frames, Split Audio and Split Video;
- SAM 3: Track Objects and Segment Images;
- DDRNet23-Slim: Image Segmentation;
- Weather: UTCI from raster + weather and Reproject census.

A number chip is cast to the type its constant had, ``float`` or ``int``, since
a run writes a whole number as ``2``, not ``2.0`` (``widget_literal``). A list
is read as it is. A setting that may be None stays a constant: no widget
holds None (a number widget's value is a finite number, ``check_widget_value``).
Track Objects keeps two, ``FORGET_SECONDS`` and ``TO_SECONDS``. Image
Segmentation's ``classes`` is a text list whose empty value reports every
class, as None did (``segment_images`` reads ``classes or`` every label).

The shipped dataflows that hold these nodes give them their template's
widgets and call. Each widget is its template's, default and all, with the
value the node used before set as its ``value`` where it differs from the
default, as the other shipped dataflows hold a template's widget and as a
plan or a node.create sets one. So each call gets what it got before.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[4]
PACKAGES = REPO / "packages"
EXAMPLES = REPO / "docs" / "examples"
#: The casts a number chip takes, by the name the call writes.
CASTS = {"float": float, "int": int}
#: What Track Objects looks for, as it ships.
TRACKED = [
    "curb ramp", "curb cut", "tactile paving", "bollard", "pole",
    "construction barrier", "traffic cone", "person",
]
#: Each node's settings, in its call's order: ``(widget, kind, default, cast)``,
#: the cast None for a list, which the call reads as it is. Segment Images'
#: labels are its package's 35, which its manifest names (``model.labels``).
SETTINGS = {
    "curio.media/video-frames": [
        ("every_seconds", "number", 2.0, "float"),
        ("max_frames_per_video", "number", 300, "int"),
    ],
    "curio.media/split-audio": [
        ("window_seconds", "number", 5.0, "float"),
        ("max_windows_per_recording", "number", 2000, "int"),
    ],
    "curio.media/split-video": [
        ("block_seconds", "number", 60.0, "float"),
        ("width", "number", 960, "int"),
        ("max_frames", "number", 30000, "int"),
    ],
    "model.curio.sam3/track-objects": [
        ("labels", "text-list", TRACKED, None),
        ("every_seconds", "number", 0.5, "float"),
        ("from_seconds", "number", 0, "float"),
        ("max_frames", "number", 450, "int"),
        ("width", "number", 960, "int"),
    ],
    "model.curio.sam3/segment-images": [
        ("labels", "text-list", "model.labels", None),
        ("threshold", "slider", 0.5, "float"),
        ("width", "number", 960, "int"),
        ("max_images", "number", 300, "int"),
    ],
    "model.curio.ddrnet23-slim/image-segmentation": [
        ("classes", "text-list", [], None),
    ],
    "curio.weather/utci-compute": [
        ("timestamp", "slider", 12, "int"),
        ("upscale_factor", "number", 1.0, "float"),
    ],
    "curio.weather/census-reproject": [
        ("source_crs", "number", 32632, "int"),
        ("target_crs", "number", 3395, "int"),
    ],
}
#: The settings that may be None, kept as constants: ``{constant: (keyword,
#: value)}``.
CONSTANTS = {
    "model.curio.sam3/track-objects": {"FORGET_SECONDS": ("forget_seconds", 10), "TO_SECONDS": ("to_seconds", None)},
}
#: Each shipped dataflow's node of the eight, by file and node id, and the
#: values its call got before its settings were widgets: what its widgets
#: hold now, as their values or their defaults. Example 10's second node held
#: ``classes = None``.
EXAMPLE_VALUES = {
    ("10-street-vision-cv-analysis.json", "4067fb98-3ed5-497a-97a5-41a98ce1085b"): {
        "classes": ["vegetation", "terrain", "sky", "road", "sidewalk", "building"],
    },
    ("10-street-vision-cv-analysis.json", "b7d41c2e-5a8f-4c61-9e0b-2f3a6d9c8e14"): {"classes": []},
    ("21-storage-photos-and-videos.json", "survey-frames"): {"every_seconds": 0.25, "max_frames_per_video": 300},
    ("22-storage-audio-recordings.json", "noise-split"): {"window_seconds": 0.1, "max_windows_per_recording": 2000},
    ("31-sideseeing-objects-along-a-walk.json", "walk-tracking"): {
        "labels": [*TRACKED, "wheelchair ramp"],
        "every_seconds": 2.5, "from_seconds": 0, "max_frames": 450, "width": 960,
    },
    ("33-sideseeing-frames-segments-blocks.json", "walk-frames"): {"every_seconds": 2.0, "max_frames_per_video": 450},
    ("33-sideseeing-frames-segments-blocks.json", "frame-segments"): {
        "labels": [
            "curb cut", "curb ramp", "wheelchair ramp", "tactile paving",
            "pole", "bollard", "construction barrier", "traffic cone", "person",
        ],
        "threshold": 0.5, "width": 960, "max_images": 450,
    },
    ("33-sideseeing-frames-segments-blocks.json", "walk-blocks"): {
        "block_seconds": 60.0, "width": 960, "max_frames": 30000,
    },
}


def _manifest(node_type: str) -> dict:
    package_id = node_type.split("/")[0]
    (path,) = [p for p in PACKAGES.glob("*/manifest.json") if p.parent.name.split("@")[0] == package_id]
    return json.loads(path.read_text(encoding="utf-8"))


def _template(node_type: str) -> dict:
    (template,) = [t for t in _manifest(node_type)["templates"] if t["id"] == node_type.split("/")[1]]
    return template


def _source(node_type: str) -> str:
    package_id = node_type.split("/")[0]
    (folder,) = [p for p in PACKAGES.iterdir() if p.name.split("@")[0] == package_id]
    return (folder / _template(node_type)["source"]).read_text(encoding="utf-8")


def _expected_default(node_type: str, default):
    return _manifest(node_type)["model"]["labels"] if default == "model.labels" else default


def _parsed(code: str) -> tuple[list, list]:
    """*code* parsed as the sandbox runs it, inside a function, each chip
    standing as a name: ``(statements, chips)``, where the name
    ``_curio_chip_<k>_`` stands for ``chips[k]``, the text inside the chip."""
    from utk_curio.backend.app.execution.code_references import REFERENCE_RE

    chips: list[str] = []

    def stand_in(match) -> str:
        chips.append(match.group(1))
        return f"_curio_chip_{len(chips) - 1}_"

    text = REFERENCE_RE.sub(stand_in, code)
    tree = ast.parse("def node():\n" + "\n".join("    " + line for line in text.splitlines()))
    return list(tree.body[0].body), chips


def _chip_name(node: ast.AST, chips: list) -> str | None:
    """The widget a chip standing as *node* names, or None for any other node."""
    if isinstance(node, ast.Name) and node.id.startswith("_curio_chip_"):
        return chips[int(node.id.removeprefix("_curio_chip_").removesuffix("_"))]
    return None


def _call(statements: list) -> ast.Call:
    last = statements[-1]
    assert isinstance(last, ast.Return) and isinstance(last.value, ast.Call), ast.dump(last)
    return last.value


def _constants(statements: list) -> dict:
    """The literal settings the code assigns, by name."""
    found = {}
    for statement in statements:
        if (
            isinstance(statement, ast.Assign) and len(statement.targets) == 1
            and isinstance(statement.targets[0], ast.Name)
        ):
            try:
                found[statement.targets[0].id] = ast.literal_eval(statement.value)
            except ValueError:
                continue
    return found


def _how_read(code: str) -> dict:
    """How the one call of *code* reads each setting, by keyword: ``("widget",
    name, cast)`` for a chip, cast or not, ``("constant", name, value)`` for a
    setting the code assigns a literal, else ``("other", text)``."""
    statements, chips = _parsed(code)
    constants = _constants(statements)
    read = {}
    for keyword in _call(statements).keywords:
        value = keyword.value
        cast = None
        if (
            isinstance(value, ast.Call) and isinstance(value.func, ast.Name) and value.func.id in CASTS
            and len(value.args) == 1 and not value.keywords
        ):
            cast, value = value.func.id, value.args[0]
        name = _chip_name(value, chips)
        if name is not None:
            read[keyword.arg] = ("widget", name, cast)
        elif cast is None and isinstance(value, ast.Name) and value.id in constants:
            read[keyword.arg] = ("constant", value.id, constants[value.id])
        else:
            read[keyword.arg] = ("other", ast.unparse(keyword.value))
    return read


def _call_values(code: str) -> dict:
    """What the one call of *code*, its chips written in, gets for each
    keyword: a literal, a cast of one, or a setting the code assigns."""
    statements, _chips = _parsed(code)
    constants = _constants(statements)
    values = {}
    for keyword in _call(statements).keywords:
        value = keyword.value
        if isinstance(value, ast.Call) and isinstance(value.func, ast.Name) and value.func.id in CASTS:
            values[keyword.arg] = CASTS[value.func.id](ast.literal_eval(value.args[0]))
        elif isinstance(value, ast.Name) and value.id in constants:
            values[keyword.arg] = constants[value.id]
        else:
            try:
                values[keyword.arg] = ast.literal_eval(value)
            except ValueError:
                continue
    return values


def _node(file: str, node_id: str) -> dict:
    spec = json.loads((EXAMPLES / file).read_text(encoding="utf-8"))
    nodes = spec.get("dataflow", spec)["nodes"]
    (node,) = [n for n in nodes if n["id"] == node_id]
    return node


@pytest.mark.parametrize("node_type", sorted(SETTINGS))
def test_each_setting_is_a_widget_with_the_default_its_constant_held(node_type):
    """The template has widgets, one per setting its call takes but those
    that may be None, in the call's order, each of its kind with the value
    the setting's constant held as its default."""
    template = _template(node_type)
    expected = [(name, kind, _expected_default(node_type, default)) for name, kind, default, _cast in SETTINGS[node_type]]
    widgets = template.get("widgets") or []
    names = [widget.get("name") for widget in widgets]
    missing = [name for name, _kind, _default in expected if name not in names]
    assert not missing, f"{node_type} has no widget {', '.join(missing)}; its widgets: {names}"
    assert template.get("hasWidgets") is True, f"{node_type} has widgets, so hasWidgets is true"
    assert [(w["name"], w["type"], w.get("default")) for w in widgets] == expected, widgets


@pytest.mark.parametrize("node_type", sorted(SETTINGS))
def test_each_call_reads_its_settings_by_chip(node_type):
    """The template's one call reads each setting by its widget's chip, a
    number cast to its constant's type, and the settings that may be None by
    their constants, which keep the values they had."""
    read = _how_read(_source(node_type))
    expected = {name: ("widget", name, cast) for name, _kind, _default, cast in SETTINGS[node_type]}
    for constant, (keyword, value) in CONSTANTS.get(node_type, {}).items():
        expected[keyword] = ("constant", constant, value)
    wrong = {keyword: read.get(keyword) for keyword in expected if read.get(keyword) != expected[keyword]}
    assert not wrong, f"{node_type}'s call reads {wrong}, not {({k: expected[k] for k in wrong})}"
    assert set(read) == set(expected), (node_type, read)


def test_every_shipped_dataflow_that_holds_one_of_these_nodes_is_known():
    """Each node of the eight in a shipped dataflow, curated or a test one, is
    one whose values this file holds, so none is left with its constants."""
    found = set()
    for path in sorted([*EXAMPLES.glob("*.json"), *(EXAMPLES / "dataflows").glob("*.json")]):
        spec = json.loads(path.read_text(encoding="utf-8"))
        nodes = spec.get("dataflow", spec).get("nodes", []) if isinstance(spec, dict) else []
        found |= {
            (path.relative_to(EXAMPLES).as_posix(), node["id"]) for node in nodes
            if isinstance(node, dict) and node.get("type") in SETTINGS
        }
    assert found == set(EXAMPLE_VALUES), sorted(found ^ set(EXAMPLE_VALUES))


@pytest.mark.parametrize(("file", "node_id"), sorted(EXAMPLE_VALUES), ids=lambda part: part.split(".json")[0][:24])
def test_a_shipped_node_holds_its_templates_widgets_at_the_values_it_used(file, node_id):
    """A shipped node of the eight has its template's widgets, each its
    template's widget whole, default and all, and holds the value its call got
    before: as its ``value`` where that differs from the default, else as the
    default, with no ``value``. Its call is its template's; and resolved as a
    run writes it, the call gets those values, each of its constant's type,
    and the values of the constants it keeps."""
    from utk_curio.backend.app.execution.code_references import effective_value, node_run_code

    node = _node(file, node_id)
    node_type = node["type"]
    values = EXAMPLE_VALUES[(file, node_id)]
    widgets = (node.get("metadata") or {}).get("widgets") or []
    names = [widget.get("name") for widget in widgets]
    missing = [name for name in values if name not in names]
    assert not missing, f"{file}'s {node_id} has no widget {', '.join(missing)}; its widgets: {names}"
    template_widgets = _template(node_type)["widgets"]

    def but_value(widget: dict) -> dict:
        return {key: value for key, value in widget.items() if key != "value"}

    assert [but_value(w) for w in widgets] == template_widgets, widgets
    assert {w["name"]: effective_value(w) for w in widgets} == values, widgets
    assert {w["name"]: "value" in w for w in widgets} == {
        w["name"]: values[w["name"]] != w["default"] for w in template_widgets
    }, widgets
    assert _how_read(node["content"]) == _how_read(_source(node_type)), node["content"]

    got = _call_values(node_run_code(node))
    casts = {name: cast for name, _kind, _default, cast in SETTINGS[node_type]}
    for name, value in values.items():
        assert got[name] == value, (name, got[name], value)
        kind = CASTS[casts[name]] if casts[name] else list
        assert type(got[name]) is kind, (name, got[name])
    for _constant, (keyword, value) in CONSTANTS.get(node_type, {}).items():
        assert got[keyword] == value, (keyword, got[keyword], value)
