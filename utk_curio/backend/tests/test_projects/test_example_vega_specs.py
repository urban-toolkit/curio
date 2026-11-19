"""The shipped Vega-Lite specs say what they draw.

Two mistakes a renderer accepts without a word, so only reading the specs
finds them:

* A ``point`` mark is hollow unless it sets ``filled``, so ``fillOpacity`` on
  it changes nothing. Example 09's scatter faded the points outside its brush
  that way, and every point stayed at full strength (#630).
* A chart coloured by Image Segmentation's classes needs a colour for each
  class its route asks for. Example 10's route 1 asks for ``terrain``, but its
  two charts listed ``car`` instead, so terrain took a recycled colour (#628).

And a spec names the dataset its inputs are stacked in by its chip,
``"data": {"name": "[!! inputs !!]"}``, as every other input is a chip: the
bare name draws the same, so only reading the specs as written finds it.

And a spec's description says what the spec holds. vega.json's and
data-pool-vega.json's bar charts kept Vega-Lite's gallery description, "A
simple bar chart with embedded data.", though their rows come from the loading
node before them. Asked to add two bars to that chart, a Node Builder took the
description's word and wrote the rows into the spec.

And a legend null hides more than its own channel's legend. Vega-Lite draws one
legend for the channels that encode one field, and for one channel across the
views of a layer or a concat, so example 23's map, coloured by ``layer`` under
the title "Layer" and stroked by ``layer`` with ``"legend": null``, drew no
legend at all.

The specs are read from the example dataflows, their walkthroughs, the default
preamble and the skills Curio ships as agents read them, and the worked
examples the builder agents are shown (the base entry's ``examples.md``),
which include example 09's scatter. A
dataflow's chart is a Vega-Lite node, or a node of a shipped template that
draws with the Vega-Lite grammar, as the Vega-Lite package's charts do.
"""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest

from utk_curio.backend.app.agents.application.turns import examples as worked_examples
from utk_curio.backend.app.agents.domain import agent_text, builtin, skills
from utk_curio.backend.app.agents.evaluation.fixtures import EXAMPLES_ROOT, example_paths

VEGA = "curio.builtin/vis-vega"
REPO_ROOT = Path(__file__).resolve().parents[4]
SEGMENTATION = "/image-segmentation"
JSON_BLOCK = re.compile(r"```json[^\n]*\n(.*?)```", re.S)
CLASSES = re.compile(r"^classes\s*=\s*(\[[^\]]*\])", re.M)


def _is_vega_lite(spec) -> bool:
    return isinstance(spec, dict) and "vega-lite" in str(spec.get("$schema", ""))


def _flow_of(doc: dict) -> dict:
    return doc.get("dataflow", doc)


def _flow(path: Path) -> dict:
    return _flow_of(json.loads(path.read_text(encoding="utf-8")))


def _vega_lite_types() -> set:
    """The node types that draw a Vega-Lite spec: every shipped template whose
    grammar is ``vega-lite``, the Vega-Lite node's and the Vega-Lite
    package's charts, read off the manifests."""
    types = {VEGA}
    for path in sorted((REPO_ROOT / "packages").glob("*/manifest.json")):
        manifest = json.loads(path.read_text(encoding="utf-8"))
        for template in manifest.get("templates") or []:
            if template.get("grammarId") == "vega-lite":
                types.add(f"{manifest['id']}/{template['id']}")
    return types


VEGA_LITE_TYPES = _vega_lite_types()


def _node_specs(flow: dict, where: str):
    """Each chart's spec, read as a run reads it: its references resolved, so
    a widget placed as a value, such as a Table's list of columns
    (``"fold": [!! columns !!]``), is JSON once its value is written."""
    from utk_curio.backend.app.execution.workflow_spec import parse_workflow_dict

    spec = parse_workflow_dict({"dataflow": flow})
    by_id = {node.id: node for node in spec.nodes}
    for node in flow.get("nodes", []):
        if node["type"].split("@", 1)[0] in VEGA_LITE_TYPES:
            yield f"{where} node {node['id'][:8]}", json.loads(spec.node_code(by_id[node["id"]], "json"))


