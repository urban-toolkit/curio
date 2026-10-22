"""The prose a run's turns are composed from is the base entry's, not Python's.

What a run is told of each tool, how it replies (the suggested prompts, the
tool and delegate requests, the dataset candidates block), the lines that
frame what it is given (the canvas context, a delegated task, the
configuration, the worked examples, the template rosters), the reply contracts
a delegated run receives, the title call's prompt and the keyword types Curio
ships are pages of the base entry, ``agents/agent.curio.builtin@1/``, which
the backend renders when it starts (``agent_text``). A fact the code owns is a
marker in them, filled from the code that owns it.

New names are read inside each test, so this module imports on a checkout
without them and each test fails on its own.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
AGENTS = REPO_ROOT / "agents"
BASE = AGENTS / "agent.curio.builtin@1"
#: The pages this prose lives in.
PAGES = (
    "tools.md", "protocol.md", "frames.md", "delegate-contracts.md",
    "conversation-title.md", "keyword-types.md", "rules/plan-rules.md",
)


def _fresh_loader(monkeypatch):
    """The loader as in a process that has not started: nothing rendered, no
    ``--dev``, no delegate contract parsed. The test's end restores the
    process's own, so a contract this test changes never reaches another."""
    from utk_curio.backend.app.agents.application.turns import delegates
    from utk_curio.backend.app.agents.domain import agent_text

    monkeypatch.delenv("CURIO_DEV", raising=False)
    monkeypatch.setattr(agent_text, "_TEXTS", {})
    monkeypatch.setattr(agent_text, "_STARTED", False)
    monkeypatch.setattr(delegates, "_PARSED_CONTRACTS", {}, raising=False)
    return agent_text


def _dev(monkeypatch):
    """Under ``curio.py start --dev`` every read renders again, so a change to
    a page or to the code a marker reads shows on the next read."""
    _fresh_loader(monkeypatch)
    monkeypatch.setenv("CURIO_DEV", "1")


def _agents_copy(tmp_path, monkeypatch) -> Path:
    """A copy of ``agents/`` the test may edit, which the pages are read from."""
    from utk_curio.backend.app.agents.domain import agent_text, builtin

    root = tmp_path / "agents"
    shutil.copytree(AGENTS, root)
    monkeypatch.setattr(builtin, "agents_dir", lambda: root)
    monkeypatch.setattr(agent_text, "base_dir", lambda: root / BASE.name)
    return root / BASE.name


def _section(page: str, name: str) -> str:
    from utk_curio.backend.app.agents.domain import agent_text

    return agent_text.section(page, name)


def _descriptions(schema) -> list[str]:
    """Every ``description`` a JSON Schema holds, its own and its parts'."""
    found = []
    if isinstance(schema, dict):
        if isinstance(schema.get("description"), str):
            found.append(schema["description"])
        for value in (schema.get("properties") or {}).values():
            found += _descriptions(value)
        found += _descriptions(schema.get("items"))
    return found


def test_the_base_entry_holds_a_page_for_each():
    listed = json.loads((BASE / "manifest.json").read_text(encoding="utf-8"))["pages"]
    missing = [page for page in PAGES if page not in listed or not (BASE / page).is_file()]
    assert not missing, f"the base entry lists no page, or holds no file, for {missing}"


def test_a_run_is_told_of_each_tool_what_the_tools_page_says(monkeypatch):
    """Each tool's description, its native description and the text of each
    of its parameters are its section of ``tools.md``; the texts several tools
    take are its ``parameters`` section. No text of the page goes unused."""
    from utk_curio.backend.app.agents.application import tools

    _fresh_loader(monkeypatch)
    texts = tools.tool_texts()
    assert set(texts) == {*tools.REGISTRY, tools.DELEGATE_TOOL, tools.SHARED_PARAMETERS}
    shared = dict(texts[tools.SHARED_PARAMETERS].parameters)
    used_shared = set()
    for tool_id, contract in tools.REGISTRY.items():
        text = texts[tool_id]
        assert contract.description == text.description and text.description, tool_id
        assert contract.native_description == text.native_description, tool_id
        described = _descriptions(contract.parameters)
        own = set(text.parameters.values())
        assert set(described) <= own | set(shared.values()), (tool_id, sorted(set(described) - own))
        assert own <= set(described), (tool_id, sorted(own - set(described)))
        used_shared |= set(described) - own
    assert used_shared == set(shared.values())
    (spec,) = tools.native_tools([], ["node.content.generate"])
    assert spec["description"] == texts[tools.DELEGATE_TOOL].description
    assert set(_descriptions(spec["parameters"])) == set(texts[tools.DELEGATE_TOOL].parameters.values())
    for spec in tools.native_tools(list(tools.REGISTRY)):
        contract = tools.REGISTRY[tools.tool_id_of(spec["name"])]
        assert spec["description"] == (texts[contract.id].native_description or texts[contract.id].description)
    plan = texts["dataflow.plan.write"]
    rules = (BASE / "rules" / "plan-rules.md").read_text(encoding="utf-8").rstrip("\n")
    assert plan.description.endswith(rules) and plan.native_description.endswith(rules)


