"""An agent's code for a node is held to the references the node's run resolves.

A run writes a node's chips in before it sends its code
(``WorkflowSpec.node_code``, through ``code_references.resolve_references``)
and refuses each one it cannot resolve: a widget the node does not declare, a
scenario chip in code. Wherever an agent's code is written into a node, such
code is refused in the run's own words, so the agent is told:
``node.content.write``, which a delegated node's code lands through too
(whose agent that asked reads the refusal whole); ``node.create``, against
the widgets the new node starts with and the input circles its template has;
and a Solve that writes without running, for a planned node, against the
circles the plan's edges wire.

A chip the node's code holds already is the user's own, and an empty Data
widget waits for its data, as the editor draws it: neither is refused.

Every test imports what it tests inside itself, so a checkout without it
fails test by test rather than at collection.
"""
from __future__ import annotations

import json

from utk_curio.backend.tests._support.agent_routes import _auth
from utk_curio.backend.tests.test_agents.test_map_edits_grounding import (
    _landed_graph,
    _project,
    _refusals,
    _write_tail,
)
from utk_curio.backend.tests.test_agents.test_source_grounding_routes import (
    _attach,
    _changes,
    _create_tail,
    _delegate_tail,
    _install,
    _proposals,
    _run,
    _script,
    _tool_results,
)

NB = "agent.curio.node-builder@1"
DFB = "agent.curio.dataflow-builder@1"
DL = "curio.builtin/data-loading"
CA = "curio.builtin/python-computation"
#: A template whose node takes one input: its only circle is input_0.
SUMMARY = "curio.builtin/data-summary"

#: The widgets case of the live runs: column b multiplied by a factor, a
#: widget the node does not declare.
BY_A_FACTOR = "df = input_0.copy()\ndf['b'] = df['b'] * [!! factor !!]\nreturn df"
#: The scenarios case: Python code holding the scale a chart's spec takes.
SCENARIO_COLORS = "df = input_0.copy()\nstyle = {'color': [!! scenario colors !!]}\nreturn df"
FACTOR = {"name": "factor", "type": "number", "label": "Factor", "default": 2}
DATA = {"name": "data", "type": "dataset", "label": "Data", "default": ""}


def _dataflow(client, user, token, node: dict) -> str:
    """A dataflow of a loader wired into *node*, a Python node."""
    return _project(client, user, token, [
        {"id": "load", "type": DL, "content": "return 1\n", "x": 0, "y": 0},
        {"x": 700, "y": 0, **node},
    ], [{"id": "e", "source": "load", "target": node["id"], "sourceHandle": "out", "targetHandle": "in"}])


def _saved_spec(user, project) -> dict:
    from utk_curio.backend.app.projects import storage as projects_storage
    from utk_curio.backend.app.projects.services import _user_dir_key

    return projects_storage.read_spec(_user_dir_key(user), project)


def _saved_content(user, project, node_id) -> str:
    return next(n for n in _saved_spec(user, project)["dataflow"]["nodes"] if n["id"] == node_id).get("content") or ""


def _the_runs_words(user, project, node_id, code) -> list[str]:
    """What the node's run says of each reference in *code* it cannot
    resolve, over the saved dataflow (``WorkflowSpec.node_code``)."""
    from utk_curio.backend.app.execution.workflow_spec import parse_workflow_dict

    flow = parse_workflow_dict(_saved_spec(user, project))
    node = next(n for n in flow.nodes if n.id == node_id)
    _code, problems = flow.node_code_and_problems(node, "python", code)
    return [p["message"] for p in problems]


def _refusal_text(words: list[str]) -> str:
    """The refusal the mint hands the model for the run's *words*."""
    from utk_curio.backend.app.agents.domain import agent_text

    return agent_text.message("mint.content-references", problems="\n".join(words))


def _a_new_nodes_words(code: str, widgets=(), circles=(0,)) -> list[str]:
    """What a run says of each reference in *code* it cannot resolve, on a
    node that holds *widgets* with its input *circles* wired: the run's own
    function (``code_references.resolve_references``)."""
    from utk_curio.backend.app.execution.code_references import resolve_references

    _code, problems = resolve_references(code, list(widgets), "python", [{"slot": slot} for slot in circles])
    return [p["message"] for p in problems]


def _create_refusal_text(words: list[str]) -> str:
    """The refusal node.create's mint hands the model for the run's *words*."""
    from utk_curio.backend.app.agents.domain import agent_text

    return agent_text.message("mint.create-references", problems="\n".join(words))


def _attached_builder(client, token, project, node_id) -> str:
    _install(client, token, project, NB)
    return _attach(client, token, project, NB, target={"kind": "node", "targetId": node_id})