def _block_specs(text: str, where: str):
    # A block that is not JSON (an excerpt, a sketch) holds no spec to check.
    for block in JSON_BLOCK.findall(text):
        try:
            spec = json.loads(block)
        except ValueError:
            continue
        if _is_vega_lite(spec):
            yield where, spec


def _shipped_specs():
    """(where, spec) for every Vega-Lite spec Curio ships or shows."""
    for path in example_paths():
        yield from _node_specs(_flow(path), path.name)
    for path in sorted(Path(EXAMPLES_ROOT).glob("*.md")):
        yield from _block_specs(path.read_text(encoding="utf-8"), path.name)
    yield from _block_specs(builtin.read_page(builtin.PREAMBLE_FILE, wanted_by="the Vega-Lite spec test"), "default preamble")
    for skill in skills.shipped_skills():
        yield from _block_specs(agent_text.skill_text(skill.name), f"skill {skill.name}")
    for example in worked_examples.used_examples():
        yield from _node_specs(_flow_of(example.spec), f"worked example {example.key}")


def _units(spec: dict, inherited: dict | None = None):
    """Every unit spec with its encoding; only a layer passes its encoding down."""
    encoding = {**(inherited or {}), **(spec.get("encoding") or {})}
    if "mark" in spec:
        yield spec, encoding
    for child in spec.get("layer") or []:
        yield from _units(child, encoding)
    for key in ("concat", "hconcat", "vconcat"):
        for child in spec.get(key) or []:
            yield from _units(child)
    if isinstance(spec.get("spec"), dict):
        yield from _units(spec["spec"])


def _mark(unit: dict) -> dict:
    mark = unit["mark"]
    return mark if isinstance(mark, dict) else {"type": mark}


def _brushes(spec: dict) -> bool:
    for param in spec.get("params") or []:
        select = param.get("select")
        if select == "interval" or (isinstance(select, dict) and select.get("type") == "interval"):
            return True
    return False


SHIPPED = list(_shipped_specs())


class TestHollowPoints:
    def test_no_hollow_point_fades_through_fill_opacity(self):
        offenders = []
        for where, spec in SHIPPED:
            config = spec.get("config") or {}
            filled_by_default = (config.get("point") or {}).get(
                "filled", (config.get("mark") or {}).get("filled", False)
            )
            for unit, encoding in _units(spec):
                mark = _mark(unit)
                if mark.get("type") != "point" or mark.get("filled", filled_by_default):
                    continue
                if "fillOpacity" in encoding or "fillOpacity" in mark:
                    offenders.append(where)
        assert offenders == [], (
            "a point mark is hollow, so fillOpacity does nothing to it: use opacity "
            f"or set filled. In: {offenders}"
        )

    def test_the_scan_reads_example_09s_scatter_everywhere_it_is_shown(self):
        brushed_points = {
            where.split(" node ")[0]
            for where, spec in SHIPPED
            for unit, _ in _units(spec)
            if _mark(unit).get("type") == "point" and _brushes(spec)
        }
        assert {
            "09-heterogeneous-data-linked-views.json",
            "09-heterogeneous-data-linked-views.md",
            "skill interaction-edges",
            "worked example 09-heterogeneous-data-linked-views",
        } <= brushed_points


EMBEDDED = re.compile(r"\b(embedded|inline) data\b", re.I)


def _holds_rows(spec) -> bool:
    """Whether *spec* holds rows of its own: ``values`` in any ``data`` of
    its views or lookups, or a ``datasets`` entry."""
    if isinstance(spec, list):
        return any(_holds_rows(item) for item in spec)
    if not isinstance(spec, dict):
        return False
    data = spec.get("data")
    if (isinstance(data, dict) and "values" in data) or spec.get("datasets"):
        return True
    return any(_holds_rows(value) for value in spec.values())


class TestADescriptionSaysWhatTheSpecHolds:
    def test_no_spec_says_its_data_is_embedded_when_it_holds_none(self):
        offenders = [where for where, spec in SHIPPED
                     if EMBEDDED.search(str(spec.get("description") or "")) and not _holds_rows(spec)]
        assert offenders == [], (
            "these specs say their data is embedded, but they hold no rows: the chart draws "
            f"the table its input hands it. In: {offenders}"
        )

    def test_the_scan_reads_the_bar_charts_of_vega_and_data_pool_vega(self):
        read = {where.split(" node ")[0] for where, _ in SHIPPED}
        assert {"vega.json", "data-pool-vega.json"} <= read


