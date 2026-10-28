"""A dataflow's Trill and its Yjs doc, each made from the other
(``collaboration/doc_mapping.py``).

Every dataflow Curio ships goes to a doc and comes back as itself: directly,
through a sync to a tab, and through the bytes a restart reloads. Each field
``TrillGenerator.generateTrill`` writes has its row in the layout the canvas
shares (``src/contracts/dataflowDoc.json``), and each row is a field it
writes. pycrdt and the mapping are imported inside each test, so a checkout
without them fails these one by one.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from utk_curio.backend.app.projects.shipped import shipped_dataflows

REPO = Path(__file__).resolve().parents[4]
FRONTEND = REPO / "utk_curio" / "frontend" / "urban-workflows" / "src"
SHIPPED = shipped_dataflows()
#: Fewer than these would mean the shipped dataflows were read wrong: the round
#: trip then runs once, to fail on that, rather than pass on what it found.
AT_LEAST_SHIPPED = 50


def _text(value) -> str:
    """*value* as text that tells ``5`` from ``5.0`` but not key orders apart."""
    return json.dumps(value, sort_keys=True)


def _same_leaves(original: dict, back: dict) -> None:
    """Each value the doc holds whole comes back as written, its keys in
    their order and its numbers in their form."""
    for name, value in original.items():
        if name not in ("nodes", "edges", "scenarios"):
            assert json.dumps(back[name]) == json.dumps(value), name
    by_id = {node["id"]: node for node in back["nodes"]}
    for node in original.get("nodes", []):
        mine = by_id[node["id"]]
        for name, value in node.items():
            if name != "metadata":
                assert json.dumps(mine[name]) == json.dumps(value), (node["id"], name)
        for name, value in (node.get("metadata") or {}).items():
            if name == "widgets":
                for widget, kept in zip(value, mine["metadata"]["widgets"]):
                    for field, part in widget.items():
                        assert json.dumps(kept[field]) == json.dumps(part), (node["id"], widget["name"], field)
            else:
                assert json.dumps(mine["metadata"][name]) == json.dumps(value), (node["id"], name)
    for edge, kept in zip(original.get("edges", []), back["edges"]):
        assert json.dumps(kept) == json.dumps(edge), edge["id"]
    for scenario, kept in zip(original.get("scenarios", []), back.get("scenarios", [])):
        for field, value in scenario.items():
            assert json.dumps(kept[field]) == json.dumps(value), (scenario["id"], field)


def _round_trip(dataflow: dict):
    from utk_curio.backend.app.collaboration import doc_mapping

    doc = doc_mapping.new_doc()
    doc_mapping.dataflow_to_doc(dataflow, doc, doc_id="test")
    return doc, doc_mapping.doc_to_dataflow(doc)


@pytest.mark.parametrize(
    "shipped", SHIPPED if len(SHIPPED) >= AT_LEAST_SHIPPED else [None],
    ids=lambda shipped: shipped.key if shipped is not None else "too-few-shipped",
)
def test_every_shipped_dataflow_round_trips(shipped):
    from pycrdt import Doc, create_sync_message, handle_sync_message

    from utk_curio.backend.app.collaboration import doc_mapping

    assert shipped is not None, (
        f"Curio ships {len(SHIPPED)} dataflows, fewer than {AT_LEAST_SHIPPED}: "
        f"{[found.key for found in SHIPPED]}"
    )
    dataflow = json.loads(shipped.path.read_text(encoding="utf-8"))["dataflow"]
    doc, back = _round_trip(dataflow)
    assert _text(back) == _text(doc_mapping.owned(dataflow))
    _same_leaves(doc_mapping.owned(dataflow), back)
    assert back["nodes"] and [node["id"] for node in back["nodes"]] == [node["id"] for node in dataflow["nodes"]]
    assert [edge["id"] for edge in back["edges"]] == [edge["id"] for edge in dataflow["edges"]]

    # A tab that syncs gets the same Trill, to the byte, and so does a doc
    # reloaded from the bytes a restart reads.
    tab = Doc()
    reply = handle_sync_message(create_sync_message(tab)[1:], doc)
    handle_sync_message(reply[1:], tab)
    assert json.dumps(doc_mapping.doc_to_dataflow(tab)) == json.dumps(back)
    reloaded = doc_mapping.new_doc()
    reloaded.apply_update(doc.get_update())
    assert json.dumps(doc_mapping.doc_to_dataflow(reloaded)) == json.dumps(back)
    assert doc_mapping.doc_id(reloaded) == "test"


# ---------------------------------------------------------------------------
# Every field generateTrill writes, against the layout
# ---------------------------------------------------------------------------

def _assigned(source: str, target: str) -> list[str]:
    """The fields ``<target>.<field> = ...`` sets in *source*."""
    return re.findall(r"\b" + re.escape(target) + r"\.(\w+)\s*=(?![=>])", source)


def _literal(source: str, start: str) -> list[str]:
    """The fields of the object literal that comes after *start* in *source*."""
    i = source.index("{", source.index(start) + len(start))
    depth, items, item = 0, [], ""
    for char in source[i:]:
        if char in "([{":
            depth += 1
            if depth == 1:
                continue
        elif char in ")]}":
            depth -= 1
            if depth == 0:
                items.append(item)
                break
        if depth == 1 and char == ",":
            items.append(item)
            item = ""
        else:
            item += char
    return [re.match(r"\s*(\w+)", part).group(1) for part in items if part.strip()]


def _function(source: str, start: str) -> str:
    """*source* from *start* to the next function it exports."""
    i = source.index(start)
    end = source.find("\nexport ", i + len(start))
    return source[i:] if end < 0 else source[i:end]


def _written_by_generate_trill() -> dict[str, list[str]]:
    generator = (FRONTEND / "TrillGenerator.ts").read_text(encoding="utf-8")
    body = generator[generator.index("static generateTrill("):]
    scenarios = _function(
        (FRONTEND / "utils" / "scenarios" / "scenarioModel.ts").read_text(encoding="utf-8"),
        "export function normalizeScenarios",
    )
    widgets = _function(
        (FRONTEND / "utils" / "widgets" / "widgetModel.ts").read_text(encoding="utf-8"),
        "export function normalizeWidgets",
    )
    return {
        "dataflow": _literal(body, "dataflow:") + _assigned(body, "trill.dataflow"),
        "node": _assigned(body, "trill_node"),
        "metadata": _assigned(body, "trill_node.metadata"),
        "edge": _assigned(body, "trill_edge"),
        "scenario": _literal(scenarios, "const scenario: Scenario =") + _assigned(scenarios, "scenario"),
        "widget": _literal(widgets, "const def: WidgetDef =") + _assigned(widgets, "def"),
    }


#: Fewer than these would mean the reading of the sources broke, not the layout.
_AT_LEAST = {"dataflow": 12, "node": 19, "metadata": 14, "edge": 7, "scenario": 8, "widget": 6}


def test_every_field_generate_trill_writes_has_its_place_in_the_doc():
    """The layout the mapping reads (``src/contracts/dataflowDoc.json``), against
    the TypeScript that writes Trill."""
    from utk_curio.backend.app.collaboration import doc_mapping

    layout = doc_mapping.LAYOUT
    written = _written_by_generate_trill()
    for level, fields in written.items():
        assert len(set(fields)) >= _AT_LEAST[level], (level, fields)
        missing = sorted(set(fields) - set(layout[level]))
        assert not missing, f"generateTrill writes {level} fields the doc has no place for: {missing}"
        unwritten = sorted(set(layout[level]) - set(fields))
        assert not unwritten, f"the layout names {level} fields generateTrill does not write: {unwritten}"
    edge_metadata = _assigned(
        (FRONTEND / "TrillGenerator.ts").read_text(encoding="utf-8"), "trill_edge.metadata"
    )
    assert edge_metadata and layout["edge"]["metadata"] == "@whole", (
        "an edge's metadata travels inside the edge's one value"
    )


def test_each_place_in_the_layout_reads():
    """Each row's place is one the mapping knows: a key of its own, a member
    of a grouped value, or one of the doc's structures."""
    from utk_curio.backend.app.collaboration import doc_mapping

    layout = doc_mapping.LAYOUT
    structures = {"@key", "@text", "@metadata", "@widgets", "@nodes", "@edges", "@scenarios", "@whole"}
    for level in ("dataflow", "node", "metadata", "widget", "edge", "scenario"):
        for field, place in layout[level].items():
            assert place in structures or re.fullmatch(r"\w+(\.\w+)?", place), (level, field, place)
    assert set(layout["roots"]) == {"meta", "dataflow", "nodes", "nodeOrder", "edges", "edgeOrder",
                                    "scenarios", "scenarioOrder"}