class TestCodeTheNodesRunRefusesIsNotWritten:
    """The live runs' two cases: the content landed, and the node's run then
    refused it, which the agent was never told."""

    def test_code_naming_a_widget_the_node_does_not_declare_is_refused_in_the_runs_words(
        self, client, user_and_token, tmp_curio, monkeypatch,
    ):
        user, token = user_and_token
        project = _dataflow(client, user, token, {"id": "mult", "type": CA, "content": "return input_0\n"})
        before = _saved_content(user, project, "mult")
        att = _attached_builder(client, token, project, "mult")
        calls = _script(monkeypatch, [_write_tail("mult", BY_A_FACTOR), "I could not write it."])
        body = _run(client, token, project, att, "multiply column b by a factor")
        assert not _changes(body) and not _proposals(body), "code its node's run refuses landed"
        assert _saved_content(user, project, "mult") == before
        words = _the_runs_words(user, project, "mult", BY_A_FACTOR)
        assert len(words) == 1 and "has no widget named factor" in words[0], words
        [refusal] = _refusals(calls, "node.content.write")
        assert _refusal_text(words) in refusal, refusal

    def test_python_code_holding_a_scenario_chip_is_refused_in_the_runs_words(
        self, client, user_and_token, tmp_curio, monkeypatch,
    ):
        user, token = user_and_token
        project = _dataflow(client, user, token, {"id": "styled", "type": CA, "content": "return input_0\n"})
        before = _saved_content(user, project, "styled")
        att = _attached_builder(client, token, project, "styled")
        calls = _script(monkeypatch, [_write_tail("styled", SCENARIO_COLORS), "I could not write it."])
        body = _run(client, token, project, att, "color the rows by scenario")
        assert not _changes(body) and not _proposals(body), "code its node's run refuses landed"
        assert _saved_content(user, project, "styled") == before
        words = _the_runs_words(user, project, "styled", SCENARIO_COLORS)
        assert len(words) == 1 and "is for a Vega-Lite or Autark spec, not for code" in words[0], words
        [refusal] = _refusals(calls, "node.content.write")
        assert _refusal_text(words) in refusal, refusal

    def test_a_delegates_code_naming_a_widget_the_node_does_not_declare_is_not_written(
        self, client, user_and_token, tmp_curio, monkeypatch,
    ):
        """As the live widgets case went: the Node Builder hands the node's
        code to node.content.generate, whose code the runtime writes through
        the same mint. The agent that asked is told why, in the run's words."""
        user, token = user_and_token
        project = _dataflow(client, user, token, {"id": "mult", "type": CA, "content": "return input_0\n"})
        before = _saved_content(user, project, "mult")
        att = _attached_builder(client, token, project, "mult")
        calls = _script(monkeypatch, [
            _delegate_tail("node.content.generate", {"nodeId": "mult", "intent": "multiply column b by a factor"}),
            BY_A_FACTOR,
            "The code could not be written.",
        ])
        body = _run(client, token, project, att, "multiply column b by a factor")
        assert _saved_content(user, project, "mult") == before, "a delegate's code its node's run refuses landed"
        assert not _changes(body) and not _proposals(body)
        words = _the_runs_words(user, project, "mult", BY_A_FACTOR)
        assert len(words) == 1 and "has no widget named factor" in words[0], words
        result = calls[2][-1]["content"]
        assert "could not be written into the node" in result and words[0] in result, result
        # Whole: what to do instead comes after the run's words.
        assert _refusal_text(words) in result, result