def _written_specs():
    """(where, text) for every Vega-Lite spec Curio ships, as it is written,
    its chips unresolved: each template of a shipped package that draws with
    the Vega-Lite grammar, and each chart of an example dataflow."""
    for path in sorted((REPO_ROOT / "packages").glob("*/manifest.json")):
        manifest = json.loads(path.read_text(encoding="utf-8"))
        for template in manifest.get("templates") or []:
            if template.get("grammarId") == "vega-lite" and template.get("source"):
                source = path.parent / template["source"]
                yield f"{path.parent.name}/{template['source']}", source.read_text(encoding="utf-8")
    for path in example_paths():
        for node in _flow(path).get("nodes", []):
            if node["type"].split("@", 1)[0] in VEGA_LITE_TYPES and isinstance(node.get("content"), str):
                yield f"{path.name} node {node['id'][:8]}", node["content"]


def _dataset_names(spec) -> list:
    """The name of each dataset *spec*'s views read: a view's own ``data``,
    or a lookup's ``from.data``, in the views ``readsInputs`` walks
    (``utils/vegaDatasets.ts``)."""
    names: list = []

    def visit(node) -> None:
        if isinstance(node, list):
            for item in node:
                visit(item)
            return
        if not isinstance(node, dict):
            return
        sources = [node.get("data")] + [
            step["from"].get("data") for step in node.get("transform") or []
            if isinstance(step, dict) and isinstance(step.get("from"), dict)
        ]
        names.extend(s["name"] for s in sources if isinstance(s, dict) and isinstance(s.get("name"), str))
        for key in ("layer", "concat", "hconcat", "vconcat", "spec"):
            visit(node.get(key))

    visit(spec)
    return names


class TestTheStackedDatasetIsNamedByItsChip:
    def test_no_shipped_spec_names_the_dataset_inputs_bare(self):
        """Read as written, each chip standing on its own held by a string of
        its text (``with_chip_placeholders``): the Vega-Lite package's fifteen charts and their
        copies in the shipped dataflows name the dataset by its chip, and no
        spec names it bare. Every spec reads so, or the scan would pass over
        it."""
        from utk_curio.backend.app.execution.code_references import with_chip_placeholders

        bare, chipped, unread = [], [], []
        for where, text in _written_specs():
            try:
                spec = json.loads(with_chip_placeholders(text))
            except ValueError:
                unread.append(where)
                continue
            names = _dataset_names(spec)
            bare.extend(where for name in names if name == "inputs")
            chipped.extend(where for name in names if name == "[!! inputs !!]")
        assert unread == [], f"these specs do not read as JSON, so their datasets went unchecked: {unread}"
        assert bare == [], f"these specs name the dataset inputs bare, not as [!! inputs !!]: {bare}"
        assert len([where for where in chipped if where.startswith("curio.vega-lite@1/")]) == 15, chipped
        assert len(chipped) >= 34, chipped


def _segmentation_routes():
    """(example, chart id, classes, spec) for each chart under a class list.

    A chart counts when every Image Segmentation node upstream of it names its
    classes in a literal ``classes = [...]``; a node that reports every class
    its model has gives the chart nothing to check against.
    """
    for path in example_paths():
        flow = _flow(path)
        nodes = {n["id"]: n for n in flow.get("nodes", [])}
        parents: dict = {}
        for edge in flow.get("edges", []):
            if edge.get("type") != "Interaction":
                parents.setdefault(edge["target"], set()).add(edge["source"])
        for node in nodes.values():
            if node["type"] != VEGA:
                continue
            seen, stack = set(), list(parents.get(node["id"], ()))
            while stack:
                current = stack.pop()
                if current not in seen:
                    seen.add(current)
                    stack.extend(parents.get(current, ()))
            segmenters = [nodes[i] for i in seen if nodes[i]["type"].endswith(SEGMENTATION)]
            found = [CLASSES.search(n.get("content") or "") for n in segmenters]
            if not segmenters or not all(found):
                continue
            classes = set()
            for match in found:
                classes.update(ast.literal_eval(match.group(1)))
            yield path.name, node["id"], classes, json.loads(node["content"])