# ---------------------------------------------------------------------------
# The rules the shipped dataflows do not all exercise
# ---------------------------------------------------------------------------

def test_absent_and_empty_stay_apart():
    cases = [
        {"nodes": [], "edges": [], "name": "listed", "scenarios": []},
        {"nodes": [], "edges": [], "name": "unlisted"},
        {"nodes": [], "edges": [], "name": "no packages yet", "packages": []},
        {"nodes": [
            {"id": "empty", "type": "t", "content": ""},
            {"id": "none", "type": "t"},
            {"id": "wide", "type": "t", "width": 400},
            {"id": "placed", "type": "t", "dashboardX": 1, "dashboardY": 2},
            {"id": "pinned", "type": "t", "dashboardPinned": False},
            {"id": "w", "type": "t", "metadata": {"widgets": [
                {"name": "unset", "type": "number", "default": 1},
                {"name": "cleared", "type": "number", "default": 1, "value": None},
            ]}},
        ], "edges": [], "name": "fields"},
    ]
    for dataflow in cases:
        _doc, back = _round_trip(dataflow)
        assert _text(back) == _text(dataflow), dataflow["name"]

    # An empty metadata, or empty widgets, is written as none: generateTrill
    # writes neither.
    _doc, back = _round_trip({"nodes": [
        {"id": "a", "type": "t", "metadata": {}},
        {"id": "b", "type": "t", "metadata": {"widgets": []}},
    ], "edges": []})
    assert back["nodes"] == [{"id": "a", "type": "t"}, {"id": "b", "type": "t"}]


