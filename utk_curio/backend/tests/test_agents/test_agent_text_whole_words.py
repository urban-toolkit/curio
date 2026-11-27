"""What Curio's agents show people, and what they tell models, in whole words.

Step 5.1 of the owner's agent chat plan. Earlier steps found these on main:

- a plan joined each node's title and intent with an em dash into the goal
  its agents are given as their mission, which their chats show;
- a node's goal cut at 60 characters, in the middle of a word, wherever a
  turn named the node: Run through, a delegate's written content, and the
  attempts card at 120;
- en and em dashes in what the agents' turns, cards and errors say, and
  counts written as "node(s)" there and in what a check tells a model;
- the Dataset Finder's candidates counted as "candidate(s)" for the model;
- a chart's Build & validate said NOT-EXECUTABLE of a document its grammar
  validated, where nothing failed.

A node is named as its header on the canvas names it: by its title, whole;
with no title, by its template's label (its type in words when the catalog
has none); with no type, by its goal cut on a word with an ellipsis; with no
goal, by its id. Where several nodes are named at once, a node in a scenario
says its scenario, as the plan's card does, and names that still read alike
end with a short id.

The guards read the agents package's Python as the prose guard does: every
string but a docstring, a string statement and a log line's text, which is
for whoever runs Curio. The dash and "(s)" guards read the folders of
:data:`ALSO_SCANNED` too, whose texts reach the agents' cards and models. New
names are read inside each test, so this module imports on a checkout without
them and each test fails on its own.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from types import SimpleNamespace

from utk_curio.backend.tests._support.agent_routes import _auth

REPO_ROOT = Path(__file__).resolve().parents[4]
APP = REPO_ROOT / "utk_curio" / "backend" / "app"
PACKAGE = APP / "agents"
#: The en dash (U+2013) and the em dash (U+2014).
DASHES = re.compile("[" + chr(0x2013) + chr(0x2014) + "]")
#: A count written for one and for many at once; "http(s)" names two schemes.
PLURAL_S = re.compile(r"(?<!http)\(s\)")
#: What a slice that names a node reads: its goal, its title or its label.
NAMES = re.compile(r"goal|title|label", re.IGNORECASE)
#: Calls whose text is a log line or a warning, by the name they are called by.
_LOG_CALL_RE = re.compile(
    r"^(?:\w+\.)?(?:log|logger|logging|_log|_logger|LOG|LOGGER)\.(?:debug|info|warning|warn|error|exception|critical)$"
    r"|^warnings\.warn$"
)

#: Folders of the package the scans leave out, and why.
LEFT_FOLDERS = {
    "evaluation/": (
        "the offline reconstruction evaluation: its reports and the intents its oracle scripts are "
        "tooling for whoever runs an evaluation, not what Curio's agents show or are told"
    ),
}
#: Folders of the app beside the agents package whose strings the dash and
#: "(s)" guards read too, and why.
ALSO_SCANNED = {
    "execution/": (
        "the runner's and the runtime journal's texts: a validation's evidence, a Solve's turns and cards, "
        "and a node's context carry them to people and to models"
    ),
}
#: Slices that bound a text rather than name a node: (file in the package, the
#: sliced expression), and why.
LEFT_CUTS = {
    ("application/dataset_resolution.py", "(mission or str(node.get('goal') or '') or '').strip()"):
        "the mission a Dataset Finder's run is handed: its whole goal, bounded as what a run reads",
    ("application/solve/batch.py", "str((self.nodes_by_id.get(node_id) or {}).get('goal') or '')"):
        "the goal a dependent's run reads of its upstream, bounded as data; its name is cut on a word",
    ("application/solve/batch.py", "self.goals"): "a list of goals, its first 20: no text is cut",
    ("application/tools.py", "str(row.get('title') or '')"): "a web search result's title, bounded as what a run reads",
    ("application/turns/grounding.py",
     "'; '.join((t for t in [str(node.get('goal') or ''), *[str(x or '') for x in extra_texts]] if t))"):
        "the texts a source search reads, bounded as data",
    ("domain/content.py", "str(llm_label)"): "the label of an LLM configuration, not of a node",
    ("domain/validation.py", "str(node.get('goal') or '')"): "the goal a validation's evidence keeps, bounded as data",
}

#: A plan's loader, as earlier steps met it.
TITLE = "Load pedestrians"
#: Its intent: longer than a name's 60 characters, its 60th inside "streets".
INTENT = "load the pedestrians counted per hour on the four busiest streets downtown"
#: That intent as the name of a node with no title.
INTENT_NAME = "load the pedestrians counted per hour on the four busiest…"
#: A goal longer than the attempts card's old 120 characters.
LONG_GOAL = (
    "load the pedestrians counted per hour on the four busiest streets downtown, then keep the counts "
    "of the weekday mornings and evenings"
)
PY = "curio.builtin/python-computation"


def _relative(path: Path) -> str:
    return path.relative_to(PACKAGE).as_posix()


def _left_out(relative: str) -> bool:
    return any(relative.startswith(folder) for folder in LEFT_FOLDERS)


def _literal(node: ast.AST) -> str | None:
    """The literal text of a string expression: a string, or an f-string's
    literal parts with "{}" where each value goes, so that "({seconds}s)"
    reads as no "(s)"."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(part.value if isinstance(part, ast.Constant) else "{}" for part in node.values)
    return None