def test_the_reply_protocol_is_the_protocol_page(monkeypatch):
    from utk_curio.backend.app.agents.application import tools
    from utk_curio.backend.app.agents.domain import builtin, content

    _fresh_loader(monkeypatch)
    page = builtin.PROTOCOL_FILE

    def say(name):
        return _section(page, name)

    assert content.tail_instruction() == content.tail_instruction([]) == say("suggested-prompts")
    grants = tools.grant_descriptions(["catalog.search", "discovery.search"])
    lines = "\n".join(f"- {tool_id}: {description}" for tool_id, description in grants)
    assert content.tail_instruction(grants) == (
        f"{say('suggested-prompts')}\n\n{say('tools')}\n{lines}\n{say('tool-request')}"
        f"\n\n{say('dataset-candidates')}\n{say('dataset-candidates-from-portals')}"
    )
    assert content.tail_instruction(grants, native_tools=True) == (
        f"{say('suggested-prompts')}\n\n{say('native-tools')}"
        f"\n\n{say('dataset-candidates')}\n{say('dataset-candidates-from-portals')}"
    )
    entries = [("node.content.generate", "Node Builder")]
    for native, ending in ((False, "delegate-request"), (True, "delegate-tool")):
        paragraph = content.delegation_instruction(entries, native_tools=native)
        assert paragraph.startswith(say("delegation") + "\n") and paragraph.endswith("\n" + say(ending))


def test_the_names_the_prose_had_in_python_are_gone():
    """Each text is read by its page and section, through the loader: no
    Python name is left for it, an alias reading the page included."""
    import importlib

    gone = {
        "agents.domain.content": (
            "TAIL_INSTRUCTION", "NATIVE_TOOLS_INSTRUCTION", "CANDIDATES_INSTRUCTION", "CANDIDATES_DISCOVERY_ADDENDUM",
        ),
        "agents.domain.contracts": ("CONFIGURATION_FRAME",),
        "agents.application.tools": ("_PLAN_RULES", "_WIDGETS", "_SCENARIO", "_NODE_ID", "_APPEARANCE"),
        "agents.application.turns.titles": ("TITLE_PROMPT",),
        "agents.service": ("TITLE_PROMPT",),
        "agents.application.turns.examples": ("HEADING",),
        "agents.application.turns.policy": ("_CONTEXT_FRAME",),
        "agents.application.turns.roster": ("_NO_NOTE_TEMPLATE_LINE",),
        "agents.application.turns.grounding": ("_DISCOVERY_RULE",),
        "agents.application.turns.delegates": ("_BUILD_REQUEST_CONTRACT", "_NOTES_REPLY_CONTRACT"),
    }
    left = []
    for module, names in gone.items():
        loaded = importlib.import_module(f"utk_curio.backend.app.{module}")
        left += [f"{module}.{name}" for name in names if hasattr(loaded, name)]
        assert not hasattr(loaded, "__getattr__"), f"{module} answers names it does not hold"
    assert not left, f"these names of the moved prose are still in Python: {left}"