def test_numbers_and_key_orders_keep_the_form_they_were_written_in():
    dataflow = {
        # In the order generateTrill writes, so the whole text compares.
        "nodes": [{"id": "n", "type": "t", "x": 1.5, "y": 2, "metadata": {
            "spatialJoin": {"predicate": "within", "output": "counts"},
            "widgets": [
                {"name": "w", "type": "slider", "default": 5.0, "options": {"step": 0.5, "min": 0}, "value": 5},
            ],
        }}],
        "edges": [],
        "name": "forms",
        "categories": {"Topic": "Heat", "City": "Chicago", "Complexity": "Basic"},
        "datasets": [{"title": "z first", "datasetId": "a"}],
    }
    _doc, back = _round_trip(dataflow)
    assert json.dumps(back) == json.dumps(dataflow)


def test_a_list_that_cannot_be_keyed_is_kept_whole():
    from pycrdt import Map

    dataflow = {
        "nodes": [{"id": "n", "type": "t", "metadata": {"widgets": [
            {"name": "twice", "type": "number", "default": 1},
            {"name": "twice", "type": "number", "default": 2},
        ]}}],
        "edges": [{"id": "e", "source": "a", "target": "b"}, {"id": "e", "source": "b", "target": "c"}],
        "name": "unkeyed",
        "scenarios": [{"name": "no id", "color": "#000", "nodes": []}],
    }
    doc, back = _round_trip(dataflow)
    assert _text(back) == _text(dataflow)
    assert isinstance(doc.get("dataflow", type=Map)["edges"], str), "the edges were not kept whole"
    assert isinstance(doc.get("dataflow", type=Map)["scenarios"], str)


def test_the_agents_sections_stay_outside_the_doc():
    from pycrdt import Map

    from utk_curio.backend.app.collaboration import doc_mapping

    dataflow = {"nodes": [], "edges": [], "name": "with agents",
                "agents": [{"agentId": "a"}], "agentAttachments": [{"attachmentId": "x"}],
                "agentDefaults": {"model": "m"}}
    doc, back = _round_trip(dataflow)
    assert back == {"nodes": [], "edges": [], "name": "with agents"}
    assert not set(doc.get("dataflow", type=Map).keys()) & doc_mapping.OUTSIDE_THE_DOC


def test_a_node_field_named_like_a_doc_key_is_refused():
    from utk_curio.backend.app.collaboration import doc_mapping

    with pytest.raises(doc_mapping.DocMappingError, match="place"):
        _round_trip({"nodes": [{"id": "n", "type": "t", "place": "here"}], "edges": []})


def test_a_value_left_without_its_json_text_is_read_as_written():
    """A writer that skips the JSON text (none should) does not stop a read."""
    from pycrdt import Map

    from utk_curio.backend.app.collaboration import doc_mapping

    doc, _back = _round_trip({"nodes": [{"id": "n", "type": "t", "goal": "g"}], "edges": [], "name": "x"})
    node = doc.get("nodes", type=Map)["n"]
    node["goal"] = 3.0      # a number pycrdt holds as it does every number
    node["title"] = "not { json"
    back = doc_mapping.doc_to_dataflow(doc)["nodes"][0]
    assert back["goal"] == 3 and isinstance(back["goal"], int)
    assert back["title"] == "not { json"
