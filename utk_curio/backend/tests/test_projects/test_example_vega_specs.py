"""The shipped Vega-Lite specs say what they draw.

Two mistakes a renderer accepts without a word, so only reading the specs
finds them:

* A ``point`` mark is hollow unless it sets ``filled``, so ``fillOpacity`` on
  it changes nothing. Example 09's scatter faded the points outside its brush
  that way, and every point stayed at full strength (#630).
* A chart coloured by Image Segmentation's classes needs a colour for each
  class its route asks for. Example 10's route 1 asks for ``terrain``, but its
  two charts listed ``car`` instead, so terrain took a recycled colour (#628).

The specs are read from the example dataflows, their walkthroughs, the default
preamble, and the worked examples the builder agents are shown
(``llm-prompts/examples.md``), which include example 09's scatter.
"""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest

from utk_curio.backend.app.agents.application.turns import examples as worked_examples
from utk_curio.backend.app.agents.domain import contracts
from utk_curio.backend.app.agents.evaluation.fixtures import EXAMPLES_ROOT, example_paths

VEGA = "curio.builtin/vis-vega"
SEGMENTATION = "/image-segmentation"
JSON_BLOCK = re.compile(r"```json[^\n]*\n(.*?)```", re.S)
CLASSES = re.compile(r"^classes\s*=\s*(\[[^\]]*\])", re.M)


def _is_vega_lite(spec) -> bool:
    return isinstance(spec, dict) and "vega-lite" in str(spec.get("$schema", ""))


def _flow_of(doc: dict) -> dict:
    return doc.get("dataflow", doc)


def _flow(path: Path) -> dict:
    return _flow_of(json.loads(path.read_text(encoding="utf-8")))


def _node_specs(flow: dict, where: str):
    for node in flow.get("nodes", []):
        if node["type"] == VEGA:
            yield f"{where} node {node['id'][:8]}", json.loads(node["content"])


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
    yield from _block_specs(contracts.render_default_preamble(), "default preamble")
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
            "default preamble",
            "worked example 09-heterogeneous-data-linked-views",
        } <= brushed_points


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
