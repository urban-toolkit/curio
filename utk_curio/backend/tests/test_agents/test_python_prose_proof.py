"""Proof of the move into the base entry: a run gets today's text, but for the listed changes.

The prose a run's turns were composed from was Python's. This commit keeps
that Python, renamed ``_TODAY_*`` and ``_today_*`` beside the readers of the
base entry, and compares what each composes: each tool's description, native
description and parameters, the native delegation tool, the tail and the
delegation paragraph for several grants, the frames and the template rosters,
the delegated runs' contracts, the title prompt, the keyword types and the
Vega-Lite document's shape. They agree byte for byte but for these changes,
made to the moved text only (a line format that stays in Python, such as a
roster line, stays as it was):

- each of the 29 em dashes the moved text held becomes a colon, a comma,
  parentheses or a full stop, as ``DASHES`` lists them, since no page of the
  base entry holds an en or em dash;
- the candidates' ``sourceType`` list names ``discovery`` too, which the
  parser accepts;
- the build request's handler name gives the pattern the build checks names
  against, where it said "a-z0-9-".

The next commit deletes the Python copies and this test.
"""

from __future__ import annotations

import json

EM = chr(0x2014)
#: Each em dash the moved text held, by the words around it, and what took its place.
DASHES = [
    ("API shapes " + EM + " never to crawl", "API shapes, never to crawl"),
    ('that run. Params: {"nodeId": "..."} ' + EM + " defaults to the node this agent is attached to.",
     'that run. Params: {"nodeId": "..."} (defaults to the node this agent is attached to).'),
    ('saved spec. Params: {"nodeId": "..."} ' + EM + " defaults to the node this agent is attached to.",
     'saved spec. Params: {"nodeId": "..."} (defaults to the node this agent is attached to).'),
    ("and description " + EM + " catalog-lane candidates", "and description. Catalog-lane candidates"),
    ("and builtin " + EM + " recommendation candidates", "and builtin. Recommendation candidates"),
    ("version conflicts " + EM + " use it to enrich", "version conflicts. Use it to enrich"),
    ("curio.notes@1 " + EM + " from packages.catalog", "curio.notes@1, from packages.catalog"),
    ('templates" list ' + EM + " never invented", 'templates" list, never invented'),
    ("[attachment context " + EM + " current canvas state]", "[attachment context: current canvas state]"),
    (" " + EM + " capability ", ", capability "),
    ("none " + EM + " nothing enlisted", "none. Nothing enlisted"),
    ("note content " + EM + " take the", "note content. Take the"),
    ("enlisted in this project " + EM + " you already have these; propose package.install with the named "
     "package to use one, and do NOT author a duplicate package:",
     "enlisted in this project (you already have these; propose package.install with the named "
     "package to use one, and do NOT author a duplicate package):"),
    ("other keys " + EM + " there is no", "other keys: there is no"),
    ("successful answer " + EM + " the caller acts", "successful answer: the caller acts"),
    ("installed target " + EM + " extend only>", "installed target (extend only)>"),
    ("'curio.notes' " + EM + " single-segment ids", "'curio.notes'. Single-segment ids"),
    ("source registers " + EM + " custom looks only>", "source registers (custom looks only)>"),
    ("Run invokes " + EM + " backend templates only>", "Run invokes (backend templates only)>"),
    ("})) " + EM + " import react normally", "})). Import react normally"),
    ("backgroundColor) " + EM + " read THESE fields", "backgroundColor). Read THESE fields"),
    ("JS dependencies " + EM + " write small", "JS dependencies: write small"),
    ("VERBATIM " + EM + " never invent placeholder", "VERBATIM. Never invent placeholder"),
    ("to the question " + EM + " always present>", "to the question (always present)>"),
    ("notesTemplates " + EM + " omit when that list is empty>", "notesTemplates (omit when that list is empty)>"),
    ("clean markdown " + EM + " bold fact labels", "clean markdown: bold fact labels"),
    ("searchResults " + EM + " when it carries", "searchResults. When it carries"),
    ("as datasetId " + EM + " any other id is dropped", "as datasetId. Any other id is dropped"),
    ("title only " + EM + " no quotes", "title only: no quotes"),
]
#: The restated facts that were wrong, as they read before and after.
FACTS = [
    ('"sourceType": "api|endpoint|portal|catalog|document|database"',
     '"sourceType": "api|endpoint|portal|catalog|document|database|discovery"'),
    ('"name": "<a-z0-9- name>"', '"name": "<a name matching ^[a-z][a-z0-9-]{0,63}$>"'),
]