class TestCodeTheNodesRunResolvesIsWritten:
    """What a run resolves, and what is not the agent's code at fault, lands."""

    def test_code_naming_a_widget_the_node_declares_lands(self, client, user_and_token, tmp_curio, monkeypatch):
        user, token = user_and_token
        project = _dataflow(client, user, token, {
            "id": "mult", "type": CA, "content": "return input_0\n", "metadata": {"widgets": [dict(FACTOR)]},
        })
        att = _attached_builder(client, token, project, "mult")
        calls = _script(monkeypatch, [_write_tail("mult", BY_A_FACTOR), "Written."])
        body = _run(client, token, project, att, "multiply column b by the factor")
        assert len(_changes(body)) == 1, _tool_results(calls[-1], "node.content.write")
        assert _saved_content(user, project, "mult") == BY_A_FACTOR

    def test_a_chip_the_node_holds_already_is_the_users_own(self, client, user_and_token, tmp_curio, monkeypatch):
        """The user's code may name a widget the node does not declare yet: an
        agent's code that keeps that chip is not refused for it, however often
        it reads it."""
        user, token = user_and_token
        project = _dataflow(client, user, token, {"id": "mult", "type": CA, "content": "return input_0 * [!! factor !!]\n"})
        code = "scaled = input_0 * [!! factor !!]\nreturn scaled + [!! factor !!]"
        att = _attached_builder(client, token, project, "mult")
        calls = _script(monkeypatch, [_write_tail("mult", code), "Written."])
        body = _run(client, token, project, att, "add the factor once more")
        assert len(_changes(body)) == 1, _tool_results(calls[-1], "node.content.write")
        assert _saved_content(user, project, "mult") == code

    def test_code_reading_an_empty_data_widget_lands_where_the_node_held_none(
        self, client, user_and_token, tmp_curio, monkeypatch,
    ):
        """A planned Data Loading node holds its Data widget, empty, and no
        code. Code that loads what Data holds is the node's own starter: a run
        refuses it until a dataset is dropped, but the code is not at fault, as
        the editor draws its chip."""
        user, token = user_and_token
        project = _project(client, user, token, [
            {"id": "load", "type": DL, "content": "", "x": 0, "y": 0, "metadata": {"widgets": [dict(DATA)]}},
        ])
        # Code that read Data already would be the user's own, which passes on its own.
        assert _saved_content(user, project, "load") == "", "the planned loader holds code"
        code = "data = curio_load_data([!! data !!])\nreturn data"
        att = _attached_builder(client, token, project, "load")
        calls = _script(monkeypatch, [_write_tail("load", code), "Written."])
        body = _run(client, token, project, att, "load the dataset dropped on this node")
        assert len(_changes(body)) == 1, _tool_results(calls[-1], "node.content.write")
        assert _saved_content(user, project, "load") == code
        words = _the_runs_words(user, project, "load", code)
        assert len(words) == 1 and "drop a file or a Data Catalog dataset on Data first" in words[0], words


class TestANewNodesCodeIsHeldToItsRun:
    """node.create: a new node's chips are judged as its run resolves them once
    the node is wired, against the widgets the request declares and its
    template gives it, and the input circles its template has. The Node
    Builder never wires a node: the user, or a plan's edges, do."""

    def _create(self, client, user, token, monkeypatch, code, node_type=CA, **params):
        project = _project(client, user, token, [])
        _install(client, token, project, NB)
        att = _attach(client, token, project, NB)
        calls = _script(monkeypatch, [_create_tail(code, node_type=node_type, **params), "Done."])
        return calls, _run(client, token, project, att, "add a node for it")

    def test_code_naming_a_widget_the_new_node_does_not_declare_is_refused_in_the_runs_words(
        self, client, user_and_token, tmp_curio, monkeypatch,
    ):
        user, token = user_and_token
        code = "df = [!! input_0 !!]\nreturn df * [!! factor !!]"
        calls, body = self._create(client, user, token, monkeypatch, code)
        assert not _changes(body) and not _proposals(body), "a node whose run refuses its code was added"
        words = _a_new_nodes_words(code)
        assert len(words) == 1 and "has no widget named factor" in words[0], words
        [refusal] = _refusals(calls, "node.create")
        assert _create_refusal_text(words) in refusal, refusal

    def test_python_holding_a_scenario_chip_is_refused_in_the_runs_words(
        self, client, user_and_token, tmp_curio, monkeypatch,
    ):
        user, token = user_and_token
        calls, body = self._create(client, user, token, monkeypatch, SCENARIO_COLORS)
        assert not _changes(body) and not _proposals(body), "a node whose run refuses its code was added"
        words = _a_new_nodes_words(SCENARIO_COLORS)
        assert len(words) == 1 and "is for a Vega-Lite or Autark spec, not for code" in words[0], words
        [refusal] = _refusals(calls, "node.create")
        assert _create_refusal_text(words) in refusal, refusal

    def test_a_chip_of_a_circle_its_template_lacks_is_refused_in_the_runs_words(
        self, client, user_and_token, tmp_curio, monkeypatch,
    ):
        """A Data Summary node takes one input, so input_1 is no circle of it:
        no edge could ever reach it."""
        user, token = user_and_token
        code = "df = [!! input_0 !!]\nreturn df.merge([!! input_1 !!])"
        calls, body = self._create(client, user, token, monkeypatch, code, node_type=SUMMARY)
        assert not _changes(body) and not _proposals(body), "a node whose run refuses its code was added"
        words = _a_new_nodes_words(code)
        assert len(words) == 1 and "input_1 has no edge" in words[0], words
        [refusal] = _refusals(calls, "node.create")
        assert _create_refusal_text(words) in refusal, refusal

    def test_a_chip_of_a_circle_its_template_has_lands_unwired(self, client, user_and_token, tmp_curio, monkeypatch):
        """As the live runs' created nodes did: the code reads input_0, and the
        user connects it."""
        user, token = user_and_token
        code = "df = [!! input_0 !!]\nreturn df.describe()"
        calls, body = self._create(client, user, token, monkeypatch, code)
        assert [card["preview"] for card in _changes(body)] == [code], _tool_results(calls[-1], "node.create")

    def test_code_reading_a_widget_the_request_declares_lands(self, client, user_and_token, tmp_curio, monkeypatch):
        user, token = user_and_token
        code = "df = [!! input_0 !!]\nreturn df * [!! factor !!]"
        calls, body = self._create(client, user, token, monkeypatch, code, widgets=[dict(FACTOR)])
        assert [card["preview"] for card in _changes(body)] == [code], _tool_results(calls[-1], "node.create")

    def test_code_reading_its_templates_empty_data_widget_lands(self, client, user_and_token, tmp_curio, monkeypatch):
        """A Data Loading node starts with its template's Data widget, empty:
        code that loads what Data holds waits for its data."""
        user, token = user_and_token
        code = "data = curio_load_data([!! data !!])\nreturn data"
        calls, body = self._create(client, user, token, monkeypatch, code, node_type=DL)
        assert [card["preview"] for card in _changes(body)] == [code], _tool_results(calls[-1], "node.create")


