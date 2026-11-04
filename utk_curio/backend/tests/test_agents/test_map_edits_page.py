"""The skill on Map Editor, ``skills/map-edits/SKILL.md``, states the call,
the edits and their fields as the node's reader takes them, and the words a
goal names edits by, and every run that writes or checks a Map Editor node's
code holds it.

The skill's body is read as agents read it, by fixed line shapes, and
compared with the reader's tables
(``utk_curio/sandbox/util/feature_edits_code.py``) and the goal rule's words
(``agents/domain/map_edits.py``), so neither can drift from the skill.
"""
from __future__ import annotations

import re

SKILL = "map-edits"
_HEADER = "| op | fields |"
_RULE = "|---|---|"
_ROW = re.compile(r"\| (?P<op>[a-z_]+) \| (?P<fields>[a-z_]+(?:(?:, | or )[a-z_]+)*) \|")
_WORDS_LINE = re.compile(
    r"- Solve makes edits in an empty .+ node only when its goal names edits; .+ "
    r"starts with one of these words: (?P<words>[a-z ,]+)\."
)
_CALL_BLOCK = re.compile(r"^```python\n(.*?)^```$", re.MULTILINE | re.DOTALL)


def _page() -> str:
    """The skill's body as agents read it."""
    from utk_curio.backend.app.agents.domain import agent_text

    return agent_text.skill_text(SKILL)


def _table_rows(text: str) -> dict[str, list[str]]:
    lines = text.splitlines()
    start = lines.index(_HEADER)
    assert lines[start + 1] == _RULE, lines[start + 1]
    rows: dict[str, list[str]] = {}
    for line in lines[start + 2:]:
        if not line.startswith("|"):
            break
        match = _ROW.fullmatch(line)
        assert match, f"a row of the table of edits is not '| op | fields |': {line!r}"
        rows[match["op"]] = re.split(r", | or ", match["fields"])
    return rows


def test_every_run_that_writes_or_checks_a_map_editor_node_holds_the_page_whole(tmp_curio):
    """A run that writes a Map Editor node's code, or checks it, is handed the
    page whole, once; a chat that lists it loads it whole; the preamble every
    agent reads leaves it out."""
    from utk_curio.backend.app.agents.application import skill_runs
    from utk_curio.backend.app.agents.domain import builtin, contracts

    page = _page().rstrip("\n")
    label = contracts.render_template("{{template.label:curio.builtin/edit-features}}")
    assert page.splitlines()[0] == f"## {label}"
    manifests = builtin.list_builtin_manifests()
    assert len(manifests) >= 7, [m.dir_name for m in manifests]
    edit = "curio.builtin/edit-features"
    inputs = {"nodeType": edit, "nodeContext": {"nodeType": edit}}
    handed = []
    for m in manifests:
        system = builtin.read_prompt_text(m.dir_name, "system")
        assert page not in system, m.dir_name
        for capability in ("node.content.generate", "content.quality.evaluate"):
            if capability in m.capability_ids:
                run = skill_runs.for_delegated("4242", "p-map-edits", m, capability, inputs,
                                               {"dataflow": {"nodes": []}}, system)
                assert (skill_runs.skills_text(run) or "").count(page) == 1, (m.dir_name, capability)
                handed.append(capability)
        if SKILL in (m.skills or ()) and m.catalog.listed:
            chat = skill_runs.for_chat("4242", "p-map-edits", m, {"dataflow": {"nodes": []}}, {"kind": "canvas"},
                                       system, [])
            status, loaded = skill_runs.read(chat, {"name": SKILL})
            assert status == "ok" and loaded.count(page) == 1, m.dir_name
    assert sorted(handed) == ["content.quality.evaluate", "node.content.generate"]


def test_the_page_lists_every_edit_with_the_fields_the_reader_takes():
    from utk_curio.sandbox.util.feature_edits_code import COMMON_FIELDS, EDIT_FIELDS, EDIT_OPS

    text = _page()
    rows = _table_rows(text)
    assert list(rows) == list(EDIT_OPS)
    assert {op: sorted(fields) for op, fields in rows.items()} == {
        op: sorted(fields) for op, fields in EDIT_FIELDS.items()
    }
    assert [field for field in COMMON_FIELDS if field != "op" and f"`{field}`" not in text] == []


def test_the_page_names_the_calls_keywords():
    from utk_curio.sandbox.util.feature_edits_code import KEYWORDS

    text = _page()
    assert [keyword for keyword in KEYWORDS if f"`{keyword}`" not in text] == []


def test_the_pages_call_is_code_the_node_reads():
    from utk_curio.sandbox.util.feature_edits_code import read_edit_features_code

    [code] = _CALL_BLOCK.findall(_page())
    read = read_edit_features_code(code)
    assert "problem" not in read, read
    assert read["circles"] == 1
    assert read["settings"]["key"] == "building_id"
    assert [edit["op"] for edit in read["settings"]["edits"]] == ["remove", "set"]


def test_the_page_names_the_words_a_goal_names_edits_by():
    from utk_curio.backend.app.agents.domain.map_edits import EDIT_WORDS

    [line] = [line for line in _page().splitlines() if _WORDS_LINE.fullmatch(line)]
    assert tuple(_WORDS_LINE.fullmatch(line)["words"].split(", ")) == EDIT_WORDS