def _changed(text: str) -> str:
    for before, after in DASHES + FACTS:
        text = text.replace(before, after)
    assert EM not in text, f"an em dash no change lists: {text[max(0, text.find(EM) - 40):text.find(EM) + 40]!r}"
    return text


def _expected(old: str, moved: list[str] | None = None) -> str:
    """*old* with the changes applied to its moved pieces (all of it when none are named)."""
    for piece in (moved if moved is not None else [old]):
        assert piece in old, piece[:80]
        old = old.replace(piece, _changed(piece))
    return old


def _difference(new: str, expected: str) -> str:
    at = next((i for i, (a, b) in enumerate(zip(new, expected)) if a != b), min(len(new), len(expected)))
    return f"at {at}: {new[max(0, at - 40):at + 60]!r}, expected {expected[max(0, at - 40):at + 60]!r}"


def _check(differing: list, label: str, new: str, old: str, moved: list[str] | None = None) -> None:
    expected = _expected(old, moved)
    if new != expected:
        differing.append(f"{label}: {_difference(new, expected)}")


def test_each_tool_is_told_as_before(monkeypatch):
    from utk_curio.backend.app.agents.application import tools

    monkeypatch.delenv("CURIO_DEV", raising=False)
    assert list(tools.REGISTRY) == list(tools._TODAY_REGISTRY)
    differing: list[str] = []
    for tool_id, old in tools._TODAY_REGISTRY.items():
        new = tools.REGISTRY[tool_id]
        assert (new.id, new.contract_version, new.effect, new.label) == (
            old.id, old.contract_version, old.effect, old.label), tool_id
        _check(differing, f"{tool_id} description", new.description, old.description)
        _check(differing, f"{tool_id} native", new.native_description or "", old.native_description or "")
        _check(differing, f"{tool_id} parameters", json.dumps(new.parameters, ensure_ascii=False),
               json.dumps(old.parameters, ensure_ascii=False))
    capabilities = ["node.content.generate", "dataset.discover"]
    _check(differing, "the delegate tool", json.dumps(tools.delegate_tool(capabilities), ensure_ascii=False),
           json.dumps(tools._today_delegate_tool(capabilities), ensure_ascii=False))
    assert not differing, "differs from today's text:\n" + "\n".join(differing)


def test_the_tail_and_the_delegation_paragraph_are_as_before(monkeypatch):
    from utk_curio.backend.app.agents.application import tools
    from utk_curio.backend.app.agents.domain import agent_text, builtin, content

    monkeypatch.delenv("CURIO_DEV", raising=False)
    protocol = [content._TODAY_TAIL_INSTRUCTION, content._TODAY_NATIVE_TOOLS_INSTRUCTION,
                content._TODAY_CANDIDATES_INSTRUCTION, content._TODAY_CANDIDATES_DISCOVERY_ADDENDUM]
    differing: list[str] = []
    for grants in ([], ["node.read"], ["catalog.search"], ["discovery.search"],
                   ["catalog.search", "discovery.search"], list(tools.REGISTRY)):
        for native in (False, True):
            old_pairs = [(tool_id, tools._TODAY_REGISTRY[tool_id].description) for tool_id in grants]
            old = content._today_tail_instruction(old_pairs, native_tools=native)
            moved = [piece for piece in protocol if piece in old]
            moved += [] if native or not grants else [description for _id, description in old_pairs]
            new = content.tail_instruction(tools.grant_descriptions(grants), native_tools=native)
            _check(differing, f"the tail, {grants}, native {native}", new, old, moved)
    entries = [("node.content.generate", "Node Builder"), ("dataset.discover", "Dataset Finder")]
    for native in (False, True):
        old = content._today_delegation_instruction(entries, native_tools=native)
        _check(differing, f"the delegation paragraph, native {native}",
               content.delegation_instruction(entries, native_tools=native), old, [])
    for section, old in (("suggested-prompts", content._TODAY_TAIL_INSTRUCTION),
                         ("native-tools", content._TODAY_NATIVE_TOOLS_INSTRUCTION),
                         ("dataset-candidates", content._TODAY_CANDIDATES_INSTRUCTION),
                         ("dataset-candidates-from-portals", content._TODAY_CANDIDATES_DISCOVERY_ADDENDUM)):
        _check(differing, f"protocol.md, {section}", agent_text.section(builtin.PROTOCOL_FILE, section), old)
    assert not differing, "differs from today's text:\n" + "\n".join(differing)