class _Shown(ast.NodeVisitor):
    """Each string of a module that something shows or says: every string but
    a docstring, a string statement and the text of a log line."""

    def __init__(self):
        self.defs: list[str] = []
        self.calls: list[str] = []
        self.statements: set[int] = set()
        self.found: list[tuple[str, int, str]] = []

    def _docstring(self, node) -> None:
        body = getattr(node, "body", None)
        if body and isinstance(body[0], ast.Expr):
            self.statements.add(id(body[0].value))

    def visit_Module(self, node):
        self._docstring(node)
        self.generic_visit(node)

    def _def(self, node):
        self._docstring(node)
        self.defs.append(node.name)
        self.generic_visit(node)
        self.defs.pop()

    visit_FunctionDef = visit_AsyncFunctionDef = visit_ClassDef = _def

    def visit_Expr(self, node):
        self.statements.add(id(node.value))
        self.generic_visit(node)

    def visit_Call(self, node):
        self.calls.append(ast.unparse(node.func))
        self.generic_visit(node)
        self.calls.pop()

    def _string(self, node) -> None:
        text = _literal(node)
        if text is None or id(node) in self.statements:
            return
        if any(_LOG_CALL_RE.match(call) for call in self.calls):
            return
        self.found.append((".".join(self.defs) or "<module>", node.lineno, text))

    def visit_Constant(self, node):
        self._string(node)

    def visit_JoinedStr(self, node):
        self._string(node)
        for part in node.values:
            if isinstance(part, ast.FormattedValue):
                self.visit(part.value)


def _strings_of(path: Path, relative: str) -> list[tuple[str, str, int, str]]:
    """Every string the module at *path* shows or says: (file, def, line, text)."""
    shown = _Shown()
    shown.visit(ast.parse(path.read_text(encoding="utf-8")))
    return [(relative, where, line, text) for where, line, text in shown.found]


def _shown_strings() -> list[tuple[str, str, int, str]]:
    """Every string the agents package, and each folder of
    :data:`ALSO_SCANNED`, shows or says: (file, def, line, text)."""
    found = []
    for path in sorted(PACKAGE.rglob("*.py")):
        relative = _relative(path)
        if not _left_out(relative):
            found += _strings_of(path, relative)
    for folder in ALSO_SCANNED:
        for path in sorted((APP / folder).rglob("*.py")):
            found += _strings_of(path, path.relative_to(APP).as_posix())
    return found


def _a_bound(upper: ast.AST | None) -> bool:
    """Whether *upper*, the end of a slice, bounds a text: a number, or a
    bound held in a name or an attribute (a constant or a parameter)."""
    if isinstance(upper, ast.Constant):
        return isinstance(upper.value, int)
    return isinstance(upper, (ast.Name, ast.Attribute))


def _offenders(pattern: re.Pattern) -> list[str]:
    """Each string the agents package shows or says that *pattern* finds."""
    found = _shown_strings()
    assert len(found) > 1000, f"the scan read {len(found)} strings; it would mean nothing"
    return [f"{relative}:{line} ({where}): {text[:120]!r}" for relative, where, line, text in found if pattern.search(text)]


def _pages() -> list[Path]:
    """What the agents read beside the code: every Markdown page and manifest
    of agents/, and each skill's SKILL.md."""
    pages = [path for path in sorted((REPO_ROOT / "agents").rglob("*")) if path.suffix in (".md", ".json")]
    return pages + sorted((REPO_ROOT / "skills").glob("*/SKILL.md"))