class TestAPlannedNodesCodeWrittenWithoutRunning:
    """A plan carries no code (``plan.nodes-carry-content``): Solve writes each
    planned node's. A Solve that writes without running holds that code to the
    references the node's run resolves, against the node's own widgets and the
    circles the plan's edges wire, as a verified Solve's run does."""

    def _planned(self, client, user, token, monkeypatch, code) -> tuple[str, str, str]:
        """A loader wired into a Python node, as a plan lands them, whose code
        a content builder writes as *code*: the project, the plan's attachment
        and the Python node's id."""
        project = _project(client, user, token, [])
        plan = {
            "goal": "the buildings scaled by a factor",
            "nodes": [
                {"ref": "load", "nodeType": DL, "title": "Buildings", "intent": "synthetic sample buildings, by building_id"},
                {"ref": "scale", "nodeType": CA, "title": "Scaled", "intent": "the buildings scaled by a factor"},
            ],
            "edges": [{"from": "load", "to": "scale"}],
        }
        plan_tail = "Plan.\n```curio.v1\n" + json.dumps({"dataflowPlan": plan}) + "\n```"

        def _reply(calls):
            frame = calls[-1][-1]["content"]
            if "[delegated task" not in frame:
                return plan_tail
            if f'"nodeType": "{CA}"' in frame:
                return code
            return 'import pandas as pd\nreturn pd.DataFrame({"building_id": [1, 2]})'

        _install(client, token, project, DFB, NB)
        att = _attach(client, token, project, DFB)
        _script(monkeypatch, [_reply])
        graph = _landed_graph(_run(client, token, project, att, "plan the buildings scaled by a factor"))
        scale = next(n["id"] for n in graph["nodes"] if str(n.get("type", "")).startswith(CA))
        return project, att, scale

    def _solved_without_running(self, client, token, project, att, node_id) -> dict:
        body = client.post(
            f"/api/agents/projects/{project}/attachments/{att}/solve",
            json={"verify": False}, headers=_auth(token),
        ).get_json()
        return body["results"][node_id]

    def test_code_naming_a_widget_the_node_does_not_have_fails_it_in_the_runs_words(
        self, client, user_and_token, tmp_curio, monkeypatch,
    ):
        user, token = user_and_token
        code = "df = [!! input_0 !!]\nreturn df * [!! factor !!]"
        project, att, scale = self._planned(client, user, token, monkeypatch, code)
        result = self._solved_without_running(client, token, project, att, scale)
        assert result["status"] == "failed", result
        assert _saved_content(user, project, scale) == "", "code its node's run refuses was written"
        words = _the_runs_words(user, project, scale, code)
        assert len(words) == 1 and "has no widget named factor" in words[0], words
        assert words[0] in result["error"], result

    def test_code_reading_the_circle_the_plans_edge_wires_is_written(
        self, client, user_and_token, tmp_curio, monkeypatch,
    ):
        user, token = user_and_token
        code = "df = [!! input_0 !!]\nreturn df.describe()"
        project, att, scale = self._planned(client, user, token, monkeypatch, code)
        result = self._solved_without_running(client, token, project, att, scale)
        assert result["status"] == "solved", result
        assert _saved_content(user, project, scale) == code