def _moved_today() -> list[str]:
    """Every text that moved, as Python held it: each tool's texts, the reply
    protocol, the frames and the roster's headings, the contracts as a delegate
    receives them, the Dataset Finder's rule and the title prompt."""
    from utk_curio.backend.app.agents.application import delegation, tools
    from utk_curio.backend.app.agents.application.turns import delegates, examples, grounding, policy, roster, titles
    from utk_curio.backend.app.agents.domain import content, contracts

    texts = []
    for old in tools._TODAY_REGISTRY.values():
        texts += [old.description, old.native_description or "", json.dumps(old.parameters, ensure_ascii=False)]
    texts.append(json.dumps(tools._today_delegate_tool(["a.b"]), ensure_ascii=False))
    texts += [content._TODAY_TAIL_INSTRUCTION, content._TODAY_NATIVE_TOOLS_INSTRUCTION,
              content._TODAY_CANDIDATES_INSTRUCTION, content._TODAY_CANDIDATES_DISCOVERY_ADDENDUM]
    texts += [policy._TODAY_CONTEXT_FRAME, contracts._TODAY_CONFIGURATION_FRAME, examples._TODAY_HEADING,
              roster._TODAY_NO_NOTE_TEMPLATE_LINE]
    texts.append(delegation._today_frame_inputs("agent.curio.node-builder@1", "a.b", {}).split("\n", 1)[0])
    row = {"id": "curio.notes/note", "label": "Note", "authorable": True, "dirName": "curio.notes@1"}
    texts.append(roster._today_available_templates_block("p", {"available": []}))
    texts.append(roster._today_available_templates_block("p", {"available": [row]}).split("\n", 1)[0])
    texts.append(roster._today_enlistable_templates_block("p", {"notEnlisted": [row]}, 5).split("\n", 1)[0])
    texts += [json.dumps(delegates._TODAY_BUILD_REQUEST_CONTRACT, ensure_ascii=False, indent=2),
              json.dumps(delegates._TODAY_NOTES_REPLY_CONTRACT, ensure_ascii=False, indent=2)]
    texts += [grounding._TODAY_DISCOVERY_RULE, titles._TODAY_TITLE_PROMPT]
    texts += [entry["description"] for entry in contracts._TODAY_KEYWORD_TYPES_DEFAULT]
    return texts


def test_the_changes_are_exactly_the_listed_ones():
    """Each listed dash and fact is in exactly one text that moved, and those
    29 are every em dash the moved text held: nothing else changed."""
    texts = _moved_today()
    found = {before: sum(text.count(before) for text in texts) for before, _after in DASHES + FACTS}
    assert all(count == 1 for count in found.values()), {before: n for before, n in found.items() if n != 1}
    assert sum(text.count(EM) for text in texts) == len(DASHES) == 29