def test_what_a_run_is_given_is_framed_by_the_frames_page(monkeypatch):
    from utk_curio.backend.app.agents.application import delegation
    from utk_curio.backend.app.agents.application.turns import examples, policy, prepare, roster
    from utk_curio.backend.app.agents.domain import builtin, contracts

    _fresh_loader(monkeypatch)
    page = builtin.FRAMES_FILE

    def say(name):
        return _section(page, name)

    system = {"role": "system", "content": "s"}
    context = prepare._messages(system, [], "the canvas", "hello")[1]
    assert context == {"role": "user", "content": f"{say('canvas-context')}\n{'the canvas'}"}
    assert policy.context_frame() == say("canvas-context")

    frame = say("delegated-task")
    assert frame.count("{parent}") == 1 and frame.count("{capability}") == 1
    framed = delegation._frame_inputs("agent.curio.node-builder@1", "node.content.generate", {"a": 1})
    expected = frame.replace("{parent}", "agent.curio.node-builder@1").replace("{capability}", "node.content.generate")
    assert framed == expected + "\n" + json.dumps({"a": 1}, indent=2)

    configuration = contracts.render_configuration({"keywordTypes": contracts.KEYWORD_TYPES.default})
    assert configuration.startswith(say("configuration") + "\n\n") and contracts.configuration_frame() == say("configuration")

    block = examples.block_for("road sunlight shadow buildings", node_type="curio.builtin/autk-grammar")
    assert block and block.startswith(say("worked-examples") + "\n\n") and examples.heading() == say("worked-examples")

    row = {"id": "curio.notes/note", "label": "Note", "authorable": True, "description": "A note."}
    assert roster._available_templates_block("p", {"available": []}) == say("no-templates")
    listed = roster._available_templates_block("p", {"available": [row]}, notes_agent=True)
    assert listed.startswith(say("templates") + "\n- curio.notes/note") and listed.endswith("\n" + say("no-note-template"))
    enlistable = roster._enlistable_templates_block("p", {"notEnlisted": [{**row, "dirName": "curio.notes@1"}]}, 5)
    assert enlistable.startswith(say("templates-not-enlisted") + "\n- curio.notes/note")


def test_a_delegated_run_s_contracts_the_title_prompt_and_the_keyword_types_are_pages(monkeypatch):
    from utk_curio.backend.app.agents.application.turns import delegates, titles
    from utk_curio.backend.app.agents.domain import agent_text, builtin, contracts

    _fresh_loader(monkeypatch)
    page = builtin.DELEGATE_CONTRACTS_FILE
    build = delegates._build_request_contract()
    assert build.pop("backendContract") == builtin.read_page(builtin.PACKAGE_CONTRACT_FILE, wanted_by="the test")
    assert build == agent_text.json_block(_section(page, "build-request"), "build-request")
    notes = agent_text.json_block(_section(page, "notes-reply"), "notes-reply")
    # One dict while the page reads the same, as the module constant was.
    assert delegates._notes_reply_contract() == notes and delegates._notes_reply_contract() is delegates._notes_reply_contract()
    assert delegates._discovery_reply_contract() == (
        f"{_section(page, 'dataset-candidates')}\n\n{_section(builtin.PROTOCOL_FILE, 'dataset-candidates')}"
    )
    title = agent_text.page_text(builtin.TITLE_FILE)
    assert titles.title_prompt() == title.rstrip("\n")
    keyword_types = agent_text.page_text(contracts.KEYWORD_TYPES_PAGE)
    assert contracts.KEYWORD_TYPES.default == agent_text.json_block(keyword_types, "keyword-types.md")


def test_the_title_call_sends_the_title_page(monkeypatch):
    from utk_curio.backend.app.agents.application.turns import titles

    _fresh_loader(monkeypatch)
    sent = []

    def _turn_text(config, messages, **kwargs):
        sent.append(messages)
        raise RuntimeError("the test stops here")

    # A title is best effort, so the call swallows the stop.
    monkeypatch.setattr(titles, "_turn_text", _turn_text)
    titles._generate_conversation_title("1", "p", "a", "How warm is Chicago?", config=None)
    assert sent and sent[0] == [
        {"role": "system", "content": titles.title_prompt()},
        {"role": "user", "content": "How warm is Chicago?"},
    ]


