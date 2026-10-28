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
# A change between two Trills, made on a doc
# ---------------------------------------------------------------------------

def _normalized(dataflow: dict) -> dict:
    return _round_trip(dataflow)[1]


@pytest.mark.parametrize(
    "first", range(len(SHIPPED)) if len(SHIPPED) >= AT_LEAST_SHIPPED else [None],
    ids=lambda first: (
        f"{SHIPPED[first].key}->{SHIPPED[(first + 1) % len(SHIPPED)].key}" if first is not None else "too-few-shipped"
    ),
)
def test_a_doc_of_each_shipped_dataflow_changes_into_the_next(first):
    """What a writer outside the doc changed, as one transaction: a doc made
    from one shipped dataflow, changed to the next, reads as the next, in its
    order; a change to what the doc holds writes nothing."""
    from utk_curio.backend.app.collaboration import doc_mapping

    assert first is not None, f"Curio ships {len(SHIPPED)} dataflows, fewer than {AT_LEAST_SHIPPED}"
    shipped, then = SHIPPED[first], SHIPPED[(first + 1) % len(SHIPPED)]
    before = json.loads(shipped.path.read_text(encoding="utf-8"))["dataflow"]
    after = json.loads(then.path.read_text(encoding="utf-8"))["dataflow"]
    doc, _back = _round_trip(before)
    written = []
    doc.observe(lambda event: written.append(event.update))

    assert doc_mapping.apply_dataflow(doc, before, after) == []
    got = doc_mapping.doc_to_dataflow(doc)
    assert _text(got) == _text(_normalized(doc_mapping.owned(after)))
    assert [node["id"] for node in got["nodes"]] == [node["id"] for node in after["nodes"]]
    assert [edge["id"] for edge in got["edges"]] == [edge["id"] for edge in after["edges"]]
    count = len(written)
    doc_mapping.apply_dataflow(doc, after, after)
    assert len(written) == count, "a change to what the doc holds already wrote something"


def test_a_change_keeps_what_the_doc_changed_meanwhile():
    """Three ways: what the change changed lands, what the doc changed since
    stays, and a node's code both changed keeps the doc's, named as refused."""
    from pycrdt import Map

    from utk_curio.backend.app.collaboration import doc_mapping

    base = {"nodes": [
        {"id": "a", "type": "t", "x": 0, "y": 0, "content": "a = 1\n",
         "metadata": {"widgets": [{"name": "w", "type": "number", "default": 1, "value": 1}]}},
        {"id": "b", "type": "t", "x": 9, "y": 9, "content": "b = 1\n"},
    ], "edges": [], "name": "base", "task": "base task"}
    doc, _back = _round_trip(base)
    with doc.transaction():
        nodes = doc.get("nodes", type=Map)
        nodes["a"]["content"].insert(0, "# doc\n")
        nodes["a"]["widgets"]["w"]["value"] = doc_mapping.encode(2)
        doc.get("dataflow", type=Map)["task"] = doc_mapping.encode("the doc's task")
    target = json.loads(json.dumps(base))
    target["name"] = "theirs"
    target["nodes"][0]["x"] = 5
    target["nodes"][0]["content"] = "a = 2\n"
    target["nodes"][0]["metadata"]["widgets"][0]["default"] = 3
    target["nodes"][1]["content"] = "b = 2\n"

    assert doc_mapping.apply_dataflow(doc, base, target) == ["a"]
    got = doc_mapping.doc_to_dataflow(doc)
    assert got["name"] == "theirs" and got["task"] == "the doc's task"
    first, second = got["nodes"]
    assert first["content"] == "# doc\na = 1\n", "the change overwrote the code the doc changed"
    assert first["x"] == 5 and second["content"] == "b = 2\n"
    assert first["metadata"]["widgets"] == [{"name": "w", "type": "number", "default": 3, "value": 2}]


def test_a_code_change_rewrites_only_what_differs_so_typing_meanwhile_stays():
    """The change replaces the stretch the two codes differ in, counted in the
    UTF-8 bytes pycrdt counts places in, so a tab's typing elsewhere in the
    same code, merged after, stays where it was typed."""
    from pycrdt import Doc, Map

    from utk_curio.backend.app.collaboration import doc_mapping

    base = {"nodes": [{"id": "n", "type": "t", "content": "héllo wörld 😀\n"}], "edges": []}
    server, _back = _round_trip(base)
    tab = Doc()
    tab.apply_update(server.get_update())
    content = tab.get("nodes", type=Map)["n"]["content"]
    content += "# tab\n"
    typed = tab.get_update(server.get_state())
    target = {"nodes": [{"id": "n", "type": "t", "content": "HÉLLO wörld 😀\n"}], "edges": []}

    doc_mapping.apply_dataflow(server, base, target)
    server.apply_update(typed)
    assert doc_mapping.doc_to_dataflow(server)["nodes"][0]["content"] == "HÉLLO wörld 😀\n# tab\n"


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