def test_the_frames_and_the_rosters_are_as_before(monkeypatch):
    from utk_curio.backend.app.agents.application import delegation
    from utk_curio.backend.app.agents.application.turns import examples, policy, prepare, roster
    from utk_curio.backend.app.agents.domain import contracts

    monkeypatch.delenv("CURIO_DEV", raising=False)
    differing: list[str] = []
    system = {"role": "system", "content": "s"}
    context = prepare._messages(system, [], "the canvas", "hello")[1]["content"]
    _check(differing, "the canvas context", context, policy._TODAY_CONTEXT_FRAME + "the canvas",
           [policy._TODAY_CONTEXT_FRAME])
    for inputs in ({}, {"subtask": "Load the trees", "nodeContext": {"id": "n1"}}):
        old = delegation._today_frame_inputs("agent.curio.node-builder@1", "node.content.generate", inputs)
        new = delegation._frame_inputs("agent.curio.node-builder@1", "node.content.generate", inputs)
        _check(differing, f"the delegated task, {sorted(inputs)}", new, old, [old.split("\n", 1)[0]])
    default = contracts._TODAY_KEYWORD_TYPES_DEFAULT
    old = "\n\n".join([contracts._TODAY_CONFIGURATION_FRAME, "Keyword types:\n" + contracts.KEYWORD_TYPES.render(default)])
    _check(differing, "the configuration", contracts.render_configuration({"keywordTypes": default}), old,
           [contracts._TODAY_CONFIGURATION_FRAME])
    _check(differing, "the worked examples' heading", examples.heading(), examples._TODAY_HEADING)
    block = examples.block_for("road sunlight shadow buildings", node_type="curio.builtin/autk-grammar")
    assert block and block.startswith(examples.heading() + "\n\n")
    row = {"id": "curio.notes/note", "label": "Note", "authorable": True, "description": "A note.", "widgets": ["w"]}
    for landscape, notes in (({"available": []}, False), ({"available": [row]}, False),
                             ({"available": [row]}, True), ({"available": [{**row, "presentation": True}]}, True)):
        old = roster._today_available_templates_block("p", landscape, notes_agent=notes)
        moved = [old.split("\n", 1)[0]]
        moved += [roster._TODAY_NO_NOTE_TEMPLATE_LINE] if roster._TODAY_NO_NOTE_TEMPLATE_LINE in old else []
        _check(differing, f"the roster, {len(landscape['available'])} templates, notes {notes}",
               roster._available_templates_block("p", landscape, notes_agent=notes), old, moved)
    enlistable = {"notEnlisted": [{**row, "dirName": "curio.notes@1"}]}
    old = roster._today_enlistable_templates_block("p", enlistable, 5)
    _check(differing, "the enlistable roster", roster._enlistable_templates_block("p", enlistable, 5), old,
           [old.split("\n", 1)[0]])
    assert roster._enlistable_templates_block("p", {"notEnlisted": []}, 5) is None
    assert not differing, "differs from today's text:\n" + "\n".join(differing)


def test_the_contracts_the_title_the_keyword_types_and_the_document_shape_are_as_before(monkeypatch):
    from utk_curio.backend.app.agents.application.turns import delegates, grounding, titles
    from utk_curio.backend.app.agents.domain import content, contracts, document_validation

    monkeypatch.delenv("CURIO_DEV", raising=False)
    differing: list[str] = []

    def as_sent(value) -> str:
        """A contract as a delegate receives it in its inputs (``delegation._frame_inputs``)."""
        return json.dumps(value, ensure_ascii=False, indent=2)

    _check(differing, "the build request", as_sent(delegates._build_request_contract()),
           as_sent(delegates._today_build_request_contract()))
    _check(differing, "the notes reply", as_sent(delegates._notes_reply_contract()),
           as_sent(delegates._TODAY_NOTES_REPLY_CONTRACT))
    _check(differing, "the dataset candidates reply", delegates._discovery_reply_contract(),
           grounding._TODAY_DISCOVERY_RULE + "\n\n" + content._TODAY_CANDIDATES_INSTRUCTION)
    _check(differing, "the title prompt", titles.title_prompt(), titles._TODAY_TITLE_PROMPT)
    _check(differing, "the keyword types", json.dumps(contracts.KEYWORD_TYPES.default, ensure_ascii=False),
           json.dumps(contracts._TODAY_KEYWORD_TYPES_DEFAULT, ensure_ascii=False))
    # The document shape stays in Python (a refusal's words); its URL is the constant's now.
    assert document_validation.grammar_shape("vega-lite") == document_validation._TODAY_GRAMMAR_SHAPES["vega-lite"]
    assert document_validation.grammar_shape("something-else") == "a JSON document"
    assert not differing, "differs from today's text:\n" + "\n".join(differing)