def test_an_edit_to_a_page_reaches_the_runs(tmp_path, monkeypatch):
    """With ``--dev`` each page is rendered at each read, so an edit to the
    page reaches what a run is told: the text is the page's, not a copy."""
    from utk_curio.backend.app.agents.application import tools
    from utk_curio.backend.app.agents.application.turns import delegates, policy, titles
    from utk_curio.backend.app.agents.domain import content, contracts

    base = _agents_copy(tmp_path, monkeypatch)
    _dev(monkeypatch)

    def edit(page, old, new):
        file = base / page
        text = file.read_text(encoding="utf-8")
        assert text.count(old) == 1, (page, old)
        file.write_text(text.replace(old, new), encoding="utf-8")

    edit("tools.md", "Fetch one public https URL", "Fetch ONE edited https URL")
    edit("tools.md", "- url: One public https URL.", "- url: An edited URL.")
    edit("rules/plan-rules.md", "A plan may add nodes", "An edited plan may add nodes")
    edit("protocol.md", "When one or more follow-up prompts", "When one or more EDITED follow-up prompts")
    edit("frames.md", "[attachment context", "[edited attachment context")
    edit("delegate-contracts.md", "compose findings ONLY from", "compose edited findings ONLY from")
    edit("conversation-title.md", "Summarize the user's request", "Summarize the edited request")
    edit("keyword-types.md", '"name": "Action"', '"name": "Deed"')

    fetch = tools.REGISTRY["web.fetch"]
    assert fetch.description.startswith("Fetch ONE edited https URL")
    assert fetch.parameters["properties"]["url"]["description"] == "An edited URL."
    plan = tools.REGISTRY["dataflow.plan.write"]
    assert "An edited plan may add nodes" in plan.description and "An edited plan may add nodes" in plan.native_description
    assert content.tail_instruction([]).startswith("When one or more EDITED follow-up prompts")
    assert policy.context_frame().startswith("[edited attachment context")
    assert delegates._notes_reply_contract()["rules"][0].startswith("compose edited findings ONLY from")
    assert titles.title_prompt().startswith("Summarize the edited request")
    assert contracts.KEYWORD_TYPES.default[0]["name"] == "Deed"


def test_a_composed_turn_reads_no_file_after_start(monkeypatch):
    """The backend renders every page when it starts; composing a run's turns
    after that reads the renders, never a file."""
    from utk_curio.backend.app.agents.application import delegation, tools
    from utk_curio.backend.app.agents.application.turns import delegates, examples, policy, roster, titles
    from utk_curio.backend.app.agents.domain import content, contracts, document_validation

    agent_text = _fresh_loader(monkeypatch)
    agent_text.render_at_start()
    reads = []
    monkeypatch.setattr(agent_text, "_source", lambda file: reads.append(file) or "")
    content.tail_instruction(tools.grant_descriptions(list(tools.REGISTRY)))
    content.tail_instruction(tools.grant_descriptions(list(tools.REGISTRY)), native_tools=True)
    tools.native_tools(list(tools.REGISTRY), ["node.content.generate"])
    content.delegation_instruction([("a.b", "A")])
    content.delegation_instruction([("a.b", "A")], native_tools=True)
    policy.context_frame()
    delegation._frame_inputs("agent.curio.node-builder@1", "a.b", {})
    contracts.render_configuration({"keywordTypes": contracts.KEYWORD_TYPES.default})
    examples.heading()
    roster._available_templates_block("p", {"available": []})
    delegates._build_request_contract()
    delegates._notes_reply_contract()
    delegates._discovery_reply_contract()
    titles.title_prompt()
    document_validation.grammar_shape("vega-lite")
    assert reads == [], f"composing a turn read {reads}"


#: Each fact the moved prose states that the code owns: the page, the marker
#: its source holds, and the code it is filled from.
FACTS = [
    ("tools.md", "{{egress.calls_per_run}}", "utk_curio.backend.app.common.egress_policy", "MAX_CALLS_PER_RUN"),
    ("tools.md", "{{models.search_max_rows}}", "utk_curio.backend.app.agents.domain.contracts", "MODELS_SEARCH_MAX_ROWS"),
    ("tools.md", "{{models.max_labels}}", "utk_curio.backend.app.agents.domain.contracts", "MODEL_LABELS_MAX"),
    ("protocol.md", "{{suggested_prompts.max_chars}}", "utk_curio.backend.app.agents.domain.content", "_PROMPT_MAX_CHARS"),
    ("protocol.md", "{{suggested_prompts.alternatives}}", "utk_curio.backend.app.agents.domain.content", "_MAX_ALTERNATIVES"),
    ("protocol.md", "{{candidates.rows_per_lane}}", "utk_curio.backend.app.agents.domain.content", "_CANDIDATES_MAX_ROWS_PER_LANE"),
    ("protocol.md", "{{candidates.name_chars}}", "utk_curio.backend.app.agents.domain.content", "_CANDIDATE_NAME_MAX_CHARS"),
    ("protocol.md", "{{candidates.text_chars}}", "utk_curio.backend.app.agents.domain.content", "_CANDIDATE_TEXT_MAX_CHARS"),
]