ROUTES = list(_segmentation_routes())


class TestSegmentationColours:
    @pytest.mark.parametrize(
        "example,chart,classes,spec", ROUTES, ids=[f"{r[0]}-{r[1][:8]}" for r in ROUTES]
    )
    def test_a_chart_coloured_by_class_names_the_classes_its_route_asks_for(
        self, example, chart, classes, spec
    ):
        domains = [
            encoding[channel]["scale"]["domain"]
            for unit, encoding in _units(spec)
            for channel in ("color", "fill", "stroke")
            if isinstance(((encoding.get(channel) or {}).get("scale") or {}).get("domain"), list)
        ]
        for domain in domains:
            assert set(domain) == classes, (
                f"{example} chart {chart[:8]}: its colour domain {domain} does not name "
                f"the classes its route asks for, {sorted(classes)}"
            )

    def test_example_10s_route_1_charts_are_checked(self):
        checked = {(example, chart[:8]) for example, chart, _, _ in ROUTES}
        assert {
            ("10-street-vision-cv-analysis.json", "8aaff248"),
            ("10-street-vision-cv-analysis.json", "1aa27f1a"),
        } <= checked


#: The channels Vega-Lite draws a legend for.
LEGEND_CHANNELS = ("color", "size", "shape", "fill", "stroke", "strokeDash", "strokeWidth", "opacity")
#: The channels Vega-Lite colours with.
COLOR_CHANNELS = ("color", "fill", "stroke")
#: The channels whose range Vega-Lite only has a list of values for.
DISCRETE_RANGE_CHANNELS = ("shape", "strokeDash")
#: Vega-Lite's kind of each scale type (``SCALE_CATEGORY_INDEX``): the views
#: of a layer or a concat share one scale of a channel only while theirs are
#: of one kind.
SCALE_KINDS = {
    "linear": "numeric", "log": "numeric", "pow": "numeric", "sqrt": "numeric", "symlog": "numeric",
    "identity": "numeric", "sequential": "numeric", "time": "time", "utc": "time", "ordinal": "ordinal",
    "bin-ordinal": "bin-ordinal", "point": "ordinal-position", "band": "ordinal-position",
    "quantile": "discretizing", "quantize": "discretizing", "threshold": "discretizing",
}
#: The scale types with a discrete domain: the legends of two channels on one
#: field merge only when both scales have one, or neither.
DISCRETE_SCALES = ("ordinal", "point", "band", "bin-ordinal")


def _legend_field(definition):
    """The field definition a channel's legend comes from: the channel's own,
    or the one its condition holds; none for a value, a datum or a geometry."""
    if isinstance(definition, dict) and not isinstance(definition.get("field"), str):
        definition = definition.get("condition")
    if not isinstance(definition, dict) or not isinstance(definition.get("field"), str):
        return None
    return None if definition.get("type") == "geojson" else definition


def _scale_type(channel: str, definition: dict) -> str:
    """The scale type Vega-Lite gives *definition* on *channel*: the one its
    scale names, else the default for its field's type (``defaultType``)."""
    scale = definition.get("scale")
    if isinstance(scale, dict) and isinstance(scale.get("type"), str):
        return scale["type"]
    if definition.get("type") in ("nominal", "ordinal"):
        return "ordinal" if channel in COLOR_CHANNELS + DISCRETE_RANGE_CHANNELS else "point"
    if channel in DISCRETE_RANGE_CHANNELS:
        return "ordinal"
    if definition.get("type") == "temporal":
        return "time"
    return "bin-ordinal" if definition.get("bin") and channel in COLOR_CHANNELS else "linear"


def _views(spec: dict, encoding: dict) -> list:
    """(kind, view, the encoding it is handed) for each view *spec* holds: a
    layer hands its encoding down, a concat and a facet's or a repeat's spec
    do not."""
    views = [("layer", child, encoding) for child in spec.get("layer") or []]
    for key in ("concat", "hconcat", "vconcat"):
        views += [(key, child, None) for child in spec.get(key) or []]
    if isinstance(spec.get("spec"), dict):
        views.append(("spec", spec["spec"], None))
    return views