class TestTheTextTheAgentsShow:
    """No string the agents package shows people or tells a model holds an en
    or em dash, or counts with "(s)"; no page an agent reads does either."""

    def test_no_string_holds_an_en_or_em_dash(self):
        wrong = _offenders(DASHES)
        assert not wrong, (
            "these strings of the agents package hold an en or em dash: a colon, a comma, a semicolon or "
            "parentheses say it instead:\n" + "\n".join(wrong)
        )

    def test_no_string_counts_with_an_s_in_brackets(self):
        wrong = _offenders(PLURAL_S)
        assert not wrong, (
            "these strings count with \"(s)\": the count's noun agrees with it instead:\n" + "\n".join(wrong)
        )

    def test_no_page_an_agent_reads_holds_a_dash_or_counts_with_an_s_in_brackets(self):
        pages = _pages()
        assert len(pages) > 50, f"the scan read {len(pages)} pages; it would mean nothing"
        wrong = []
        for page in pages:
            for number, line in enumerate(page.read_text(encoding="utf-8").splitlines(), 1):
                if DASHES.search(line) or PLURAL_S.search(line):
                    wrong.append(f"{page.relative_to(REPO_ROOT).as_posix()}:{number}: {line.strip()[:120]}")
        assert not wrong, "\n".join(wrong)

    def test_each_folder_left_out_or_read_too_is_there_and_says_why(self):
        for folder, why in LEFT_FOLDERS.items():
            assert (PACKAGE / folder).is_dir() and why, folder
        for folder, why in ALSO_SCANNED.items():
            assert (APP / folder).is_dir() and why, folder

    def test_no_label_is_cut_by_a_slice(self):
        """A node's goal, title or label is never cut to its first N
        characters, N a number or a bound held in a constant or a parameter:
        a name is the node's title whole, or the name its header shows, and a
        bound cuts on a word too."""
        found = []
        for path in sorted(PACKAGE.rglob("*.py")):
            relative = _relative(path)
            if _left_out(relative):
                continue
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if (
                    isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Slice)
                    and node.slice.lower is None and node.slice.step is None
                    and _a_bound(node.slice.upper)
                    and NAMES.search(ast.unparse(node.value))
                ):
                    found.append((relative, ast.unparse(node.value), node.lineno))
        assert len(found) >= len(LEFT_CUTS), f"the scan found {len(found)} cuts; it would mean nothing"
        wrong = [f"{relative}:{line}: {value}" for relative, value, line in found if (relative, value) not in LEFT_CUTS]
        stale = sorted(key for key in LEFT_CUTS if key not in {(relative, value) for relative, value, _ in found})
        assert not wrong and not stale, (
            "these slices cut a node's name in the middle of a word: name it with labels.node_label, or cut "
            "on a word with labels.on_a_word:\n" + "\n".join(wrong)
            + (f"\nand these entries leave out nothing; delete them: {stale}" if stale else "")
        )


class TestANodeIsNamedAsItsCanvasNamesIt:
    """The one rule that names a node in what the agents show."""

    #: Each template's label by unversioned id, as a project's catalog holds them.
    TEMPLATES = {"curio.builtin/vis-vega": "Vega-Lite", "curio.builtin/data-loading": "Data Loading"}

    def _name(self, node) -> str:
        from utk_curio.backend.app.agents.domain import labels

        return labels.node_label(node, templates=self.TEMPLATES)

    def test_its_title_whole_else_its_templates_label_else_its_goal_cut_on_a_word_else_its_id(self):
        long_title = "Load the pedestrians counted per hour on the four busiest streets downtown since 2019"
        assert self._name({"id": "n1", "title": f" {TITLE} ", "goal": INTENT}) == TITLE
        assert self._name({"id": "n1", "title": long_title, "goal": INTENT}) == long_title
        # With no title, the name its header shows: its template's label, for
        # a versioned type too, else its type in words.
        assert self._name({"id": "n1", "type": "curio.builtin/vis-vega@1", "goal": INTENT}) == "Vega-Lite"
        assert self._name({"id": "n1", "type": "curio.builtin/vis-vega", "title": "  ", "goal": INTENT}) == "Vega-Lite"
        assert self._name({"id": "n1", "type": "curio.sky/sky-view", "goal": INTENT}) == "Sky View"
        # With no type, its goal cut on a word; with no goal, its id.
        assert self._name({"id": "n1", "goal": INTENT}) == INTENT_NAME
        assert self._name({"id": "n1", "goal": "load the heat data"}) == "load the heat data"
        assert self._name({"id": "n1", "goal": "  "}) == "n1"
        assert self._name({"id": "n1"}) == "n1"
        assert self._name(None) == ""
        word = "x" * 70
        assert self._name({"id": "n1", "goal": f"{word} and more"}) == f"{word}…"

    def test_no_cut_halves_a_word(self):
        from utk_curio.backend.app.agents.domain import labels

        texts = [INTENT, LONG_GOAL, "Load pedestrians: " + INTENT, "a, b; c: d - e " * 12, "word " * 40]
        for text in texts:
            words = " ".join(text.split())
            for limit in range(8, len(words) + 2):
                cut = labels.on_a_word(text, limit)
                if cut == words:
                    continue
                body = cut[:-1]
                assert cut.endswith("…") and words.startswith(body), (text, limit, cut)
                assert not words[len(body)].isalnum(), f"{cut!r} halves a word of {words!r} at {limit}"
                assert len(body) <= limit or " " not in body, (text, limit, cut)