@pytest.mark.parametrize("page, marker, module, name", FACTS, ids=[fact[3] for fact in FACTS])
def test_each_number_the_prose_states_is_filled_from_the_code_that_owns_it(page, marker, module, name, monkeypatch):
    """The page holds the marker, not the number, and a change to the code
    reaches what a run is told."""
    import importlib

    from utk_curio.backend.app.agents.application import tools
    from utk_curio.backend.app.agents.domain import content

    source = (BASE / page).read_text(encoding="utf-8")
    assert marker in source, f"{page} states {name} without the marker {marker}"
    _dev(monkeypatch)
    monkeypatch.setattr(importlib.import_module(module), name, 987)
    told = "\n".join([
        content.tail_instruction(tools.grant_descriptions(["catalog.search", "discovery.search"])),
        *(json.dumps(spec) for spec in tools.native_tools(list(tools.REGISTRY))),
    ])
    assert told.count("987") >= source.count(marker), f"{name} set to 987 reached the runs {told.count('987')} times"


def test_each_list_and_name_the_prose_states_is_filled_from_the_code_that_owns_it(monkeypatch):
    from utk_curio.backend.app.agents.application import tools
    from utk_curio.backend.app.agents.application.turns import delegates
    from utk_curio.backend.app.agents.domain import builtin, content, contracts, document_validation, tool_names
    from utk_curio.backend.app.execution.code_references import reference_text
    from utk_curio.backend.app.packages.domain import backend_contract, node_appearance

    def source(page):
        return (BASE / page).read_text(encoding="utf-8")

    assert "{{candidates.source_types}}" in source("protocol.md")
    assert "{{tools.wire_name:dataflow.read}}" in source("protocol.md")
    assert "{{tools.delegate}}" in source("protocol.md")
    assert "{{agent.name:agent.curio.node-builder}}" in source("protocol.md")
    assert source("delegate-contracts.md").count("{{note.palette_choices}}") == 2
    assert "{{backend.timeout_class_choices}}" in source("delegate-contracts.md")
    assert "{{backend.handler_pattern}}" in source("delegate-contracts.md")
    assert "{{widgets.reference:name}}" in source("tools.md")

    _fresh_loader(monkeypatch)
    protocol = content.tail_instruction(tools.grant_descriptions(["catalog.search", "discovery.search"]))
    assert f'"sourceType": "{"|".join(content._CANDIDATE_SOURCE_TYPES)}"' in protocol
    native = _section("protocol.md", "native-tools")
    assert f"dataflow.read is called {tool_names.wire_name('dataflow.read')}." in native
    node_builder = builtin.get_builtin_manifest(builtin.builtin_coord("agent.curio.node-builder")).name
    assert f"handed to {node_builder} instead" in _section("protocol.md", "dataset-candidates-from-portals")
    assert f"call the {tool_names.DELEGATE_TOOL} tool" in content.delegation_instruction([("a.b", "A")], native_tools=True)
    name = tools.REGISTRY["node.create"].parameters["properties"]["widgets"]["items"]["properties"]["name"]
    assert reference_text("name") in name["description"]

    _dev(monkeypatch)
    monkeypatch.setattr(content, "_CANDIDATE_SOURCE_TYPES", ("api", "lake"))
    monkeypatch.setattr(node_appearance, "NAMED_COLORS", {"teal": "#00ffff", "rust": "#b7410e"})
    monkeypatch.setattr(backend_contract, "TIMEOUT_CLASSES", ("brief", "long"))
    monkeypatch.setattr(backend_contract, "HANDLER_NAME_RE", re.compile(r"^[a-z]{1,9}$"))
    monkeypatch.setattr(contracts, "VEGA_SCHEMA_URL", "https://example.org/vega-lite/v9.json")
    assert '"sourceType": "api|lake"' in _section("protocol.md", "dataset-candidates")
    build = delegates._build_request_contract()["shape"]
    assert build["manifest"]["backend"]["handlers"] == [
        {"name": "<a name matching ^[a-z]{1,9}$>", "timeoutClass": "brief | long"}
    ]
    assert build["nodes"][0]["appearance"]["backgroundColor"] == "teal|rust|#rrggbb"
    assert delegates._notes_reply_contract()["shape"]["notes"][0]["color"] == "teal|rust|#rrggbb"
    assert '"$schema": "https://example.org/vega-lite/v9.json"' in document_validation.grammar_shape("vega-lite")