def _legend_channels(spec: dict, inherited: dict | None = None, scopes: dict | None = None, path: tuple = ()):
    """(scope, channel, field definition) for each legend channel of each view
    of *spec*.

    The views of a layer or a concat share one scale and one legend of a
    channel, unless its ``resolve`` makes the channel independent, or the
    views ask for scales of different kinds (a nominal colour beside a
    quantitative one, as example 04's map and bars do): then each view keeps
    its own, and *scopes* names, per channel, the view it is kept in."""
    scopes = scopes or {}
    encoding = {**(inherited or {}), **(spec.get("encoding") or {})}
    if "mark" in spec:
        for channel in LEGEND_CHANNELS:
            definition = _legend_field(encoding.get(channel))
            if definition is not None:
                yield scopes.get(channel, ()), channel, definition
    views = _views(spec, encoding)
    kinds: dict = {}
    for _, child, handed in views:
        for _, channel, definition in _legend_channels(child, handed):
            kinds.setdefault(channel, set()).add(SCALE_KINDS.get(_scale_type(channel, definition)))
    independent = {channel for channel, seen in kinds.items() if len(seen) > 1}
    resolve = spec.get("resolve") or {}
    independent |= {channel for part in ("scale", "legend") for channel, mode in (resolve.get(part) or {}).items()
                    if mode == "independent"}
    for index, (key, child, handed) in enumerate(views):
        view = path + ((key, index),)
        yield from _legend_channels(child, handed, {**scopes, **dict.fromkeys(independent, view)}, view)


def _legends_hidden_by_a_null(spec: dict) -> list:
    """Each legend of *spec* that a ``"legend": null`` hides though another
    channel of it shows one, as (the channels that hide it, those that show it).

    Vega-Lite draws one legend for the channels that share a scale (one
    channel across the views that share it) or a field (color and stroke on
    the same field, both scales with a discrete domain or neither; a channel
    shared by views that encode different fields has no one field), and a null
    on any of them hides that legend for all of them, or conflicts with a
    legend another names."""
    channels = list(_legend_channels(spec))
    legend_of = list(range(len(channels)))
    fields: dict = {}
    for scope, channel, definition in channels:
        fields.setdefault((scope, channel), set()).add(definition["field"])

    def legend(index: int) -> int:
        while legend_of[index] != index:
            index = legend_of[index]
        return index

    def field_of(scope: tuple, channel: str, definition: dict):
        """The one field of the channel's legend, and whether its scale's
        domain is discrete; none when its views encode different fields."""
        if len(fields[(scope, channel)]) > 1:
            return None
        return definition["field"], _scale_type(channel, definition) in DISCRETE_SCALES

    for i, (scope, channel, definition) in enumerate(channels):
        for j, (other_scope, other_channel, other) in enumerate(channels[:i]):
            field = field_of(scope, channel, definition)
            same_field = field is not None and field == field_of(other_scope, other_channel, other)
            if scope == other_scope and (channel == other_channel or same_field):
                legend_of[legend(i)] = legend(j)
    legends: dict = {}
    for i, (_, channel, definition) in enumerate(channels):
        hides = "legend" in definition and definition["legend"] is None
        legends.setdefault(legend(i), ([], []))[0 if hides else 1].append(f"{channel} ({definition['field']})")
    return [(hiding, showing) for hiding, showing in legends.values() if hiding and showing]


def _circles(encoding: dict) -> dict:
    return {"mark": "circle", "encoding": encoding}


_K = {"field": "k", "type": "nominal"}
_HIDDEN = {"legend": None}