class TestAPlannedNodesGoal:
    """A plan's node is given its title and its intent as its goal, the
    mission its agents read and their chats show, joined with no dash."""

    def test_is_its_title_a_colon_and_its_intent(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        from utk_curio.backend.tests.test_agents import test_routes_proposals as routes

        user, token = user_and_token
        helper = routes.TestDataflowPlanMint()
        tail = helper._plan_tail(nodes=[{"ref": "load", "nodeType": PY, "title": TITLE, "intent": INTENT}], edges=[])
        att_id, _ = helper._setup(client, user, token, alice_project, monkeypatch, replies=["Here is the plan.\n" + tail])
        card = routes._landed_plan(helper._run(client, token, alice_project, att_id).get_json())
        assert [node["goal"] for node in card["canvas"]["nodes"]] == [f"{TITLE}: {INTENT}"]
        saved = routes.TestNodeCreate()._spec_nodes(user, alice_project)
        assert [node["goal"] for node in saved if node.get("title") == TITLE] == [f"{TITLE}: {INTENT}"]
        # The plan's card says its node the same way, with no dash.
        assert card["preview"].splitlines()[0] == f"{TITLE} · {PY} · {INTENT}"

    def test_after_a_title_that_holds_a_colon_is_a_semicolon(
        self, client, user_and_token, tmp_curio, alice_project, monkeypatch
    ):
        """A title with a colon of its own, as the Crown Heights plot's, gave
        its goal two colons. A semicolon joins such a title to its intent,
        which keeps its case as the plan wrote it, as it does after the colon
        that joins any other title."""
        from utk_curio.backend.tests.test_agents import test_routes_proposals as routes

        user, token = user_and_token
        plot, load, count = "Plot: shadow on Block 1259 through the day", "Load: buildings", "Count trees"
        rows = [
            {"ref": "plot", "nodeType": PY, "title": plot, "intent": "Plot the share of Block 1259 in shadow by the hour"},
            {"ref": "load", "nodeType": PY, "title": load, "intent": "NYC's footprints around the block"},
            {"ref": "count", "nodeType": PY, "title": count, "intent": "Count the trees on each block"},
        ]
        helper = routes.TestDataflowPlanMint()
        tail = helper._plan_tail(nodes=rows, edges=[])
        att_id, _ = helper._setup(client, user, token, alice_project, monkeypatch, replies=["Here is the plan.\n" + tail])
        card = routes._landed_plan(helper._run(client, token, alice_project, att_id).get_json())
        goals = {
            plot: f"{plot}; Plot the share of Block 1259 in shadow by the hour",
            load: f"{load}; NYC's footprints around the block",
            count: f"{count}: Count the trees on each block",
        }
        assert {node["title"]: node["goal"] for node in card["canvas"]["nodes"]} == goals
        saved = routes.TestNodeCreate()._spec_nodes(user, alice_project)
        assert {node["title"]: node["goal"] for node in saved if node.get("title") in goals} == goals


class TestATurnNamesTheNodeWhole:
    """Each turn that names a node names it as its header on the canvas does."""

    def test_run_through_names_the_node_by_its_title(self, client, user_and_token, tmp_curio, alice_project, monkeypatch):
        from utk_curio.backend.tests.test_agents import test_routes_proposals as routes
        from utk_curio.backend.tests.test_agents import test_routes_solve as routes_solve

        user, token = user_and_token
        monkeypatch.setattr(
            "utk_curio.backend.app.execution.runner._http_exec",
            lambda endpoint, payload: {"stdout": [], "stderr": "", "output": {"path": "art-run", "dataType": "dataframe"}},
        )
        tail = routes.TestDataflowPlanMint()._plan_tail(
            nodes=[{"ref": "load", "nodeType": PY, "title": TITLE, "intent": INTENT}], edges=[],
        )
        att_id, _card, _ids, _ = routes_solve._landed_plan(
            client, user, token, alice_project, monkeypatch, replies=["Here is the plan.\n" + tail],
        )
        r = client.post(f"/api/agents/projects/{alice_project}/attachments/{att_id}/run-node",
                        json={"ref": "load"}, headers=_auth(token))
        assert r.status_code == 200, r.get_json()
        assert routes_solve.TestStreamedSolve()._sse_events(r)[-1][1]["ok"] is True
        turns = client.get(f"/api/agents/projects/{alice_project}/attachments/{att_id}/session",
                           headers=_auth(token)).get_json()["turns"]
        ran = [turn for turn in turns if (turn.get("text") or "").startswith("Ran through")]
        assert [turn["text"] for turn in ran] == [f"Ran through {TITLE!r}: ok."]
        lines = ran[0]["content"][0]["lines"]
        assert lines[0] == f"{TITLE} · ok" and lines[2] == "1 node in the chain", lines

    def _written_by_a_delegate(self, client, token, monkeypatch, node: dict) -> list[str]:
        """The turns of the node's own agent that hold the content a canvas
        agent's delegate wrote into *node*."""
        from utk_curio.backend.tests.test_agents import test_delegation as delegation_tests

        body = {"name": "p", "spec": {"dataflow": {"nodes": [node], "edges": [], "packages": []}}, "outputs": []}
        r = client.post("/api/projects", json=body, headers=_auth(token))
        assert r.status_code == 201, r.get_json()
        pid = r.get_json()["id"]
        att_id, _ = delegation_tests._setup(client, token, pid, monkeypatch, replies=[
            delegation_tests._delegate_tail(inputs=json.dumps({"intent": "fix", "nodeId": node["id"]})),
            "print('v2')",
            "Done.",
        ])
        reply = delegation_tests._run(client, token, pid, att_id, message="update the loader").get_json()
        home = next(p for p in reply["content"] if p["type"] == "delegation")["attachmentId"]
        turns = client.get(f"/api/agents/projects/{pid}/attachments/{home}/session", headers=_auth(token)).get_json()["turns"]
        return [turn["text"] for turn in turns if any(p.get("type") == "change" for p in turn.get("content") or [])]

    def test_a_delegates_written_content_names_the_node_by_its_title(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        _user, token = user_and_token
        node = {"id": "n1", "content": "print(1)", "title": TITLE, "goal": INTENT}
        assert self._written_by_a_delegate(client, token, monkeypatch, node) == [f"Wrote the content of {TITLE!r}."]

    def test_a_node_with_no_title_is_named_by_its_templates_label(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        # As its header on the canvas names it, never by its goal.
        _user, token = user_and_token
        node = {"id": "n1", "type": PY, "content": "print(1)", "goal": INTENT}
        assert self._written_by_a_delegate(client, token, monkeypatch, node) == [
            "Wrote the content of 'Python Computation'."
        ]

    def test_a_node_with_no_title_or_type_is_named_by_its_goal_cut_on_a_word(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        _user, token = user_and_token
        node = {"id": "n1", "content": "print(1)", "goal": INTENT}
        assert self._written_by_a_delegate(client, token, monkeypatch, node) == [
            f"Wrote the content of {INTENT_NAME!r}."
        ]

    def _attempts_label(self, monkeypatch, node: dict, label: str) -> str:
        """The label of the attempts card a validation that failed shows for
        *node*, which its turns call *label*."""
        from utk_curio.backend.app.agents.application.solve import validate
        from utk_curio.backend.app.agents.repositories import sessions

        said: list = []
        monkeypatch.setattr(sessions, "append_turns", lambda *args, **kwargs: said.extend(args[4]))
        outcome = {"rounds": 1, "stoppedBy": "attempts", "evidence": {"kind": "execution-error"},
                   "attempts": [{"round": 1, "verdict": "fail", "kind": "execution-error", "detail": "NameError: boom"}]}
        validate._say_it_failed("u1", "p1", "att", "sess", None, None, {"dataflow": {"nodes": [node]}},
                                node, label, outcome, ["round 1: fail"])
        [part] = [p for turn in said for p in turn.get("content") or [] if p.get("type") == "solveAttempts"]
        return part["label"]

    def test_the_attempts_card_names_the_node_by_its_title(self, monkeypatch):
        node = {"id": "n1", "title": TITLE, "goal": LONG_GOAL}
        assert self._attempts_label(monkeypatch, node, TITLE) == TITLE

    def test_the_attempts_card_of_a_node_with_no_title_cuts_its_goal_on_a_word(self, monkeypatch):
        from utk_curio.backend.app.agents.application.solve import node_solve

        node = {"id": "n1", "goal": LONG_GOAL}
        label = self._attempts_label(monkeypatch, node, node_solve.solve_label(node, templates={}))
        assert label == INTENT_NAME

    def test_solve_this_node_names_its_attempts_card_by_the_nodes_title(
        self, client, user_and_token, tmp_curio, monkeypatch
    ):
        from utk_curio.backend.tests.test_agents import test_verified_rounds as rounds_tests

        user, token = user_and_token
        helper = rounds_tests.TestSolveNode()
        bad = helper.LOADER.replace("return df", "always_bad()\nreturn df")
        ctx = helper._setup(client, user, token, monkeypatch, content=bad, child_replies=[bad],
                            exec_outcomes={"always_bad": "Traceback: NameError: always_bad"},
                            title=TITLE, goal=LONG_GOAL)
        done = helper._solve_node(client, token, ctx)[-1][1]
        assert done["verdict"] == "fail"
        turns = client.get(f"/api/agents/projects/{ctx['pid']}/attachments/{ctx['att']}/session",
                           headers=_auth(token)).get_json()["turns"]
        labels = [p["label"] for p in turns[-1].get("content") or [] if p.get("type") == "solveAttempts"]
        assert labels == [TITLE], labels

    def _transcript(self, nodes, results, *, scenarios=None, unstarted=(), cancelled=False):
        """The Build & validate transcript's lines and attempts cards for
        *results*, over a dataflow of *nodes* and *scenarios*."""
        from utk_curio.backend.app.agents.application.solve.batch import SolveBatch

        batch = object.__new__(SolveBatch)
        batch.nodes_by_id = {node["id"]: node for node in nodes}
        batch.spec = {"dataflow": {"nodes": nodes, **({"scenarios": scenarios} if scenarios else {})}}
        batch.current = {"spec": batch.spec}
        batch.user_key, batch.project_id = "u1", "p1"
        batch.unstarted = list(unstarted)
        batch.batch_reason = None
        batch.results = results
        return batch._transcript_lines(cancelled)

    def test_the_build_transcript_names_each_node_as_its_canvas_does(self):
        nodes = [
            {"id": "a1b2c3d4-load", "title": TITLE, "goal": LONG_GOAL},
            {"id": "e5f6a7b8-map", "title": "Library branch map", "goal": "map the branches"},
            {"id": "c9d0e1f2-sum", "goal": LONG_GOAL},
        ]
        failed = {"round": 1, "verdict": "fail", "kind": "execution-error", "detail": "NameError: boom"}
        results = {
            "a1b2c3d4-load": {"status": "failed", "verdict": "fail", "rounds": 2, "stoppedBy": "attempts",
                              "attempts": [failed, {**failed, "round": 2}]},
            "e5f6a7b8-map": {"status": "solved", "verdict": "not-executable", "rounds": 1, "attempts": [],
                             "verification": {"status": "document-valid", "reason": "validated"}},
        }
        lines, parts = self._transcript(nodes, results, unstarted=["c9d0e1f2-sum"], cancelled=True)
        assert lines[0] == f"{TITLE} · failed · fail after 2 rounds", lines
        assert "Library branch map · solved · validated against its grammar after 1 round" in lines, lines
        assert "cancelled: 1 node not attempted" in lines, lines
        assert [part["label"] for part in parts] == [TITLE]

    def test_the_build_transcript_tells_nodes_of_one_name_apart(self):
        """A scenario's copy holds its original's title, and a person can
        title two nodes alike. The transcript's lines and its attempts cards
        say each node's scenario, as the plan's card does, and end names that
        still read alike with a short id."""
        nodes = [
            {"id": "a1b2c3d4-shade", "type": PY, "title": "Shade"},
            {"id": "e5f6a7b8-shade", "type": PY, "title": "Shade"},
            {"id": "c9d0e1f2-load", "type": PY, "title": "Load"},
            {"id": "f3a4b5c6-load", "type": PY, "title": "Load"},
        ]
        scenarios = [
            {"id": "s1", "name": "Base", "color": "#1f77b4", "nodes": ["a1b2c3d4-shade"]},
            {"id": "s2", "name": "Heat", "color": "#ff7f0e", "nodes": ["e5f6a7b8-shade"]},
        ]
        failed = {"round": 1, "verdict": "fail", "kind": "execution-error", "detail": "NameError: boom"}
        results = {
            node["id"]: {"status": "failed", "verdict": "fail", "rounds": 1, "stoppedBy": "attempts",
                         "attempts": [failed]}
            for node in nodes
        }
        lines, parts = self._transcript(nodes, results, scenarios=scenarios)
        names = ["Shade (Base)", "Shade (Heat)", "Load (c9d0e1f2)", "Load (f3a4b5c6)"]
        assert [line for line in lines if not line.startswith(" ")] == [
            f"{name} · failed · fail after 1 round" for name in names
        ], lines
        assert [part["label"] for part in parts] == names


class TestTheFinderCountsItsCandidates:
    """What a parent agent's model is told of the candidates its Dataset
    Finder found: counted as words count, in plain words."""

    def _told(self, rows: list, catalog: list | None = None, listing: list | None = None) -> str:
        from utk_curio.backend.app.agents.application.turns import delegates

        child = json.dumps({"datasetCandidates": {"lanes": {"external": rows, "catalog": catalog or []}}})
        _part, text, outcome = delegates._mint_candidates_from_delegate({}, child, listing or [])
        assert outcome == "ok", text
        return text

    def test_one_candidate_and_three_candidates(self, app):
        rows = [{"name": f"Portal {i}", "sourceType": "portal"} for i in range(3)]
        one, three = self._told(rows[:1]), self._told(rows)
        assert one.startswith("The user is shown 1 dataset candidate to choose from;"), one
        assert three.startswith("The user is shown 3 dataset candidates to choose from;"), three
        for text in (one, three):
            assert "(s)" not in text and "verdict" not in text and "runtime's" not in text, text
            assert "Curio checked each external source itself" in text, text

    def test_a_dropped_catalog_row_is_counted_in_words(self, app):
        catalog = [{"name": "Fake", "sourceType": "catalog", "datasetId": "ds-9"}]
        text = self._told([{"name": "Portal", "sourceType": "portal"}], catalog=catalog,
                          listing=[{"id": "ds-1", "name": "Real", "installed": True}])
        assert "Dropped 1 catalog row that the Data Catalog does not hold." in text, text
        assert "(s)" not in text, text


class TestAValidatedChart:
    """A chart or a map is a document the sandbox cannot run: it is checked
    against its grammar's schema, and what the chats say of it says so, never
    NOT-EXECUTABLE, which reads as a failure where nothing failed."""

    def test_its_build_says_it_was_validated_against_its_grammar(self, monkeypatch):
        from utk_curio.backend.app.agents.application.proposals import changes, mint
        from utk_curio.backend.app.agents.application.solve import validate
        from utk_curio.backend.app.agents.repositories import sessions

        said: list = []
        monkeypatch.setattr(sessions, "append_turns", lambda *args, **kwargs: said.append((args[3], args[4])))
        monkeypatch.setattr(mint, "_mint_node_content_write", lambda *args, **kwargs: (
            "applied", "", {"type": "change", "changeId": "c1", "tool": "node.content.write"}))
        monkeypatch.setattr(changes, "take_landed", lambda ctx: [])
        done = {"verdict": "not-executable", "rounds": 1, "nodeId": "map",
                "evidence": {"kind": "not-executable", "documentValidated": "vis-vega"},
                "attempts": [{"round": 1, "verdict": "not-executable", "kind": "not-executable"}]}
        builder = SimpleNamespace(coord="agent.curio.node-builder@1",
                                  manifest=SimpleNamespace(name="Node Builder", category="node"))
        # The round's line as the loop writes it (test_its_round_says_its_grammar_validated_it).
        list(validate._land_validated(
            "u1", "p1", "att-plan", "sess-plan", "att-map", "sess-map", "map", "Library branch map",
            '{"mark": "bar"}', done, 1, ["round 1: validated against its grammar"], resolution=builder,
        ))
        by_chat = {attachment: turns for attachment, turns in said}
        [home], [plan] = by_chat["att-map"], by_chat["att-plan"]
        assert home["text"] == "Validated 'Library branch map' against its grammar after 1 round, written into the node."
        assert plan["text"] == (
            "Validated 'Library branch map' against its grammar after 1 round: "
            "the trace and the change live in the node's Node Builder."
        )
        trace = next(p for p in home["content"] if p.get("type") == "card")
        assert trace["title"] == "Solve trace · VALIDATED against its grammar"
        assert trace["lines"][0] == "dependencies executed: 0 nodes"
        assert trace["lines"][-1] == "outcome: validated against its grammar after 1 round"
        [entry] = [p for p in plan["content"] if p.get("type") == "delegation"]
        assert entry["summary"] == "Validated 'Library branch map' against its grammar (1 round)"
        shown = [home["text"], plan["text"], trace["title"], *trace["lines"], entry["summary"]]
        assert not [text for text in shown if "executable" in text.lower()], shown

    def test_solve_this_node_says_so_on_its_card(self, client, user_and_token, tmp_curio, monkeypatch):
        from utk_curio.backend.tests.test_agents import test_verified_rounds as rounds_tests

        user, token = user_and_token
        helper = rounds_tests.TestSolveNode()
        ctx = helper._setup(client, user, token, monkeypatch, content='{"mark": "bar"}', node_type=rounds_tests.VEGA,
                            title="Library branch map")
        done = helper._solve_node(client, token, ctx)[-1][1]
        assert done["verdict"] == "not-executable" and done["rounds"] == 1
        turns = client.get(f"/api/agents/projects/{ctx['pid']}/attachments/{ctx['att']}/session",
                           headers=_auth(token)).get_json()["turns"]
        assert turns[-1]["text"].startswith("Validated 'Library branch map': its vis-vega document is valid")
        assert turns[-1]["content"][0]["title"] == "Solve · VALIDATED against its grammar after 1 round"
        # Its trail says the same, and nothing failed, so it has no attempts to fix.
        assert turns[-1]["content"][0]["lines"] == ["round 1 · validated against its grammar"]
        assert not [p for p in turns[-1]["content"] if p.get("type") == "solveAttempts"]

    def test_its_round_says_its_grammar_validated_it(self, app, tmp_curio):
        """The loop's own line for the round: the line the trace card shows
        under its VALIDATED title, with no reason the sandbox ran nothing."""
        from utk_curio.backend.tests.test_agents import test_document_validation as documents

        _events, outcome, _inputs = documents.TestTheWriteGateInTheLoop()._rounds(
            app, documents.VEGA, [documents.OWNERS_VEGA, documents.FIXED_VEGA],
        )
        assert outcome["verdict"] == "not-executable"
        assert outcome["roundsTrace"][-1] == "round 2: validated against its grammar", outcome["roundsTrace"]
        assert not [line for line in outcome["roundsTrace"] if "executable" in line], outcome["roundsTrace"]


class TestAnInputContractNamesItsSlots:
    """What a model is told of a node's inputs names each upstream node as its
    header names it, never by its goal cut in the middle of a word, and tells
    two of one name apart."""

    def test_each_slot_by_its_name_and_two_alike_by_a_short_id(self):
        from utk_curio.backend.app.agents.domain import input_contract, labels

        spec = {"dataflow": {
            "nodes": [
                {"id": "a1b2c3d4-tracts", "type": PY, "title": "Tracts", "goal": LONG_GOAL},
                {"id": "e5f6a7b8-heat", "type": PY, "goal": LONG_GOAL},
                {"id": "c9d0e1f2-heat", "type": PY, "goal": "the heat again"},
                {"id": "join", "type": PY, "title": "Join", "goal": "join them"},
            ],
            "edges": [
                {"id": "e0", "source": "a1b2c3d4-tracts", "target": "join", "targetHandle": "in"},
                {"id": "e1", "source": "e5f6a7b8-heat", "target": "join", "targetHandle": "in_1"},
                {"id": "e2", "source": "c9d0e1f2-heat", "target": "join", "targetHandle": "in_2"},
            ],
        }}
        shape = input_contract.arg_shape(spec, "join", templates={PY: "Python Computation"})
        names = ["Tracts", "Python Computation (e5f6a7b8)", "Python Computation (c9d0e1f2)"]
        assert [slot["label"] for slot in shape["slots"]] == names
        assert input_contract.describe(shape) == (
            "3 inputs, one per circle: [!! input_0 !!] = Tracts; "
            "[!! input_1 !!] = Python Computation (e5f6a7b8); [!! input_2 !!] = Python Computation (c9d0e1f2)"
        )
        refusal = input_contract.refusal_text(shape, {"name": "input_0", "attribute": "crs", "line": 2})
        assert all(f"[!! input_{i} !!] = {name}" in refusal for i, name in enumerate(names)), refusal
        # Each slot keeps its node's goal for a model to read: whole when it
        # fits, else cut on a word.
        assert [slot["goal"] for slot in shape["slots"]] == [
            labels.on_a_word(LONG_GOAL, 120), labels.on_a_word(LONG_GOAL, 120), "the heat again",
        ]


class TestWhereANotEnlistedPackagesDirNameIs:
    """A not-enlisted template's line in the roster holds two groups in
    parentheses, its label's and its package's. Each page that tells a model
    where a dirName is points at the one after 'package'."""

    POINTER = "follows 'package' in the parentheses that end its line"

    def test_the_line_and_each_page_that_points_into_it_agree(self):
        from utk_curio.backend.app.agents.application.turns import roster

        entry = {"id": "curio.notes/note-surface", "label": "Note", "description": "A note on the canvas."}
        line = roster._template_line(entry, suffix=" (package curio.notes@1)")
        assert line == "- curio.notes/note-surface (Note): A note on the canvas. (package curio.notes@1)"
        for page in ("skills/reuse-first/SKILL.md", "agents/agent.curio.builtin@1/messages.md",
                     "agents/agent.curio.builtin@1/tools.md"):
            pointing = [
                text for text in (REPO_ROOT / page).read_text(encoding="utf-8").splitlines()
                if "dirName" in text and "parentheses" in text
            ]
            assert pointing and all(self.POINTER in text for text in pointing), (page, pointing)