def test_the_candidates_block_offers_every_source_type_a_row_may_carry(monkeypatch):
    """The block a run is shown lists each ``sourceType`` the parser accepts,
    ``discovery`` included, so a row the model copies from it is kept."""
    from utk_curio.backend.app.agents.application import tools
    from utk_curio.backend.app.agents.domain import content

    _fresh_loader(monkeypatch)
    told = content.tail_instruction(tools.grant_descriptions(["catalog.search"]))
    shown = re.search(r'"sourceType": "([a-z|]+)", "url"', told)
    assert shown, "the candidates block shows no sourceType list"
    offered = shown.group(1).split("|")
    assert offered == list(content._CANDIDATE_SOURCE_TYPES), offered
    for source_type in offered:
        row = content._parse_candidate_row({"name": "Trees", "sourceType": source_type}, "external")
        assert row is not None, source_type


def test_the_build_request_names_the_handler_pattern_the_build_checks(monkeypatch):
    """The handler name a delegated package-writing call is shown is the
    pattern the build refuses others by: a name that starts with a digit fits
    "a-z0-9-" and is refused."""
    from utk_curio.backend.app.agents.application.turns import delegates
    from utk_curio.backend.app.packages.domain.backend_contract import HANDLER_NAME_RE, TIMEOUT_CLASSES

    _fresh_loader(monkeypatch)
    (handler,) = delegates._build_request_contract()["shape"]["manifest"]["backend"]["handlers"]
    assert handler == {"name": f"<a name matching {HANDLER_NAME_RE.pattern}>", "timeoutClass": " | ".join(TIMEOUT_CLASSES)}
    assert not HANDLER_NAME_RE.match("9lives") and HANDLER_NAME_RE.match("lives9")


def test_a_frame_that_loses_a_run_value_is_refused(tmp_path, monkeypatch):
    """The delegated task's frame names the delegating agent and the
    capability once each; a frame without one, or with one twice, is refused
    rather than sent without who asked or what for."""
    from utk_curio.backend.app.agents.application import delegation
    from utk_curio.backend.app.agents.domain import agent_text

    base = _agents_copy(tmp_path, monkeypatch)
    _dev(monkeypatch)
    frames = base / "frames.md"
    text = frames.read_text(encoding="utf-8")
    for broken in (text.replace("{capability}", "a capability"), text.replace("{parent}", "{parent} {parent}")):
        frames.write_text(broken, encoding="utf-8")
        with pytest.raises(agent_text.AgentTextError, match="delegated-task"):
            delegation._frame_inputs("agent.curio.node-builder@1", "a.b", {})
    frames.write_text(text, encoding="utf-8")
    # One pass: a value that reads like the other slot is still a value.
    frame = _section("frames.md", "delegated-task")
    swapped = frame.replace("{parent}", "\0").replace("{capability}", "{parent}").replace("\0", "{capability}")
    assert delegation._frame_inputs("{capability}", "{parent}", {}) == swapped + "\n{}"