#: Specs whose legends Vega-Lite 6.5 was seen to draw or hide (each compiled
#: and drawn to SVG), with whether a legend null hides a legend another
#: channel shows, as the scan must call it.
LEGEND_CASES = {
    "color and stroke on one field, the stroke's legend null, as example 23's map had them": (
        _circles({"color": {**_K, "title": "K"}, "stroke": {**_K, **_HIDDEN}}), True),
    "color and stroke on one field, no legend null": (
        _circles({"color": {**_K, "title": "K"}, "stroke": _K}), False),
    "color and stroke on two fields, the stroke's legend null": (
        _circles({"color": {**_K, "title": "K"}, "stroke": {"field": "j", "type": "nominal", **_HIDDEN}}), False),
    "a discrete color and a continuous size on one field, the size's legend null": (
        _circles({"color": {"field": "n", "type": "nominal"},
                  "size": {"field": "n", "type": "quantitative", **_HIDDEN}}), False),
    "color and stroke on one field, both legends null": (
        _circles({"color": {**_K, **_HIDDEN}, "stroke": {**_K, **_HIDDEN}}), False),
    "a legend named on color, the stroke's null on the same field (Vega-Lite warns of the conflict)": (
        _circles({"color": {**_K, "legend": {"orient": "bottom"}}, "stroke": {**_K, **_HIDDEN}}), True),
    "a legend null in color's condition, stroke on the same field": (
        {"params": [{"name": "p", "select": "point"}],
         **_circles({"color": {"condition": {"param": "p", **_K, **_HIDDEN}, "value": "grey"}, "stroke": _K})}, True),
    "color in one layer, the stroke's legend null on the same field in another": (
        {"layer": [_circles({"color": _K}), {"mark": "text", "encoding": {"stroke": {**_K, **_HIDDEN}}}]}, True),
    "color in one layer, color's legend null in another": (
        {"layer": [_circles({"color": _K}), {"mark": "text", "encoding": {"color": {**_K, **_HIDDEN}}}]}, True),
    "color in one view of a concat, the stroke's legend null on the same field in the other": (
        {"hconcat": [_circles({"color": _K}), _circles({"stroke": {**_K, **_HIDDEN}})]}, True),
    "the same, with each view's legends its own": (
        {"resolve": {"legend": {"color": "independent", "stroke": "independent"}},
         "hconcat": [_circles({"color": _K}), _circles({"stroke": {**_K, **_HIDDEN}})]}, False),
    "the same, with color on another field in the other view too": (
        {"hconcat": [_circles({"color": _K}),
                     _circles({"color": {"field": "j", "type": "nominal"}, "stroke": {**_K, **_HIDDEN}})]}, False),
    "a nominal color and a size in one view, a quantitative color's legend null on the size's field "
    "in the other, as example 04's map and bars have them": (
        {"hconcat": [_circles({"color": _K, "size": {"field": "n", "type": "quantitative"}}),
                     _circles({"color": {"field": "n", "type": "quantitative", **_HIDDEN}})]}, False),
}


class TestALegendNullHidesNoLegendAnotherChannelShows:
    def test_no_legend_null_hides_a_legend_another_channel_shows(self):
        """Every spec Curio ships or shows, and every chart template of a
        shipped package as written, each chip held by a string of its text."""
        from utk_curio.backend.app.execution.code_references import with_chip_placeholders

        specs = list(SHIPPED)
        for where, text in _written_specs():
            try:
                specs.append((where, json.loads(with_chip_placeholders(text))))
            except ValueError:
                continue  # test_no_shipped_spec_names_the_dataset_inputs_bare names it
        offenders = sorted({
            f"{where}: {', '.join(hiding)} hides the legend that {', '.join(showing)} shows"
            for where, spec in specs for hiding, showing in _legends_hidden_by_a_null(spec)
        })
        assert offenders == [], (
            "Vega-Lite draws one legend for the channels that encode one field, so a legend null on "
            "one of them hides it for all of them: take the null out, and the one legend stands for "
            f"them all. In: {offenders}"
        )

    @pytest.mark.parametrize("case", list(LEGEND_CASES))
    def test_the_scan_calls_each_case_as_vega_lite_draws_it(self, case):
        spec, hidden = LEGEND_CASES[case]
        assert bool(_legends_hidden_by_a_null(spec)) is hidden, _legends_hidden_by_a_null(spec)

    def test_the_scan_reads_example_23s_map_everywhere_it_is_shown(self):
        layered = {
            where.split(" node ")[0]
            for where, spec in SHIPPED
            if {(channel, definition["field"]) for _, channel, definition in _legend_channels(spec)}
            >= {("color", "layer"), ("stroke", "layer")}
        }
        assert {
            "23-storage-folder-of-different-files.json",
            "23-storage-folder-of-different-files.md",
            "worked example 23-storage-folder-of-different-files",
        } <= layered