def _moved_texts() -> list[tuple[str, str]]:
    """Every text of this prose a run gets, with where it is: each tool's
    texts, each section of the protocol and the frames, every string of the
    delegate contracts, the title prompt, the plan rules and each keyword
    type's description."""
    from utk_curio.backend.app.agents.application import tools
    from utk_curio.backend.app.agents.domain import agent_text, contracts

    texts = []
    for name, text in tools.tool_texts().items():
        texts += [(f"tools.md, {name}", text.description), (f"tools.md, {name}, native", text.native_description or "")]
        texts += [(f"tools.md, {name}, {path}", said) for path, said in text.parameters.items()]
    for page in ("protocol.md", "frames.md"):
        texts += [(f"{page}, {name}", text) for name, text in agent_text.sections(page).items()]

    def strings(value):
        if isinstance(value, str):
            yield value
        elif isinstance(value, dict):
            for item in value.values():
                yield from strings(item)
        elif isinstance(value, list):
            for item in value:
                yield from strings(item)

    for name, text in agent_text.sections("delegate-contracts.md").items():
        found = list(strings(agent_text.json_block(text, name))) if "```json" in text else [text]
        texts += [(f"delegate-contracts.md, {name}", said) for said in found]
    for page in ("conversation-title.md", "rules/plan-rules.md"):
        texts.append((page, agent_text.page_text(page)))
    texts += [("keyword-types.md", entry["description"]) for entry in contracts.KEYWORD_TYPES.default]
    return texts


#: A moved text is looked for in Python by its sentences and clauses as long
#: as this: a copy is caught by any one of them, whatever punctuation the page
#: changed.
_PIECE_CHARS = 30
_CUT_RE = re.compile(r"(?<=[.;:!?])\s+|\s+-\s+|\n")


def _python_strings() -> list[tuple[str, str]]:
    """Every string literal in ``utk_curio/``'s Python, its tests left out,
    with where it is: adjacent literals joined as Python joins them, and each
    literal part of an f-string."""
    import ast

    found = []
    for path in sorted((REPO_ROOT / "utk_curio").rglob("*.py")):
        relative = path.relative_to(REPO_ROOT).as_posix()
        if "/tests/" in relative or relative.startswith("utk_curio/frontend/"):
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                found.append((f"{relative}:{node.lineno}", node.value))
    return found


def test_no_moved_text_is_left_in_python(monkeypatch):
    """No sentence or clause of the prose the base entry holds is still a
    string in ``utk_curio/``: each text has one home, which an edit to the
    page reaches."""
    _fresh_loader(monkeypatch)
    pieces = {}
    for where, text in _moved_texts():
        for piece in _CUT_RE.split(text):
            piece = piece.strip()
            if len(piece) >= _PIECE_CHARS:
                pieces.setdefault(piece, where)
    assert len(pieces) > 200, f"the scan cut only {len(pieces)} pieces of moved text; it would mean nothing"
    python = _python_strings()
    assert len(python) > 1000, "the scan found almost no Python strings"
    left = sorted({
        f"{location}: {piece!r} ({where})"
        for piece, where in pieces.items()
        for location, literal in python
        if piece in literal
    })
    assert not left, "moved text still in Python:\n" + "\n".join(left[:40])


def test_a_page_s_sections_are_read_strictly(tmp_path, monkeypatch):
    """A section the runtime asks for and the page lacks, a name given twice,
    and a tool section with a stray line are refused, naming the page; a
    ``## `` line inside a fenced block is the section's text."""
    from utk_curio.backend.app.agents.application import tools
    from utk_curio.backend.app.agents.domain import agent_text

    base = _agents_copy(tmp_path, monkeypatch)
    _dev(monkeypatch)
    with pytest.raises(agent_text.AgentTextError, match="protocol.md has no section 'no-such'"):
        agent_text.section("protocol.md", "no-such")
    protocol = base / "protocol.md"
    text = protocol.read_text(encoding="utf-8")
    protocol.write_text(text + "\n## tools\n\nAgain.\n", encoding="utf-8")
    with pytest.raises(agent_text.AgentTextError, match="two sections named 'tools'"):
        agent_text.section("protocol.md", "tools")
    protocol.write_text(text + "\n## fenced\n\n```text\n## not a section\n```\n", encoding="utf-8")
    assert agent_text.section("protocol.md", "fenced") == "```text\n## not a section\n```"
    page = base / "tools.md"
    page.write_text(page.read_text(encoding="utf-8").replace("- url: One public", "- url One public"), encoding="utf-8")
    with pytest.raises(agent_text.AgentTextError, match="web.fetch"):
        tools.REGISTRY["web.fetch"].parameters
