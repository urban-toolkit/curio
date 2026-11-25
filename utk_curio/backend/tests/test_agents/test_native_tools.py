"""Native tool calls: a run whose LLM configuration calls tools natively.

Such a run is offered its grants and its delegates as tools (``tools.native_tools``)
instead of the fenced ``toolRequest`` / ``delegateRequest`` syntax, and the
model's first call takes the path a fenced request takes: the same parser and
budgets, grant check, mint, delegate and round accounting. Its result goes back
as a tool message answering the call, flagged when it is an error. Every other
call of the reply is answered as not run, the last round offers no call unless
it is a plan's last try, as a fenced plan block has one, and an endpoint that
refuses the tools puts the run on the fenced protocol, from where it was. Runs go through the scripted provider, scripted to call tools
natively (``testing_provider.script_chat_capabilities``).
"""

from __future__ import annotations

import json

import pytest
import requests

from utk_curio.backend.app.agents.infrastructure import chat_capabilities
from utk_curio.backend.app.agents.infrastructure.egress import EgressRefused, EgressResult
from utk_curio.backend.app.agents.domain import agent_text, builtin, content
from utk_curio.backend.app.agents.repositories import model_catalog
from utk_curio.backend.app.agents.application import tool_rounds
from utk_curio.backend.app.agents.application.turns import titles
from utk_curio.backend.app.agents.infrastructure import providers
from utk_curio.backend.app.agents.infrastructure import testing_provider
from utk_curio.backend.app.agents.application import tools
from utk_curio.backend.app.agents.infrastructure.providers import (
    NativeToolsRefused,
    ProviderConfig,
)
from utk_curio.backend.tests._support import gemma4_vllm
from utk_curio.backend.tests._support.agent_routes import READER, _auth, _write_reader
from utk_curio.backend.tests.test_agents import test_document_proposals as document_proposals
from utk_curio.backend.tests.test_agents import test_plan_scenario_routes as scenario_routes
from utk_curio.backend.tests.test_agents import test_routes_proposals as routes_proposals

#: An agent that only chats and reads: the three read tools, no delegates.
#: No card is one, so a made-up one stands in (``_support.agent_routes``).
CHAT = READER


def _protocol(name: str) -> str:
    """A section of the base entry's ``protocol.md``, as a run reads it."""
    return agent_text.section(builtin.PROTOCOL_FILE, name)
NB = "agent.curio.node-builder@1"
DFB = "agent.curio.dataflow-builder@1"
DF = "agent.curio.dataset-finder@1"
CA = "curio.builtin/python-computation"
AUTK = "curio.builtin/autk-grammar"

TEMPLATES = [
    {
        "id": "python-computation", "label": "Python Computation",
        "category": "computation", "engine": "python", "editor": "code",
        "description": "Run python analysis code.",
        "inputPorts": [{"types": ["DATAFRAME"], "cardinality": "[1,n]"}],
        "outputPorts": [{"types": ["JSON"], "cardinality": "1"}],
    },
]

#: gemma4's whole reply in a run on native tools (the live skill evaluation,
#: widgets case 3): its delegation written as a fenced block, one closing brace short.
BROKEN_DELEGATION = (
    '```curio.v1\n{"delegateRequest": {"capability": "node.content.generate", "inputs": {"context": {"nodeId": '
    '"c8c48cdb-323d-4f80-ace9-7ac358277f90", "currentContent": "import pandas as pd\\r\\n\\r\\ndf = None\\r\\n'
    'mult = None\\r\\n\\r\\n# The dataframe and the multiplier, on the two input circles\\r\\n'
    'for item in (input_0, input_1):\\r\\n    if isinstance(item, pd.DataFrame):\\r\\n        df = item\\r\\n'
    "    elif isinstance(item, dict) and 'multiplier' in item:\\r\\n        mult = item['multiplier']\\r\\n\\r\\n"
    "# Defaults\\r\\nif df is None:\\r\\n    df = pd.DataFrame({'a': [], 'b': []})\\r\\nif mult is None:\\r\\n"
    "    mult = 1\\r\\n\\r\\ndf = df.copy()\\r\\nif 'b' in df.columns:\\r\\n"
    "    df['b'] = pd.to_numeric(df['b'], errors='coerce') * float(mult)\\r\\n\\r\\n"
    "df.metadata = {'name': 'Multiplied Numbers'}\\r\\nreturn df\\r\\n\"}, "
    "\"intent\": \"Modify the node to multiply column 'b' by 25 instead of using a multiplier from the input.\", "
    "\"nodeType\": \"curio.builtin/python-computation\"}}\n```"
)


@pytest.fixture()
def project(client, user_and_token):
    user, token = user_and_token
    from utk_curio.backend.app.projects.services import _user_dir_key

    routes_proposals.TestNodeCreate()._write_builtin_package(_user_dir_key(user), templates=TEMPLATES)
    _write_reader(user)
    body = {
        "name": "p",
        "spec": {"dataflow": {"nodes": [
            {"id": "n1", "type": CA, "goal": "count the rows", "content": "return 1", "x": 0, "y": 0},
        ], "edges": [], "packages": []}},
        "outputs": [],
    }
    resp = client.post("/api/projects", json=body, headers=_auth(token))
    assert resp.status_code == 201, resp.get_data(as_text=True)
    return resp.get_json()["id"]


@pytest.fixture()
def headers(client, user_and_token):
    """A scripted configuration as the default, calling tools natively."""
    testing_provider.reset()
    _, token = user_and_token
    h = _auth(token)
    created = client.post("/api/agents/llm/configs", headers=h, json={
        "label": "Scripted", "apiType": "testing", "model": "scripted"})
    assert created.status_code == 201, created.get_json()
    client.put("/api/agents/llm/default", headers=h, json={"configId": created.get_json()["config"]["id"]})
    testing_provider.script_chat_capabilities(tools=True)
    yield h
    testing_provider.reset()


def _attach(client, headers, pid, coord, target=None):
    client.post(f"/api/agents/projects/{pid}/install", json={"coord": coord}, headers=headers)
    resp = client.post(
        f"/api/agents/projects/{pid}/attachments",
        json={"coord": coord, "target": target or {"kind": "canvas"}}, headers=headers,
    )
    assert resp.status_code in (200, 201), resp.get_json()
    return resp.get_json()["attachmentId"]


def _run(client, headers, pid, att, message="go"):
    resp = client.post(
        f"/api/agents/projects/{pid}/attachments/{att}/run", json={"message": message}, headers=headers,
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)
    return resp.get_json()


def _stream(client, headers, pid, att, message="go") -> list[tuple[str, object]]:
    resp = client.post(
        f"/api/agents/projects/{pid}/attachments/{att}/run/stream", json={"message": message}, headers=headers,
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)
    events = []
    for block in resp.get_data(as_text=True).strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line)
        events.append((lines["event"], json.loads(lines["data"])))
    return events


def _last_turn(client, headers, pid, att) -> dict:
    turns = client.get(f"/api/agents/projects/{pid}/attachments/{att}/session", headers=headers).get_json()["turns"]
    return turns[-1]


def _run_calls() -> list[list]:
    """The captured message lists of the run's own calls, the title call left out."""
    return [
        messages for messages in testing_provider.captured()
        if not (messages and messages[0].get("content") == titles.title_prompt())
    ]


def _offered() -> list[dict]:
    return [o for o, messages in zip(testing_provider.offered(), testing_provider.captured())
            if not (messages and messages[0].get("content") == titles.title_prompt())]


def _call(name, arguments=None, call_id=None) -> dict:
    call = {"name": name, "arguments": arguments or {}}
    if call_id:
        call["id"] = call_id
    return call


class TestTheToolsOffered:
    def test_every_contract_is_offered_under_a_name_that_decodes_to_its_id(self):
        specs = tools.native_tools(list(tools.REGISTRY), ["node.content.generate"])
        assert [tools.tool_id_of(s["name"]) for s in specs[:-1]] == list(tools.REGISTRY)
        assert all("." not in s["name"] for s in specs)
        assert specs[-1]["name"] == tools.DELEGATE_TOOL and tools.tool_id_of(tools.DELEGATE_TOOL) is None
        assert tools.tool_id_of("node_read") is None and tools.tool_id_of(None) is None

    def test_each_schema_is_an_object_whose_required_keys_it_declares(self):
        def check(schema, where):
            if schema.get("type") == "object":
                properties = schema.get("properties") or {}
                assert set(schema.get("required") or ()) <= set(properties), where
                for key, value in properties.items():
                    check(value, f"{where}.{key}")
            if schema.get("type") == "array":
                check(schema["items"], f"{where}[]")

        for spec in tools.native_tools(list(tools.REGISTRY), ["node.content.generate"]):
            assert spec["parameters"]["type"] == "object", spec["name"]
            check(spec["parameters"], spec["name"])

    def test_descriptions_fit_the_length_openai_takes(self):
        for spec in tools.native_tools(list(tools.REGISTRY), ["node.content.generate"]):
            assert len(spec["description"]) <= 1024, spec["name"]

    def test_the_plan_tool_is_described_as_a_call_natively(self):
        (plan,) = tools.native_tools(["dataflow.plan.write"])
        assert "block" not in plan["description"] and "toolRequest" not in plan["description"]
        assert "dataflowPlan block" in tools.REGISTRY["dataflow.plan.write"].description

    def test_the_offered_schemas_are_copies(self):
        (spec,) = tools.native_tools(["web.fetch"])
        spec["parameters"]["properties"].clear()
        assert tools.REGISTRY["web.fetch"].parameters["properties"]

    def test_delegation_names_only_the_given_capabilities(self):
        (spec,) = tools.native_tools([], ["dataset.discover", "dataset.discover", "node.content.generate"])
        assert spec["parameters"]["properties"]["capability"]["enum"] == [
            "dataset.discover", "node.content.generate",
        ]
        assert tools.native_tools([], []) == []


class TestTheSystemTurn:
    def test_the_native_tail_drops_only_the_tool_list_and_its_syntax(self):
        grants = tools.grant_descriptions(["catalog.search", "discovery.search"])
        native = content.tail_instruction(grants, native_tools=True)
        fenced = content.tail_instruction(grants)
        assert native.startswith(content.tail_instruction())
        assert _protocol("native-tools") in native
        assert '"toolRequest"' in fenced and '"toolRequest"' not in native
        assert "- catalog.search:" in fenced and "- catalog.search:" not in native
        # The candidates block is no tool call, so both protocols keep its schema.
        assert _protocol("dataset-candidates") in native and _protocol("dataset-candidates-from-portals") in native

    def test_the_native_delegation_paragraph_names_the_delegate_tool(self):
        entries = [("node.content.generate", "Node Builder")]
        native = content.delegation_instruction(entries, native_tools=True)
        assert "node.content.generate" in native and "Node Builder" in native
        assert "delegate tool" in native and "delegateRequest" not in native
        assert "delegateRequest" in content.delegation_instruction(entries)

    def test_a_native_run_is_told_how_to_call(self, client, headers, project):
        att = _attach(client, headers, project, CHAT)
        testing_provider.push_reply("Hello.")
        _run(client, headers, project, att)
        (system, *_), = _run_calls()
        assert _protocol("native-tools") in system["content"]
        assert '"toolRequest"' not in system["content"]
        # It names no skills, so its chat lists every skill and loads one with skill.read.
        assert [s["kind"] for s in system["slots"]][:3] == ["preamble", "skill-catalog", "instruction"]
        assert _offered()[0] == {
            "tools": ["dataflow__read", "node__read", "node__runtime__read", "skill__read"], "toolChoice": "auto",
            "replySchema": None,
        }
        pins = _last_turn(client, headers, project, att)["execution"]["pins"]
        assert pins["toolProtocol"] == "native"

    def test_a_capability_check_that_fails_leaves_the_run_fenced(self, client, headers, project, monkeypatch):
        def _broken(config, user_key, **kwargs):
            raise OSError("the disk is full")

        monkeypatch.setattr(chat_capabilities, "chat_capabilities", _broken)
        att = _attach(client, headers, project, CHAT)
        testing_provider.push_reply("Hello.")
        assert _run(client, headers, project, att)["reply"] == "Hello."
        assert _offered()[0] == {"tools": [], "toolChoice": None, "replySchema": None}

    def test_a_fenced_run_is_unchanged(self, client, headers, project):
        testing_provider.script_chat_capabilities(tools=False)
        att = _attach(client, headers, project, CHAT)
        testing_provider.push_reply("Hello.")
        _run(client, headers, project, att)
        (system, *_), = _run_calls()
        assert '"toolRequest"' in system["content"]
        assert _protocol("native-tools") not in system["content"]
        assert _offered()[0] == {"tools": [], "toolChoice": None, "replySchema": None}
        pins = _last_turn(client, headers, project, att)["execution"]["pins"]
        assert pins["toolProtocol"] == "fenced"


class TestANativeCall:
    def test_the_call_runs_its_tool_and_the_result_answers_it(self, client, headers, project):
        att = _attach(client, headers, project, CHAT)
        testing_provider.push_replies(
            {"text": "Let me look.", "toolCalls": [_call("dataflow.read", call_id="c1")]},
            "There is one node.",
        )
        body = _run(client, headers, project, att)
        assert body["reply"] == "Let me look.\n\nThere is one node."
        _, second = _run_calls()
        call, result = second[-2:]
        assert call == {"role": "assistant", "content": "Let me look.",
                        "tool_calls": [{"id": "c1", "name": "dataflow__read", "arguments": {}}]}
        assert (result["role"], result["tool_call_id"], result["name"], result["is_error"]) == (
            "tool", "c1", "dataflow__read", False)
        assert json.loads(result["content"])["nodes"][0]["id"] == "n1"
        execution = _last_turn(client, headers, project, att)["execution"]
        assert [c["tool"] for c in execution["toolCalls"]] == ["dataflow.read"]

    def test_the_session_keeps_text_only(self, client, headers, project):
        att = _attach(client, headers, project, CHAT)
        testing_provider.push_replies({"toolCalls": [_call("dataflow.read")]}, "Done.")
        _run(client, headers, project, att)
        turns = client.get(f"/api/agents/projects/{project}/attachments/{att}/session",
                           headers=headers).get_json()["turns"]
        assert [t["text"] for t in turns] == ["go", "Done."]
        assert all("tool_calls" not in json.dumps(t) for t in turns)

    def test_only_the_first_call_of_a_reply_runs(self, client, headers, project):
        att = _attach(client, headers, project, CHAT)
        testing_provider.push_replies(
            {"toolCalls": [_call("dataflow.read", call_id="a"), _call("node.read", {"nodeId": "n1"}, "b")]},
            "Done.",
        )
        _run(client, headers, project, att)
        results = [m for m in _run_calls()[1] if m.get("role") == "tool"]
        assert [(r["tool_call_id"], r["is_error"]) for r in results] == [("a", False), ("b", True)]
        assert results[1]["content"].startswith("not run: one tool call per reply")
        execution = _last_turn(client, headers, project, att)["execution"]
        assert [c["tool"] for c in execution["toolCalls"]] == ["dataflow.read"]

    def test_an_ungranted_tool_is_refused_as_an_error(self, client, headers, project):
        att = _attach(client, headers, project, CHAT)
        testing_provider.push_replies({"toolCalls": [_call("web.fetch", {"url": "https://x.org"})]}, "Sorry.")
        _run(client, headers, project, att)
        result = _run_calls()[1][-1]
        assert result["is_error"] is True
        assert result["content"] == "refused: tool 'web.fetch' is not granted for this run"

    @pytest.mark.parametrize("call, expected", [
        (_call("no_such_tool"), "there is no tool named 'no_such_tool'"),
        (_call("delegate", {"capability": "Not An Id"}), "capability must be a capability id"),
        (_call("node.read", {"nodeId": "x" * 2000}), "toolRequest.params is"),
    ])
    def test_an_unreadable_call_gets_its_errors_back(self, client, headers, project, call, expected):
        att = _attach(client, headers, project, CHAT)
        testing_provider.push_replies({"toolCalls": [call]}, "Sorry.")
        _run(client, headers, project, att)
        result = _run_calls()[1][-1]
        assert result["is_error"] is True
        assert result["content"].startswith("invalid call, not run.") and expected in result["content"]
        assert "toolCalls" not in _last_turn(client, headers, project, att)["execution"]

    def test_the_last_round_offers_no_call(self, client, headers, project):
        att = _attach(client, headers, project, CHAT)
        testing_provider.push_replies(
            *[{"toolCalls": [_call("dataflow.read")]}] * tool_rounds.MAX_TOOL_ROUNDS, "Enough.",
        )
        body = _run(client, headers, project, att)
        assert body["reply"] == "Enough."
        assert [o["toolChoice"] for o in _offered()] == ["auto"] * tool_rounds.MAX_TOOL_ROUNDS + ["none"]
        last_result = _run_calls()[-1][-1]
        assert last_result["content"].endswith("\n" + agent_text.message("tool-round.final-round"))

    def test_a_fenced_block_in_a_native_run_is_answered_in_kind(self, client, headers, project):
        att = _attach(client, headers, project, CHAT)
        testing_provider.push_replies(
            '```curio.v1\n{"toolRequest": {"tool": "dataflow.read", "params": {}}}\n```', "Done.",
        )
        _run(client, headers, project, att)
        second = _run_calls()[1]
        assert second[-1]["role"] == "user"
        assert second[-1]["content"].startswith("[tool result] dataflow.read: ok")
        assert _offered()[1]["tools"], "the run stays on native tools"


class TestMutations:
    def test_a_native_create_call_lands_the_node(self, client, headers, project):
        att = _attach(client, headers, project, NB)
        testing_provider.push_replies(
            {"toolCalls": [_call("node.create", {"nodeType": CA, "content": "return 2", "title": "Two"})]},
            "Added a node.",
        )
        body = _run(client, headers, project, att)
        assert not [p for p in body["content"] if p["type"] == "proposal"]
        (change,) = [p for p in body["content"] if p["type"] == "change"]
        assert change["tool"] == "node.create"
        result = _run_calls()[1][-1]
        assert result["is_error"] is False and "is on the canvas" in result["content"], result["content"]

    def test_a_refused_create_call_is_an_error_the_model_can_fix(self, client, headers, project):
        att = _attach(client, headers, project, NB)
        testing_provider.push_replies(
            {"toolCalls": [_call("node.create", {"nodeType": CA})]},
            {"toolCalls": [_call("node.create", {"nodeType": CA, "content": "return 3"})]},
            "Added.",
        )
        body = _run(client, headers, project, att)
        refused = _run_calls()[1][-1]
        assert refused["is_error"] is True
        assert refused["content"] == "refused: params.content must be a non-empty string"
        assert [p["tool"] for p in body["content"] if p["type"] == "change"] == ["node.create"]

    def test_the_plan_is_a_call_whose_errors_come_back_as_its_result(self, client, headers, project):
        att = _attach(client, headers, project, DFB)
        plan = {"goal": "count twice", "nodes": [
            {"ref": "a", "nodeType": CA, "title": "Count", "intent": "count the rows again"}],
            "edges": [{"from": "n1", "to": "a"}]}
        testing_provider.push_replies(
            {"toolCalls": [_call("dataflow.plan.write", {**plan, "goal": ""})]},
            {"toolCalls": [_call("dataflow.plan.write", plan)]},
            "The plan is on the canvas.",
        )
        body = _run(client, headers, project, att)
        rejected = _run_calls()[1][-1]
        assert rejected["is_error"] is True and "goal" in rejected["content"]
        assert [p["tool"] for p in body["content"] if p["type"] == "change"] == ["dataflow.plan.write"]
        assert not [p for p in body["content"] if p["type"] == "proposal"]
        # The call's result says what landed and ends with the Topology verdict.
        landed = _run_calls()[2][-1]
        assert landed["is_error"] is False, landed
        assert "the plan added 1 node and 1 connection. Topology: acyclic." in landed["content"], landed["content"]
        assert _offered()[0]["tools"][1] == "dataflow__plan__write"


#: A plan whose scenario holds its one node, and the same plan breaking one of
#: the plan's own scenario rules, as 7 of gemma4's native plans did in #1282's
#: live check: a member that is neither a ref of the plan nor a node of the
#: dataflow. The plan's grammar takes it and the mint refuses it, on both
#: protocols with the same words.
RECOUNT = {"goal": "count twice", "nodes": [
    {"ref": "a", "nodeType": CA, "title": "Count", "intent": "count the rows again"}],
    "edges": [{"from": "n1", "to": "a"}], "scenarios": [{"name": "Recount", "nodes": ["a"]}]}
RECOUNT_BROKEN = {**RECOUNT, "scenarios": [{"name": "Recount", "nodes": ["a", "ghost"]}]}
GHOST = "'ghost' is neither a ref of this plan nor an existing node id"


def _too_big(plan: dict) -> dict:
    """*plan* past the plan's params budget: a call the runtime cannot read."""
    return {**plan, "goal": "g" * (content.PLAN_TAIL_MAX_BYTES + 1)}


class TestAPlansTries:
    """A plan gets as many tries on native tools as a fenced dataflowPlan
    block does: every refusal is a correction round while the MAX_TOOL_ROUNDS
    budget lasts, and the try after the last correction is judged as well. It
    lands, or the plan's card says why it could not, and no round follows it.
    Before, a native run's call after its third refusal offered no call, so a
    native plan had three tries where a block has four: in #1282's live check,
    gemma4's 7 refused native plans broke the plan's scenario rules and were
    not fixed within their rounds."""

    LAST = tool_rounds.MAX_TOOL_ROUNDS + 1  # a block's tries, each one call

    def _fenced(self, client, headers, plans) -> tuple[dict, list]:
        """*plans* as fenced blocks, one a reply, in a dataflow of their own:
        the turn's answer and its run's calls."""
        testing_provider.script_chat_capabilities(tools=False)
        pid = _new_dataflow(client, headers)
        att = _attach(client, headers, pid, DFB)
        before = len(_run_calls())
        testing_provider.push_replies(*[scenario_routes._reply(plan) for plan in plans], attachment=att)
        body = _run(client, headers, pid, att)
        testing_provider.script_chat_capabilities(tools=True)
        return body, _run_calls()[before:]

    def _native(self, client, headers, project, plans, stream=False, then=()):
        """*plans* as native calls of the plan tool, one a reply, then the
        replies *then*: the run's answer, then what each of its calls offered
        and the calls."""
        att = _attach(client, headers, project, DFB)
        self.att = att
        before = len(_run_calls())
        testing_provider.push_replies(
            *[{"toolCalls": [_call("dataflow.plan.write", plan)]} for plan in plans], *then, attachment=att)
        if stream:
            answer = _stream(client, headers, project, att)
        else:
            answer = client.post(f"/api/agents/projects/{project}/attachments/{att}/run",
                                 json={"message": "go"}, headers=headers)
        return answer, _offered()[before:], _run_calls()[before:]

    @staticmethod
    def _results(calls: list) -> list[str]:
        """What each tool result of the run told the model, as its last call holds them."""
        return [m["content"] for m in calls[-1] if m.get("role") == "tool"]

    def test_a_plan_refused_three_times_lands_on_its_fourth_try_as_a_fenced_block_does(
        self, client, headers, project,
    ):
        plans = [RECOUNT_BROKEN] * tool_rounds.MAX_TOOL_ROUNDS + [RECOUNT]
        fenced, fenced_calls = self._fenced(client, headers, plans)
        assert len(fenced_calls) == self.LAST
        resp, offered, calls = self._native(client, headers, project, plans)
        # The call after the third refusal still offers the plan's call.
        assert [o["toolChoice"] for o in offered] == ["auto"] * self.LAST, resp.get_data(as_text=True)
        assert resp.status_code == 200, resp.get_data(as_text=True)
        native = routes_proposals._landed_plan(resp.get_json())
        assert native["plan"] == routes_proposals._landed_plan(fenced)["plan"]
        assert len(calls) == self.LAST, "a round followed the plan's last try"
        refusals = self._results(calls)
        assert len(refusals) == tool_rounds.MAX_TOOL_ROUNDS and all(GHOST in r for r in refusals), refusals
        # The third refusal asks for the plan again, not for an answer.
        assert agent_text.message("tool-round.final-round") not in refusals[-1], refusals[-1]
        assert testing_provider.pending() == 0

    def test_a_plan_still_refused_on_its_last_try_ends_with_the_cap_card_as_a_fenced_block_does(
        self, client, headers, project,
    ):
        """Five invalid tries, one more than the budget takes: the fifth is
        never asked for, and the turn ends with the plan's cap card."""
        plans = [RECOUNT_BROKEN] * (self.LAST + 1)
        fenced, fenced_calls = self._fenced(client, headers, plans)
        assert len(fenced_calls) == self.LAST
        resp, offered, calls = self._native(client, headers, project, plans)
        assert [o["toolChoice"] for o in offered] == ["auto"] * self.LAST, resp.get_data(as_text=True)
        assert resp.status_code == 200, resp.get_data(as_text=True)
        body = resp.get_json()
        assert len(calls) == self.LAST, "a round followed the plan's last try"
        assert testing_provider.pending() == 2, "each run left its fifth try unasked"
        assert routes_proposals._changes(body) == routes_proposals._changes(fenced) == []
        (card,) = [p for p in body["content"] if p["type"] == "card"]
        assert card == next(p for p in fenced["content"] if p["type"] == "card")
        assert card["title"] == "Plan could not be made" and GHOST in card["lines"][0], card

    def test_another_call_on_the_plans_last_try_ends_with_the_cap_card(self, client, headers, project):
        """The last try is the plan's: a read the model calls in it instead,
        as the refusal's "dataflow.read shows them" invites, is dropped at the
        cap as on the fenced protocol, and the turn ends with the plan's card,
        not with nothing."""
        resp, offered, calls = self._native(
            client, headers, project, [RECOUNT_BROKEN] * tool_rounds.MAX_TOOL_ROUNDS,
            then=[{"text": "Let me read the node ids first.", "toolCalls": [_call("dataflow.read")]}],
        )
        assert [o["toolChoice"] for o in offered] == ["auto"] * self.LAST, resp.get_data(as_text=True)
        assert resp.status_code == 200, resp.get_data(as_text=True)
        body = resp.get_json()
        assert len(calls) == self.LAST, "a round followed the plan's last try"
        assert routes_proposals._changes(body) == []
        (card,) = [p for p in body["content"] if p["type"] == "card"]
        assert card["title"] == "Plan could not be made" and GHOST in card["lines"][0], card
        assert body["reply"] == "Let me read the node ids first."
        execution = _last_turn(client, headers, project, self.att)["execution"]
        assert [c["tool"] for c in execution["toolCalls"]] == ["dataflow.plan.write"] * tool_rounds.MAX_TOOL_ROUNDS

    def test_a_fenced_plan_request_gets_a_blocks_tries_too(self, client, headers, project):
        """The toolRequest form of a fenced plan (dev/55) takes the native
        call's path, so it gets the same tries: three refusals, then a valid
        request at the cap, which lands instead of being cut off."""
        testing_provider.script_chat_capabilities(tools=False)
        att = _attach(client, headers, project, DFB)
        before = len(_run_calls())
        testing_provider.push_replies(
            *[_block("dataflow.plan.write", RECOUNT_BROKEN)] * tool_rounds.MAX_TOOL_ROUNDS,
            _block("dataflow.plan.write", RECOUNT), attachment=att)
        body = _run(client, headers, project, att)
        assert [p["tool"] for p in routes_proposals._changes(body)] == ["dataflow.plan.write"], body["content"]
        calls = _run_calls()[before:]
        assert len(calls) == self.LAST, "a round followed the plan's last try"
        results = [m["content"] for m in calls[-1]
                   if m.get("role") == "user" and str(m.get("content")).startswith("[tool result]")]
        assert len(results) == tool_rounds.MAX_TOOL_ROUNDS and all(GHOST in r for r in results), results
        assert agent_text.message("tool-round.final-round") not in results[-1], results[-1]

    def test_a_streamed_plan_gets_the_same_tries(self, client, headers, project):
        plans = [RECOUNT_BROKEN] * tool_rounds.MAX_TOOL_ROUNDS + [RECOUNT]
        events, offered, calls = self._native(client, headers, project, plans, stream=True)
        assert [o["toolChoice"] for o in offered] == ["auto"] * self.LAST, events[-1]
        kind, done = events[-1]
        assert kind == "done", done
        assert [p["tool"] for p in done["content"] if p["type"] == "change"] == ["dataflow.plan.write"]
        assert len(calls) == self.LAST

    @pytest.mark.parametrize("last", ["readable", "unreadable"])
    def test_a_plan_call_too_big_to_read_gets_the_same_tries(self, client, headers, project, last):
        """A plan call the runtime cannot read is corrected as a broken plan
        block is, and its last try lands, or ends with the plan's cap card."""
        plans = [_too_big(RECOUNT)] * tool_rounds.MAX_TOOL_ROUNDS + [
            RECOUNT if last == "readable" else _too_big(RECOUNT)]
        resp, offered, calls = self._native(client, headers, project, plans)
        assert [o["toolChoice"] for o in offered] == ["auto"] * self.LAST, resp.get_data(as_text=True)[:2000]
        assert resp.status_code == 200, resp.get_data(as_text=True)[:2000]
        body = resp.get_json()
        assert len(calls) == self.LAST, "a round followed the plan's last try"
        corrections = self._results(calls)
        assert len(corrections) == tool_rounds.MAX_TOOL_ROUNDS
        assert all(c.startswith("invalid call, not run.") and "toolRequest.params is" in c for c in corrections)
        assert agent_text.message("tool-round.final-round") not in corrections[-1], corrections[-1]
        if last == "readable":
            assert [p["tool"] for p in routes_proposals._changes(body)] == ["dataflow.plan.write"]
        else:
            (card,) = [p for p in body["content"] if p["type"] == "card"]
            assert card["title"] == "Plan could not be made" and "toolRequest.params is" in card["lines"][0], card


class TestDelegation:
    def test_a_delegate_call_runs_the_delegate_and_its_result_answers_the_call(self, client, headers, project):
        att = _attach(client, headers, project, DF)
        testing_provider.route_by_intent({"suggest a next step": "Add a chart."})
        testing_provider.push_replies(
            {"toolCalls": [_call("delegate", {"capability": "workflow.suggest",
                                              "inputs": {"intent": "suggest a next step"}}, "d1")]},
            "Try a chart next.",
        )
        body = _run(client, headers, project, att)
        offered = _offered()[0]["tools"]
        assert offered[-1] == "delegate"
        system = _run_calls()[0][0]["content"]
        assert "call the delegate tool" in system and "delegateRequest" not in system
        result = next(m for m in _run_calls()[-1] if m.get("role") == "tool" and m["tool_call_id"] == "d1")
        assert result["is_error"] is False and "Add a chart." in result["content"]
        (entry,) = [p for p in body["content"] if p["type"] == "delegation"]
        assert entry["capability"] == "workflow.suggest" and entry["status"] == "ok"

    def test_a_capability_nobody_declares_is_refused(self, client, headers, project):
        att = _attach(client, headers, project, DF)
        testing_provider.push_replies(
            {"toolCalls": [_call("delegate", {"capability": "nothing.declares.this", "inputs": {}})]}, "Sorry.",
        )
        _run(client, headers, project, att)
        result = _run_calls()[1][-1]
        assert result["is_error"] is True
        assert result["content"] == (
            "refused: no delegate of this agent declares capability 'nothing.declares.this'")

    def test_a_delegation_block_a_brace_short_gets_a_correction_round_then_delegates(
        self, client, headers, project,
    ):
        """The block never reaches the user: as a broken tool request's block
        does (#245), it gets a correction round that names the broken JSON, and
        the corrected call delegates."""
        att = _attach(client, headers, project, NB)
        block = BROKEN_DELEGATION.split("\n", 1)[1].rsplit("\n", 1)[0]
        corrected = json.loads(block + "}")["delegateRequest"]
        testing_provider.route_by_intent({"multiply column 'b' by 25": "return input_0"})
        testing_provider.push_replies(
            BROKEN_DELEGATION,
            {"toolCalls": [_call("delegate", corrected, "d1")]},
            "The new node's code is written.",
        )
        body = _run(client, headers, project, att)
        assert "delegateRequest" not in body["reply"], body["reply"]
        correction = _run_calls()[1][-1]
        assert correction["role"] == "user", correction
        assert correction["content"].startswith("[tool validation]"), correction["content"]
        assert "not valid JSON" in correction["content"], correction["content"]
        (entry,) = [p for p in body["content"] if p["type"] == "delegation"]
        assert (entry["capability"], entry["status"]) == ("node.content.generate", "ok"), entry


class TestTheFallback:
    def test_a_refusal_of_the_tools_reruns_the_round_fenced(self, client, headers, project):
        att = _attach(client, headers, project, CHAT)
        testing_provider.push_replies(
            {"error": "this model does not support tools", "status": 400}, "A fenced answer.",
        )
        body = _run(client, headers, project, att)
        assert body["reply"] == "A fenced answer."
        offered = _offered()
        assert offered[0]["tools"] and offered[1] == {"tools": [], "toolChoice": None, "replySchema": None}
        retry_system = _run_calls()[1][0]["content"]
        assert '"toolRequest"' in retry_system and _protocol("native-tools") not in retry_system
        pins = _last_turn(client, headers, project, att)["execution"]["pins"]
        assert (pins["toolProtocol"], pins["nativeToolsRefused"]) == ("fenced", True)

    def test_a_refusal_mid_run_carries_the_conversation_over(self, client, headers, project):
        att = _attach(client, headers, project, CHAT)
        testing_provider.push_replies(
            {"text": "Reading.", "toolCalls": [_call("dataflow.read", call_id="c1")]},
            {"error": "tool results are not supported", "status": 400},
            "Done.",
        )
        body = _run(client, headers, project, att)
        assert body["reply"] == "Reading.\n\nDone."
        retried = _run_calls()[2]
        assert not any(m.get("role") == "tool" or m.get("tool_calls") for m in retried)
        request, result = retried[-2:]
        assert request["content"].startswith("Reading.\n\n```curio.v1\n")
        assert json.loads(request["content"].split("\n", 3)[3].rsplit("\n", 1)[0]) == {
            "toolRequest": {"tool": "dataflow.read", "params": {}}}
        assert result["content"].startswith("[tool result] dataflow.read: ok")

    def test_another_endpoint_error_is_a_run_error(self, client, headers, project):
        att = _attach(client, headers, project, CHAT)
        testing_provider.push_reply({"error": "the server is down", "status": 503})
        resp = client.post(f"/api/agents/projects/{project}/attachments/{att}/run",
                           json={"message": "go"}, headers=headers)
        assert resp.status_code == 502 and "the server is down" in resp.get_json()["error"]
        assert len(_run_calls()) == 1

    def test_the_refusal_is_remembered_once_the_fenced_call_succeeds(
        self, client, user_and_token, project, monkeypatch
    ):
        """On the suite's own endpoint (an OpenAI-compatible server the table
        does not know), after an earlier trial found it takes tools."""
        user, token = user_and_token
        h = _auth(token)
        from utk_curio.backend.app.projects.services import _user_dir_key

        key = _user_dir_key(user)
        endpoint = ("openai_compatible", "http://127.0.0.1:9/v1", "test-model")
        model_catalog.remember_chat_capabilities(key, *endpoint, {"tools": True, "reason": "asked before"})
        offered = []

        def _fake(config, messages, max_output_tokens=None, usage_out=None, **kwargs):
            if messages[0].get("content") == titles.title_prompt():
                return "Title"
            offered.append(bool(kwargs.get("tools")))
            if kwargs.get("tools"):
                raise NativeToolsRefused("tools are not supported for this model")
            return "Fenced."

        monkeypatch.setattr(providers, "run_chat_turn", _fake)
        att = _attach(client, h, project, CHAT)
        assert _run(client, h, project, att)["reply"] == "Fenced."
        assert offered == [True, False]
        remembered = model_catalog.remembered_chat_capabilities(key, *endpoint)
        assert remembered["tools"] is False and "tools are not supported" in remembered["reason"]
        # The next run starts fenced.
        _run(client, h, project, att)
        assert offered == [True, False, False]


class TestRecordingARefusal:
    def _cfg(self, **kw):
        base = dict(api_key="k", api_type="openai_compatible", base_url="http://localhost:11434/v1", model="m")
        base.update(kw)
        return ProviderConfig(**base)

    def test_only_an_endpoint_the_table_does_not_know_is_recorded(self, tmp_curio):
        chat_capabilities.record_native_refusal(self._cfg(), "7", "no tools")
        assert model_catalog.remembered_chat_capabilities(
            "7", "openai_compatible", "http://localhost:11434/v1", "m")["tools"] is False
        for config in (self._cfg(api_type="anthropic"), self._cfg(base_url="https://api.openai.com/v1"),
                       self._cfg(api_type="testing")):
            chat_capabilities.record_native_refusal(config, "7", "no tools")
            assert model_catalog.remembered_chat_capabilities(
                "7", config.api_type, config.base_url, config.model) is None


class TestStreaming:
    def test_a_native_call_streams_as_tool_events(self, client, headers, project):
        att = _attach(client, headers, project, CHAT)
        testing_provider.push_replies(
            {"text": "Let me look.", "toolCalls": [_call("dataflow.read", call_id="c1")]}, "One node.",
        )
        events = _stream(client, headers, project, att)
        kinds = [kind for kind, _ in events]
        assert kinds.index("tool_requested") < kinds.index("tool_started") < kinds.index("tool_result")
        assert dict(events)["tool_result"] == {"tool": "dataflow.read", "status": "ok"}
        deltas = "".join(data["text"] for kind, data in events if kind == "delta")
        assert deltas == "Let me look.One node."
        assert events[-1][1]["reply"] == "Let me look.\n\nOne node."
        result = _run_calls()[1][-1]
        assert (result["role"], result["tool_call_id"], result["is_error"]) == ("tool", "c1", False)

    def test_an_unreadable_call_streams_a_revision(self, client, headers, project):
        att = _attach(client, headers, project, CHAT)
        testing_provider.push_replies({"toolCalls": [_call("no_such_tool")]}, "Sorry.")
        events = _stream(client, headers, project, att)
        assert ("tool_revision", {"attempt": 1, "errors": 1}) in events

    def test_a_refusal_of_the_tools_reruns_the_round_fenced(self, client, headers, project):
        att = _attach(client, headers, project, CHAT)
        testing_provider.push_replies({"error": "no tools here", "status": 422}, "A fenced answer.")
        events = _stream(client, headers, project, att)
        assert events[-1][0] == "done" and events[-1][1]["reply"] == "A fenced answer."
        assert [bool(o["tools"]) for o in _offered()] == [True, False]
        pins = _last_turn(client, headers, project, att)["execution"]["pins"]
        assert pins["toolProtocol"] == "fenced" and pins["nativeToolsRefused"] is True

    def test_the_last_round_offers_no_call(self, client, headers, project):
        att = _attach(client, headers, project, CHAT)
        testing_provider.push_replies(
            *[{"toolCalls": [_call("dataflow.read")]}] * tool_rounds.MAX_TOOL_ROUNDS, "Enough.",
        )
        _stream(client, headers, project, att)
        assert [o["toolChoice"] for o in _offered()] == ["auto"] * tool_rounds.MAX_TOOL_ROUNDS + ["none"]


#: muse-glimmer's whole last reply in 83 of its turns in the 11-24 skill
#: evaluation (run 45341666171): its last round offered no call, so it wrote its
#: next call as text, in its own call syntax, and the chat showed that as the
#: reply. This one asks for node.read.
CALL_AS_TEXT = (
    "<|start|>assistant to=node__read<|message|><atem:function_calls>\n"
    '<atem:invoke name="node__read">\n'
    '<atem:parameter name="nodeId">n1</atem:parameter>\n'
    "</atem:invoke>\n"
    "</atem:function_calls>"
)
#: The same call from its header's ``to=`` on, as its other 35 such replies
#: wrote it, every one with nothing before it.
CALL_FROM_ITS_HEADER = CALL_AS_TEXT[len("<|start|>assistant"):]
#: Text before such a call, which none of those replies had: it stays the reply.
PROSE = "The node returns 1, so its output is one row."
#: A change written the same way.
CHANGE_AS_TEXT = (
    "<|start|>assistant to=node__content__write<|message|><atem:function_calls>\n"
    '<atem:invoke name="node__content__write">\n'
    '<atem:parameter name="nodeId">n1</atem:parameter>\n'
    '<atem:parameter name="content">return 2</atem:parameter>\n'
    "</atem:invoke>\n"
    "</atem:function_calls>"
)
#: A plan written the same way, on the plan's last try, which offers its call.
PLAN_AS_TEXT = (
    "<|start|>assistant to=dataflow__plan__write<|message|><atem:function_calls>\n"
    '<atem:invoke name="dataflow__plan__write">\n'
    '<atem:parameter name="goal">count twice</atem:parameter>\n'
    '<atem:parameter name="nodes">[{"ref": "a", "nodeType": "curio.builtin/python-computation", '
    '"title": "Count", "intent": "count the rows again"}]</atem:parameter>\n'
    '<atem:parameter name="edges">[{"from": "n1", "to": "a"}]</atem:parameter>\n'
    "</atem:invoke>\n"
    "</atem:function_calls>"
)
#: An answer that holds code, XML, HTML and a ``<`` but no call, ending in
#: text that could have begun one: it is left as it is.
ANSWER = (
    "The node keeps the rows where `a < b`:\n\n"
    "```python\nrows = df[df.a < df.b]  # see <b>bold</b>\n```\n\n"
    'Its output reads as <rows count="2"><row id="1"/></rows>, as <svg width="10"><rect/></svg> '
    'and as <function_calls><invoke name="node__read"/></function_calls>. '
    "In Elm `f <| g x` pipes, the crs to=EPSG:4326 stays, and as assistant to the team I write to=all"
)
#: The pin of a turn whose last round's call was asked once more with no
#: tools (``turn_loop.ASKED_AGAIN``): ``answered``, or ``failed: <status>``.
ASKED_AGAIN = "askedAgainWithoutTools"
#: What a call asked once more offers the model: no tools and no tool_choice.
NOTHING_OFFERED = {"tools": [], "toolChoice": None, "replySchema": None}
#: Each call's tool_choice in a turn whose reads use its tool rounds, whose
#: last round wrote a call as text, and whose call was asked once more.
CHOICES_ASKED_AGAIN = ["auto"] * tool_rounds.MAX_TOOL_ROUNDS + ["none", None]


def _message(message_id: str) -> str | None:
    """The message *message_id* of messages.md; None when the page has no
    such message, so a checkout without it fails at an assertion."""
    try:
        return agent_text.message(message_id)
    except agent_text.AgentTextError:
        return None


@pytest.fixture()
def one_character_deltas(monkeypatch):
    """A streamed turn's text one character a delta, as a model's server
    streams a reply token by token. The scripted provider sends a reply
    whole, in one delta, which no hold ever has to wait on."""
    whole = providers.stream_chat_turn

    def _one_character_at_a_time(*args, **kwargs):
        for event in whole(*args, **kwargs):
            if isinstance(event, str):
                yield from event
            else:
                yield event

    monkeypatch.setattr(providers, "stream_chat_turn", _one_character_at_a_time)


class TestACallWrittenAsText:
    """A run on native tools offers no call in its last round
    (``tool_choice`` none). muse-glimmer then wrote its next call as text, in
    its own call syntax (OpenAI's harmony format), and the chat showed that
    markup as the reply: 118 of its 486 replies in the 11-24 skill evaluation,
    and 122 of 480 on 11-17. Such a call is never run, and no delta, reply or
    saved turn, which later turns read, holds a piece of it. Dropped, it left
    38 of muse-glimmer's 54 live runs on 11-24 saying it used its tool rounds
    before it could answer, so its round's call is asked once more, with the
    same messages and no tools at all, and that reply answers after the text
    before the call; a change written as text still gets the cutoff card.
    Once a turn: a call written as text in that reply too is dropped as a
    request at the cap is, the reply keeping the text before it, and a reply
    left with no text says the agent used its tool rounds before it could
    answer, as does a turn whose call asked again fails. A last reply in
    prose, the plan's last try, which offers its call, and the fenced
    protocol, which offers no tools, are never asked again. Below the cap such
    a call is asked for again, as a request block the parser could not take
    is. An answer that holds code, XML or a ``<`` is left as it is."""

    def _ended(self, client, headers, project, att, path) -> tuple[dict, str | None]:
        """How the turn asked through *path* ended, the blocking answer's body
        or the stream's done, and the text its deltas streamed (None when it
        streamed none)."""
        if path == "run":
            return _run(client, headers, project, att), None
        events = _stream(client, headers, project, att)
        kind, done = events[-1]
        assert kind == "done", events[-1]
        return done, "".join(data["text"] for kind, data in events if kind == "delta")

    @pytest.mark.parametrize("path", ["run", "run/stream"])
    def test_a_call_written_as_text_again_when_asked_again_says_the_rounds_ran_out(
            self, client, headers, project, path):
        att = _attach(client, headers, project, CHAT)
        testing_provider.push_replies(
            *[{"toolCalls": [_call("dataflow.read")]}] * tool_rounds.MAX_TOOL_ROUNDS, CALL_AS_TEXT, CALL_AS_TEXT,
        )
        ended, _ = self._ended(client, headers, project, att, path)
        # Asked again once, and no call after it.
        assert [o["toolChoice"] for o in _offered()] == CHOICES_ASKED_AGAIN
        assert ended["reply"] == _message("turn.tool-rounds-used"), ended["reply"]
        assert not [p for p in ended["content"] if p["type"] == "card"], "a read cut off at the cap gets no card"
        saved = _last_turn(client, headers, project, att)
        assert saved["text"] == ended["reply"]
        assert [c["tool"] for c in saved["execution"]["toolCalls"]] == ["dataflow.read"] * tool_rounds.MAX_TOOL_ROUNDS
        assert saved["execution"]["pins"].get(ASKED_AGAIN) == "answered", saved["execution"]["pins"]

    @pytest.mark.parametrize("path", ["run", "run/stream"])
    def test_the_text_before_a_call_written_as_text_is_the_reply(self, client, headers, project, path):
        att = _attach(client, headers, project, CHAT)
        testing_provider.push_replies(
            *[{"toolCalls": [_call("dataflow.read")]}] * tool_rounds.MAX_TOOL_ROUNDS,
            f"{PROSE}\n{CALL_FROM_ITS_HEADER}", CALL_AS_TEXT,
        )
        ended, _ = self._ended(client, headers, project, att, path)
        assert [o["toolChoice"] for o in _offered()] == CHOICES_ASKED_AGAIN
        assert ended["reply"] == PROSE, ended["reply"]
        assert _last_turn(client, headers, project, att)["text"] == PROSE

    def test_a_change_written_as_text_at_the_cap_is_cut_off_with_its_card(
            self, client, user_and_token, headers, project):
        att = _attach(client, headers, project, NB)
        testing_provider.push_replies(
            *[{"toolCalls": [_call("dataflow.read")]}] * tool_rounds.MAX_TOOL_ROUNDS, CHANGE_AS_TEXT, CHANGE_AS_TEXT,
        )
        body = _run(client, headers, project, att)
        assert [o["toolChoice"] for o in _offered()] == CHOICES_ASKED_AGAIN
        cards = [p for p in body["content"] if p["type"] == "card"]
        assert [card["title"] for card in cards] == ["Request cut off"], body["content"]
        assert "node.content.write" in cards[0]["lines"][0], cards[0]
        assert body["reply"] == _message("turn.tool-rounds-used"), body["reply"]
        assert routes_proposals._changes(body) == []
        user, _ = user_and_token
        assert _saved_nodes(user, project)["n1"]["content"] == "return 1"

    def test_a_plan_written_as_text_on_its_last_try_is_never_run_and_its_card_says_why(
            self, client, headers, project):
        """The plan's last try offers its call, and a plan written as text
        there is no try: nothing runs it, and the plan's card says why the
        plan could not be made, as for any other request on that try."""
        tries = TestAPlansTries()
        resp, offered, calls = tries._native(
            client, headers, project, [RECOUNT_BROKEN] * tool_rounds.MAX_TOOL_ROUNDS, then=[PLAN_AS_TEXT],
        )
        assert [o["toolChoice"] for o in offered] == ["auto"] * tries.LAST, resp.get_data(as_text=True)
        body = resp.get_json()
        assert body["reply"] == _message("turn.tool-rounds-used"), body["reply"]
        cards = {p["title"]: p for p in body["content"] if p["type"] == "card"}
        assert sorted(cards) == ["Plan could not be made", "Request cut off"], body["content"]
        assert GHOST in cards["Plan could not be made"]["lines"][0], cards
        assert "dataflow.plan.write" in cards["Request cut off"]["lines"][0], cards
        assert routes_proposals._changes(body) == []
        assert len(calls) == tries.LAST, "a round followed the plan's last try"
        execution = _last_turn(client, headers, project, tries.att)["execution"]
        assert [c["tool"] for c in execution["toolCalls"]] == ["dataflow.plan.write"] * tool_rounds.MAX_TOOL_ROUNDS

    @pytest.mark.parametrize("path", ["run", "run/stream"])
    def test_an_answer_holding_code_xml_and_angle_brackets_is_left_as_it_is(
            self, client, headers, project, one_character_deltas, path):
        att = _attach(client, headers, project, CHAT)
        testing_provider.push_replies(
            *[{"toolCalls": [_call("dataflow.read")]}] * tool_rounds.MAX_TOOL_ROUNDS, ANSWER,
        )
        ended, streamed = self._ended(client, headers, project, att, path)
        assert ended["reply"] == ANSWER, ended["reply"]
        assert streamed in (None, ANSWER), streamed
        assert not [p for p in ended["content"] if p["type"] == "card"]
        assert _last_turn(client, headers, project, att)["text"] == ANSWER

    @pytest.mark.parametrize("last, again, shown", [
        (CALL_AS_TEXT, CALL_AS_TEXT, ""),
        (f"{PROSE}\n{CALL_FROM_ITS_HEADER}", CALL_AS_TEXT, PROSE),
        (CALL_AS_TEXT, f"{PROSE}\n{CALL_FROM_ITS_HEADER}", PROSE),
    ], ids=["only-the-call", "after-text", "after-text-when-asked-again"])
    def test_no_delta_streams_a_piece_of_a_call_written_as_text(
            self, client, headers, project, one_character_deltas, last, again, shown):
        att = _attach(client, headers, project, CHAT)
        testing_provider.push_replies(
            *[{"toolCalls": [_call("dataflow.read")]}] * tool_rounds.MAX_TOOL_ROUNDS, last, again,
        )
        ended, streamed = self._ended(client, headers, project, att, "run/stream")
        assert [o["toolChoice"] for o in _offered()] == CHOICES_ASKED_AGAIN
        for piece in ("<|", "to=", "node__read", "atem:"):
            assert piece not in streamed, f"{piece!r} streamed: {streamed!r}"
        assert streamed.strip() == shown, streamed
        assert ended["reply"] == (shown or _message("turn.tool-rounds-used")), ended["reply"]

    def test_a_call_written_as_text_below_the_cap_is_asked_for_again(
            self, client, headers, project, one_character_deltas):
        att = _attach(client, headers, project, CHAT)
        testing_provider.push_replies(
            CALL_AS_TEXT, {"toolCalls": [_call("node.read", {"nodeId": "n1"})]}, "It returns 1.",
        )
        events = _stream(client, headers, project, att)
        kind, done = events[-1]
        assert (kind, done.get("reply")) == ("done", "It returns 1."), events[-1]
        streamed = "".join(data["text"] for kind, data in events if kind == "delta")
        assert "<|" not in streamed and "atem:" not in streamed, streamed
        assert ("tool_revision", {"attempt": 1, "errors": 2}) in events
        calls = _run_calls()
        assert len(calls) == 3, calls
        called_as_text = _message("tool-round.call-as-text")
        assert called_as_text is not None and called_as_text in calls[1][-1]["content"], calls[1][-1]
        assert "<|" not in json.dumps(calls[1]) and "<|" not in json.dumps(calls[2])
        execution = _last_turn(client, headers, project, att)["execution"]
        assert [c["tool"] for c in execution["toolCalls"]] == ["node.read"]

    @pytest.mark.parametrize("path", ["run", "run/stream"])
    def test_a_last_reply_that_is_a_call_written_as_text_is_asked_again_with_no_tools_and_that_reply_answers(
            self, client, headers, project, one_character_deltas, path):
        att = _attach(client, headers, project, CHAT)
        testing_provider.push_replies(
            *[{"toolCalls": [_call("dataflow.read")]}] * tool_rounds.MAX_TOOL_ROUNDS, CALL_AS_TEXT, PROSE,
        )
        ended, streamed = self._ended(client, headers, project, att, path)
        offered = _offered()
        assert [o["toolChoice"] for o in offered] == CHOICES_ASKED_AGAIN
        assert offered[-2]["tools"] == offered[0]["tools"] and offered[-1] == NOTHING_OFFERED, offered[-2:]
        calls = _run_calls()
        # The same call once more: never the reply that wrote the call as text,
        # and no new text, the last round's own line ending it.
        assert calls[-1] == calls[-2], calls[-1][-1]
        assert calls[-1][-1]["content"].endswith("\n" + agent_text.message("tool-round.final-round"))
        assert ended["reply"] == PROSE, ended["reply"]
        assert streamed in (None, PROSE), streamed
        saved = _last_turn(client, headers, project, att)
        assert saved["text"] == PROSE
        assert saved["execution"]["pins"].get(ASKED_AGAIN) == "answered", saved["execution"]["pins"]

    @pytest.mark.parametrize("path", ["run", "run/stream"])
    def test_the_text_before_the_call_stays_and_the_reply_asked_again_answers_after_it(
            self, client, headers, project, path):
        att = _attach(client, headers, project, CHAT)
        testing_provider.push_replies(
            *[{"toolCalls": [_call("dataflow.read")]}] * tool_rounds.MAX_TOOL_ROUNDS,
            f"{PROSE}\n{CALL_FROM_ITS_HEADER}", "So its chart shows one bar.",
        )
        ended, _ = self._ended(client, headers, project, att, path)
        assert [o["toolChoice"] for o in _offered()] == CHOICES_ASKED_AGAIN
        assert ended["reply"] == f"{PROSE}\n\nSo its chart shows one bar.", ended["reply"]
        assert _last_turn(client, headers, project, att)["text"] == ended["reply"]

    def test_a_change_written_as_text_keeps_its_card_when_the_reply_asked_again_answers(
            self, client, user_and_token, headers, project):
        att = _attach(client, headers, project, NB)
        testing_provider.push_replies(
            *[{"toolCalls": [_call("dataflow.read")]}] * tool_rounds.MAX_TOOL_ROUNDS, CHANGE_AS_TEXT,
            "Its code should return 2.",
        )
        body = _run(client, headers, project, att)
        assert [o["toolChoice"] for o in _offered()] == CHOICES_ASKED_AGAIN
        assert body["reply"] == "Its code should return 2.", body["reply"]
        cards = [p for p in body["content"] if p["type"] == "card"]
        assert [card["title"] for card in cards] == ["Request cut off"], body["content"]
        assert "node.content.write" in cards[0]["lines"][0], cards[0]
        assert routes_proposals._changes(body) == []
        user, _ = user_and_token
        assert _saved_nodes(user, project)["n1"]["content"] == "return 1"

    @pytest.mark.parametrize("path", ["run", "run/stream"])
    def test_a_last_reply_in_prose_is_the_answer_and_nothing_is_asked_again(self, client, headers, project, path):
        att = _attach(client, headers, project, CHAT)
        testing_provider.push_replies(*[{"toolCalls": [_call("dataflow.read")]}] * tool_rounds.MAX_TOOL_ROUNDS, PROSE)
        ended, _ = self._ended(client, headers, project, att, path)
        offered = _offered()
        assert [o["toolChoice"] for o in offered] == ["auto"] * tool_rounds.MAX_TOOL_ROUNDS + ["none"]
        assert offered[-1]["tools"] == offered[0]["tools"], "the last round offers every tool, with no call"
        assert ended["reply"] == PROSE, ended["reply"]
        assert ASKED_AGAIN not in _last_turn(client, headers, project, att)["execution"]["pins"]

    @pytest.mark.parametrize("path", ["run", "run/stream"])
    def test_a_call_asked_again_that_fails_ends_the_turn_as_before(self, client, headers, project, path):
        """A provider may refuse a request that offers no tools while its
        history holds tool calls: the turn ends as it did before its call was
        asked again, never as an error, and nothing is asked after it."""
        att = _attach(client, headers, project, CHAT)
        testing_provider.push_replies(
            *[{"toolCalls": [_call("dataflow.read")]}] * tool_rounds.MAX_TOOL_ROUNDS, CALL_AS_TEXT,
            {"error": "the conversation holds tool calls but the request offers no tools", "status": 400},
        )
        ended, _ = self._ended(client, headers, project, att, path)
        assert [o["toolChoice"] for o in _offered()] == CHOICES_ASKED_AGAIN
        assert ended["reply"] == _message("turn.tool-rounds-used"), ended["reply"]
        saved = _last_turn(client, headers, project, att)
        assert saved["text"] == ended["reply"]
        assert saved["execution"]["status"] == "ok", saved["execution"]
        assert saved["execution"]["pins"].get(ASKED_AGAIN) == "failed: 400", saved["execution"]["pins"]

    def test_a_fenced_run_is_never_asked_again(self, client, headers, project):
        testing_provider.script_chat_capabilities(tools=False)
        att = _attach(client, headers, project, CHAT)
        read = '```curio.v1\n{"toolRequest": {"tool": "dataflow.read", "params": {}}}\n```'
        testing_provider.push_replies(*[read] * tool_rounds.MAX_TOOL_ROUNDS, CALL_AS_TEXT)
        body = _run(client, headers, project, att)
        assert _offered() == [NOTHING_OFFERED] * (tool_rounds.MAX_TOOL_ROUNDS + 1)
        assert body["reply"] == _message("turn.tool-rounds-used"), body["reply"]
        assert ASKED_AGAIN not in _last_turn(client, headers, project, att)["execution"]["pins"]


def _ask(client, headers, project, att, path) -> tuple[str, dict, str | None]:
    """The turn asked through *path*, whatever it ended with: its last
    event's kind and data, the blocking answer a ``done`` when it answered 200
    and an ``error`` otherwise, and the text its deltas streamed (None for the
    blocking answer)."""
    if path == "run":
        resp = client.post(f"/api/agents/projects/{project}/attachments/{att}/run",
                           json={"message": "go"}, headers=headers)
        return ("done" if resp.status_code == 200 else "error"), resp.get_json(silent=True) or {}, None
    events = _stream(client, headers, project, att)
    kind, data = events[-1]
    streamed = "".join(d["text"] for k, d in events if k == "delta")
    return kind, data if isinstance(data, dict) else {"error": data}, streamed


#: The Researcher, whose chat searches the web and reads pages.
RESEARCHER = "agent.curio.researcher@1"
#: Where web.search asks in these tests: a SearXNG that no request reaches,
#: since egress.fetch is the test's own (``web``).
SEARCH_URL = "https://search.example.test/search?q={q}&format=json"
#: What a search answers.
SEARCH_RESULTS = {"results": [{"title": "Chicago Region Trees Initiative", "url": "https://chicagorti.org",
                               "content": "Chicago has about 3.6 million trees."}]}
#: The two pages research-notes case 3 names.
PAGES = ("https://chicagorti.org", "https://en.wikipedia.org/wiki/Urban_forest")
#: A read of the dataflow, which spends a tool round.
READ = {"toolCalls": [_call("dataflow.read")]}


def _search(q: str = "Chicago tree canopy") -> dict:
    return {"toolCalls": [_call("web.search", {"q": q})]}


def _fetch(url: str = PAGES[0]) -> dict:
    return {"toolCalls": [_call("web.fetch", {"url": url})]}


def _answered(status: int, body: str, content_type: str = "application/json") -> EgressResult:
    """What a fetch of the test's web answers: *status* and *body*."""
    return EgressResult(url=PAGES[0], final_url=PAGES[0], status=status, content_type=content_type, body=body)


class _Web:
    """The web as ``egress.fetch`` reaches it in a test, with no socket: each
    fetch takes the next answer queued, a result or an exception it raises,
    and with none queued a search answers its rows and a page answers 200."""

    def __init__(self):
        self.answers: list = []
        self.asked: list[str] = []

    def fetch(self, url, **kwargs):
        self.asked.append(url)
        if self.answers:
            answer = self.answers.pop(0)
            if isinstance(answer, BaseException):
                raise answer
            return answer
        if url.startswith(SEARCH_URL.split("?")[0]):
            return EgressResult(url=url, final_url=url, status=200, content_type="application/json",
                                body=json.dumps(SEARCH_RESULTS))
        return EgressResult(url=url, final_url=url, status=200, content_type="text/html",
                            body="<html><body>Chicago has about 3.6 million trees.</body></html>")


@pytest.fixture()
def web(monkeypatch):
    """The test's web: web.search asks :data:`SEARCH_URL`, and every fetch
    is answered by a :class:`_Web`."""
    from utk_curio.backend.app.agents.infrastructure import egress

    monkeypatch.setenv("CURIO_SEARCH_URL", SEARCH_URL)
    fake = _Web()
    monkeypatch.setattr(egress, "fetch", fake.fetch)
    return fake


class TestWebReadsSpendNoRound:
    """A turn has MAX_TOOL_ROUNDS tool rounds (``tool_rounds``). In the
    SearXNG proving run 45671908088 (DeepSeek, the Researcher), research-notes
    case 3 called web.search, web.fetch and web.fetch, each of which worked,
    and the cap then left it no round to write its notes: 12 of research-notes'
    18 runs, and 15 of fact-checking's 18, reached the cap on their third web
    read. A web.search or web.fetch that worked spends no round, up to
    ``tool_rounds.FREE_WEB_READS`` a turn, the egress budget's own number, so
    every web read a turn may make is free while it works, and the turn's
    record counts them (``freeWebReads``). A web read that failed spends a
    round, as before: a search its provider answered with no results, or not
    with 200, a page that answered other than 200, the egress policy's
    refusal, a timeout, a provider it could not reach, so a dead provider
    cannot keep a turn going. A search with no query is a parameter refusal,
    free as any other up to MAX_REFUSED_ROUNDS a turn. Native calls and fenced
    blocks count alike, streamed or not."""

    @pytest.mark.parametrize("path", ["run", "run/stream"])
    def test_a_search_and_two_page_reads_that_work_spend_no_round(self, client, headers, project, web, path):
        att = _attach(client, headers, project, RESEARCHER)
        testing_provider.push_replies(
            _search(), _fetch(PAGES[0]), _fetch(PAGES[1]), *[READ] * tool_rounds.MAX_TOOL_ROUNDS, "Done.")
        kind, ended, _ = _ask(client, headers, project, att, path)
        choices = [o["toolChoice"] for o in _offered()]
        # The call after the three web reads still offers a call: they spent no round.
        assert choices == ["auto"] * (3 + tool_rounds.MAX_TOOL_ROUNDS) + ["none"], choices
        assert (kind, ended.get("reply")) == ("done", "Done."), ended
        execution = _last_turn(client, headers, project, att)["execution"]
        assert [(c["tool"], c["status"]) for c in execution["toolCalls"]] == [
            ("web.search", "ok"), ("web.fetch", "ok"), ("web.fetch", "ok"),
            *[("dataflow.read", "ok")] * tool_rounds.MAX_TOOL_ROUNDS], execution["toolCalls"]
        assert execution.get("freeWebReads") == 3, execution
        assert "refusedRounds" not in execution
        final = agent_text.message("tool-round.final-round")
        results = _native_results()
        assert [final in r for r in results] == [False] * (2 + tool_rounds.MAX_TOOL_ROUNDS) + [True], results
        assert len(web.asked) == 3, web.asked

    @pytest.mark.parametrize("path", ["run", "run/stream"])
    def test_fenced_web_reads_that_work_spend_no_round_either(self, client, headers, project, web, path):
        testing_provider.script_chat_capabilities(tools=False)
        att = _attach(client, headers, project, RESEARCHER)
        testing_provider.push_replies(
            _block("web.search", {"q": "Chicago tree canopy"}), _block("web.fetch", {"url": PAGES[0]}),
            _block("web.fetch", {"url": PAGES[1]}),
            *[_block("dataflow.read", {})] * tool_rounds.MAX_TOOL_ROUNDS, "Done.")
        kind, ended, _ = _ask(client, headers, project, att, path)
        calls = _run_calls()
        # Each request a call: the three web reads, the three rounds, and the answer.
        assert len(calls) == 3 + tool_rounds.MAX_TOOL_ROUNDS + 1, (len(calls), ended)
        assert (kind, ended.get("reply")) == ("done", "Done."), ended
        execution = _last_turn(client, headers, project, att)["execution"]
        assert [c["tool"] for c in execution["toolCalls"]] == [
            "web.search", "web.fetch", "web.fetch", *["dataflow.read"] * tool_rounds.MAX_TOOL_ROUNDS]
        assert execution.get("freeWebReads") == 3, execution
        assert execution["pins"]["toolProtocol"] == "fenced"

    @pytest.mark.parametrize("call, answer, status", [
        (_search(), _answered(202, ""), "error"),
        (_search(), _answered(503, '{"error": "unavailable"}'), "error"),
        (_search(), requests.exceptions.ConnectionError("connection refused"), "error"),
        (_fetch("http://127.0.0.1/data.json"), EgressRefused("host '127.0.0.1' is not a public address"), "error"),
        (_fetch(PAGES[0]), requests.exceptions.ReadTimeout("read timed out"), "error"),
        (_fetch(PAGES[0]), _answered(404, "<html>Not Found</html>", "text/html"), "ok"),
    ], ids=["search-202-empty", "search-503", "search-unreachable", "fetch-egress-refused", "fetch-timeout",
            "page-404"])
    def test_a_web_read_that_fails_spends_a_round(self, client, headers, project, web, call, answer, status):
        att = _attach(client, headers, project, RESEARCHER)
        web.answers.append(answer)
        testing_provider.push_replies(
            call, _fetch(PAGES[0]), _fetch(PAGES[1]), *[READ] * (tool_rounds.MAX_TOOL_ROUNDS - 1), "Done.")
        kind, ended, _ = _ask(client, headers, project, att, "run")
        choices = [o["toolChoice"] for o in _offered()]
        # The failed read spent the first round, and the two that worked none.
        assert choices == ["auto"] * (2 + tool_rounds.MAX_TOOL_ROUNDS) + ["none"], choices
        assert (kind, ended.get("reply")) == ("done", "Done."), ended
        execution = _last_turn(client, headers, project, att)["execution"]
        assert execution["toolCalls"][0]["status"] == status, execution["toolCalls"][0]
        assert execution.get("freeWebReads") == 2, execution

    def test_a_search_with_no_query_is_a_parameter_refusal(self, client, headers, project, web):
        att = _attach(client, headers, project, RESEARCHER)
        testing_provider.push_replies(
            {"toolCalls": [_call("web.search", {})]}, _search(), _fetch(PAGES[0]), _fetch(PAGES[1]),
            *[READ] * tool_rounds.MAX_TOOL_ROUNDS, "Done.")
        kind, ended, _ = _ask(client, headers, project, att, "run")
        choices = [o["toolChoice"] for o in _offered()]
        assert choices == ["auto"] * (4 + tool_rounds.MAX_TOOL_ROUNDS) + ["none"], choices
        assert (kind, ended.get("reply")) == ("done", "Done."), ended
        execution = _last_turn(client, headers, project, att)["execution"]
        first = execution["toolCalls"][0]
        assert (first["tool"], first["status"]) == ("web.search", "refused"), first
        assert (execution.get("refusedRounds"), execution.get("freeWebReads")) == (1, 3), execution
        assert _native_results()[0] == "refused: " + agent_text.message("tools.query-required")
        assert len(web.asked) == 3, "the search with no query asked its provider"

    def test_every_web_read_the_egress_budget_allows_is_free_and_one_past_it_spends_a_round(
            self, client, headers, project, web):
        from utk_curio.backend.app.common import egress_policy

        free = getattr(tool_rounds, "FREE_WEB_READS", None)
        assert free == egress_policy.MAX_CALLS_PER_RUN, (free, egress_policy.MAX_CALLS_PER_RUN)
        att = _attach(client, headers, project, RESEARCHER)
        testing_provider.push_replies(
            _search(), *[_fetch(f"https://example.org/page-{i}") for i in range(free)],
            *[READ] * (tool_rounds.MAX_TOOL_ROUNDS - 1), "Done.")
        kind, ended, _ = _ask(client, headers, project, att, "run")
        choices = [o["toolChoice"] for o in _offered()]
        # The web call past the budget is refused, and spends the first round.
        assert choices == ["auto"] * (free + tool_rounds.MAX_TOOL_ROUNDS) + ["none"], choices
        assert (kind, ended.get("reply")) == ("done", "Done."), ended
        execution = _last_turn(client, headers, project, att)["execution"]
        assert [c["status"] for c in execution["toolCalls"][:free + 1]] == ["ok"] * free + ["error"]
        assert execution.get("freeWebReads") == free, execution
        spent = agent_text.message("tool-round.egress-spent", calls=egress_policy.MAX_CALLS_PER_RUN)
        assert spent in _native_results()[free], _native_results()[free]
        assert len(web.asked) == free

    def test_a_web_read_past_the_free_ones_spends_a_round(self, client, headers, project, web, monkeypatch):
        monkeypatch.setattr(tool_rounds, "FREE_WEB_READS", 2, raising=False)
        att = _attach(client, headers, project, RESEARCHER)
        testing_provider.push_replies(
            _search(), _fetch(PAGES[0]), _fetch(PAGES[1]), *[READ] * (tool_rounds.MAX_TOOL_ROUNDS - 1), "Done.")
        kind, ended, _ = _ask(client, headers, project, att, "run")
        choices = [o["toolChoice"] for o in _offered()]
        # Two reads are free; the third worked too, and spent the first round.
        assert choices == ["auto"] * (2 + tool_rounds.MAX_TOOL_ROUNDS) + ["none"], choices
        assert (kind, ended.get("reply")) == ("done", "Done."), ended
        execution = _last_turn(client, headers, project, att)["execution"]
        assert [c["status"] for c in execution["toolCalls"]] == ["ok"] * (2 + tool_rounds.MAX_TOOL_ROUNDS)
        assert execution.get("freeWebReads") == 2, execution


#: Why a last round's call was asked again when its reply held no text, as
#: ``askedAgainWithoutTools`` says before how it went: no call either, or a
#: call the cap drops.
EMPTY_REPLY = "empty reply"
EMPTY_REPLY_WITH_A_CALL = "empty reply with a call"


@pytest.fixture()
def server_calls_whatever_is_offered(monkeypatch):
    """The scripted model's server sends the calls a reply makes even when
    the call offered the tools with no call (``tool_choice`` none), as a
    server that ignores ``tool_choice`` does."""
    scripted = testing_provider._scripted_turn
    monkeypatch.setattr(testing_provider, "_scripted_turn",
                        lambda reply, tools, tool_choice: scripted(reply, tools, "auto"))


class TestAnEmptyLastReply:
    """At the cap the last round offers the tools with no call (``tool_choice``
    none), and its reply is the turn's answer. That reply often held no text,
    and the chat showed an empty message: DeepSeek, Curio's default model on
    dev and stable, in 28 of 486 replies on 11-24 (run 45341666171), 26 of 486
    on 11-25 (45523145703) and 8 of 36 in the SearXNG proving run
    (45671908088), nearly every one two newlines, its thinking apart from
    them; gemma4 in 19 of 486 on 11-24, each with no text at all. Such a reply
    is asked once more, with the same messages and no tools, as a call written
    as text is (:class:`TestACallWrittenAsText`), once a turn whichever made
    it: a reply with no text and no call, or with no text beside a call the
    cap drops (a request block, or a call a server sends though the round
    offered none). The reply asked again answers; when it holds no text
    either, or its call fails, the reply says the agent used its tool rounds
    before it could answer. ``askedAgainWithoutTools`` says why and how it
    went. A last reply in prose is the answer as before, a plan's last try,
    which offers its call, and the fenced protocol, which offers no tools, are
    never asked again: there an empty last reply ends with the line."""

    @pytest.mark.parametrize("empty", ["", "\n\n"], ids=["no-text", "two-newlines"])
    @pytest.mark.parametrize("path", ["run", "run/stream"])
    def test_an_empty_last_reply_is_asked_again_with_no_tools_and_that_reply_answers(
            self, client, headers, project, path, empty):
        att = _attach(client, headers, project, CHAT)
        testing_provider.push_replies(*[READ] * tool_rounds.MAX_TOOL_ROUNDS, empty, PROSE)
        kind, ended, streamed = _ask(client, headers, project, att, path)
        offered = _offered()
        assert [o["toolChoice"] for o in offered] == CHOICES_ASKED_AGAIN, offered
        assert offered[-2]["tools"] == offered[0]["tools"] and offered[-1] == NOTHING_OFFERED, offered[-2:]
        calls = _run_calls()
        # The same call once more: never the empty reply, and no new text.
        assert calls[-1] == calls[-2], calls[-1][-1]
        assert (kind, ended.get("reply")) == ("done", PROSE), ended
        assert streamed is None or streamed.strip() == PROSE, streamed
        saved = _last_turn(client, headers, project, att)
        assert saved["text"] == PROSE
        assert saved["execution"]["pins"].get(ASKED_AGAIN) == f"{EMPTY_REPLY}, answered", saved["execution"]["pins"]

    @pytest.mark.parametrize("path", ["run", "run/stream"])
    def test_an_empty_reply_asked_again_and_empty_again_says_the_rounds_ran_out(self, client, headers, project, path):
        att = _attach(client, headers, project, CHAT)
        testing_provider.push_replies(*[READ] * tool_rounds.MAX_TOOL_ROUNDS, "\n\n", "")
        kind, ended, _ = _ask(client, headers, project, att, path)
        assert [o["toolChoice"] for o in _offered()] == CHOICES_ASKED_AGAIN
        assert (kind, ended.get("reply")) == ("done", _message("turn.tool-rounds-used")), ended
        assert not [p for p in ended.get("content") or [] if p["type"] == "card"], ended["content"]
        saved = _last_turn(client, headers, project, att)
        assert saved["text"] == ended["reply"]
        assert saved["execution"]["pins"].get(ASKED_AGAIN) == f"{EMPTY_REPLY}, empty again", saved["execution"]["pins"]

    @pytest.mark.parametrize("path", ["run", "run/stream"])
    def test_an_empty_reply_whose_call_asked_again_fails_ends_with_the_line(self, client, headers, project, path):
        att = _attach(client, headers, project, CHAT)
        testing_provider.push_replies(
            *[READ] * tool_rounds.MAX_TOOL_ROUNDS, "\n\n",
            {"error": "the conversation holds tool calls but the request offers no tools", "status": 400},
        )
        kind, ended, _ = _ask(client, headers, project, att, path)
        assert [o["toolChoice"] for o in _offered()] == CHOICES_ASKED_AGAIN
        assert (kind, ended.get("reply")) == ("done", _message("turn.tool-rounds-used")), ended
        saved = _last_turn(client, headers, project, att)
        assert saved["execution"]["status"] == "ok", saved["execution"]
        assert saved["execution"]["pins"].get(ASKED_AGAIN) == f"{EMPTY_REPLY}, failed: 400", saved["execution"]["pins"]

    def test_a_request_block_at_the_cap_with_no_text_is_asked_again_and_never_run(self, client, headers, project):
        att = _attach(client, headers, project, CHAT)
        testing_provider.push_replies(
            *[READ] * tool_rounds.MAX_TOOL_ROUNDS, "\n\n" + _block("node.read", {"nodeId": "n1"}), PROSE)
        kind, ended, _ = _ask(client, headers, project, att, "run")
        assert [o["toolChoice"] for o in _offered()] == CHOICES_ASKED_AGAIN
        assert (kind, ended.get("reply")) == ("done", PROSE), ended
        execution = _last_turn(client, headers, project, att)["execution"]
        assert [c["tool"] for c in execution["toolCalls"]] == ["dataflow.read"] * tool_rounds.MAX_TOOL_ROUNDS
        assert execution["pins"].get(ASKED_AGAIN) == f"{EMPTY_REPLY_WITH_A_CALL}, answered", execution["pins"]

    @pytest.mark.parametrize("path", ["run", "run/stream"])
    def test_a_call_the_server_sends_at_the_cap_with_no_text_is_asked_again_and_never_run(
            self, client, headers, project, server_calls_whatever_is_offered, path):
        att = _attach(client, headers, project, CHAT)
        testing_provider.push_replies(
            *[READ] * tool_rounds.MAX_TOOL_ROUNDS,
            {"text": "\n\n", "toolCalls": [_call("node.read", {"nodeId": "n1"})]}, PROSE)
        kind, ended, _ = _ask(client, headers, project, att, path)
        assert [o["toolChoice"] for o in _offered()] == CHOICES_ASKED_AGAIN
        assert (kind, ended.get("reply")) == ("done", PROSE), ended
        execution = _last_turn(client, headers, project, att)["execution"]
        assert [c["tool"] for c in execution["toolCalls"]] == ["dataflow.read"] * tool_rounds.MAX_TOOL_ROUNDS
        assert execution["pins"].get(ASKED_AGAIN) == f"{EMPTY_REPLY_WITH_A_CALL}, answered", execution["pins"]

    def test_prose_beside_a_call_the_server_sends_at_the_cap_is_the_answer_and_nothing_is_asked_again(
            self, client, headers, project, server_calls_whatever_is_offered):
        att = _attach(client, headers, project, CHAT)
        testing_provider.push_replies(
            *[READ] * tool_rounds.MAX_TOOL_ROUNDS, {"text": PROSE, "toolCalls": [_call("node.read", {"nodeId": "n1"})]})
        kind, ended, _ = _ask(client, headers, project, att, "run")
        assert [o["toolChoice"] for o in _offered()] == ["auto"] * tool_rounds.MAX_TOOL_ROUNDS + ["none"]
        assert (kind, ended.get("reply")) == ("done", PROSE), ended
        assert ASKED_AGAIN not in _last_turn(client, headers, project, att)["execution"]["pins"]

    @pytest.mark.parametrize("last, again, pinned", [
        (CALL_AS_TEXT, "\n\n", "answered"),
        ("\n\n", CALL_AS_TEXT, f"{EMPTY_REPLY}, empty again"),
    ], ids=["call-as-text-then-empty", "empty-then-call-as-text"])
    def test_one_call_a_turn_is_asked_again_whichever_reply_left_no_answer(
            self, client, headers, project, last, again, pinned):
        att = _attach(client, headers, project, CHAT)
        testing_provider.push_replies(*[READ] * tool_rounds.MAX_TOOL_ROUNDS, last, again, PROSE)
        kind, ended, _ = _ask(client, headers, project, att, "run")
        assert [o["toolChoice"] for o in _offered()] == CHOICES_ASKED_AGAIN
        assert (kind, ended.get("reply")) == ("done", _message("turn.tool-rounds-used")), ended
        assert testing_provider.pending() == 1, "a call was asked a third time"
        assert _last_turn(client, headers, project, att)["execution"]["pins"].get(ASKED_AGAIN) == pinned

    def test_a_fenced_run_whose_last_reply_is_empty_ends_with_the_line(self, client, headers, project):
        testing_provider.script_chat_capabilities(tools=False)
        att = _attach(client, headers, project, CHAT)
        testing_provider.push_replies(*[_block("dataflow.read", {})] * tool_rounds.MAX_TOOL_ROUNDS, "\n\n", PROSE)
        kind, ended, _ = _ask(client, headers, project, att, "run")
        assert _offered() == [NOTHING_OFFERED] * (tool_rounds.MAX_TOOL_ROUNDS + 1)
        assert (kind, ended.get("reply")) == ("done", _message("turn.tool-rounds-used")), ended
        assert ASKED_AGAIN not in _last_turn(client, headers, project, att)["execution"]["pins"]

    def test_an_empty_reply_on_a_plans_last_try_says_the_plan_could_not_be_made(self, client, headers, project):
        """The plan's last try offers its call, so it is never asked again:
        an empty reply there ends with the plan's card and the line."""
        tries = TestAPlansTries()
        resp, offered, calls = tries._native(
            client, headers, project, [RECOUNT_BROKEN] * tool_rounds.MAX_TOOL_ROUNDS, then=["\n\n", PROSE],
        )
        assert [o["toolChoice"] for o in offered] == ["auto"] * tries.LAST, resp.get_data(as_text=True)
        body = resp.get_json()
        assert body["reply"] == _message("turn.tool-rounds-used"), body["reply"]
        (card,) = [p for p in body["content"] if p["type"] == "card"]
        assert card["title"] == "Plan could not be made" and GHOST in card["lines"][0], card
        assert len(calls) == tries.LAST, "a round followed the plan's last try"


#: A number widget a Python node declares, with its default and its options.
SCALE = {"name": "scale", "type": "number", "label": "Scale", "default": 1,
         "options": {"min": 0.5, "max": 4, "step": 0.5}}


def _offered_schema(tool_id: str) -> dict:
    """The params schema a run on native tools is offered for *tool_id*."""
    (spec,) = tools.native_tools([tool_id])
    return spec["parameters"]


def _as_gemma4_calls(tool_id: str, arguments: dict) -> dict:
    """A native call of *tool_id* meant as *arguments*, as a vLLM server hands
    over the one Gemma 4 makes (``_support/gemma4_vllm``): each value the
    offered schema does not type is its text."""
    return _call(tool_id, gemma4_vllm.delivered(arguments, _offered_schema(tool_id)))


def _block(tool_id: str, params: dict) -> str:
    return "```curio.v1\n" + json.dumps({"toolRequest": {"tool": tool_id, "params": params}}) + "\n```"


def _new_dataflow(client, headers, nodes=None) -> str:
    """Another dataflow of the fixtures' user: the fixture's node, then *nodes*."""
    body = {"name": "q", "spec": {"dataflow": {"nodes": [
        {"id": "n1", "type": CA, "goal": "count the rows", "content": "return 1", "x": 0, "y": 0},
        *(nodes or []),
    ], "edges": [], "packages": []}}, "outputs": []}
    resp = client.post("/api/projects", json=body, headers=headers)
    assert resp.status_code == 201, resp.get_data(as_text=True)
    return resp.get_json()["id"]


def _saved_nodes(user, project) -> dict[str, dict]:
    from utk_curio.backend.app.projects import storage as projects_storage
    from utk_curio.backend.app.projects.services import _user_dir_key

    return {n["id"]: n for n in projects_storage.read_spec(_user_dir_key(user), project)["dataflow"]["nodes"]}


def _native_results() -> list[str]:
    """What each tool result told the model in the last run's calls."""
    return [m["content"] for m in _run_calls()[-1] if m.get("role") == "tool"]


class TestTypedValuesInANativeCall:
    """On 11-03 the owner's vLLM server ran gemma4 on native tools, and 11 of
    its 14 dataflow.plan.write calls were refused as invalid, while the fenced
    plans of the same case landed with their widget's default, options and
    duplicate's value. Gemma 4 writes a number bare in its own call syntax, and
    vLLM's parser for it keeps a bare value as its text, typing it only where
    the offered schema says what it is (``_support/gemma4_vllm``). The plan's
    schema typed none of a widget's values: its default and options were not
    in it, and a duplicate's values were an open object. So the scenarios
    case's factor of 2, its default of 1 and its options came as text, which
    the widget's own checks refuse ("must be a number", "Enter a number."),
    round after round.

    The schema now types each value it can (a widget's options) and gives the
    others, whose type is their widget's, as JSON text, read back as a fenced
    block is read (``tools.native_arguments``). Each call below is the one
    vLLM hands over for Gemma 4, and lands as its fenced block does, through
    the same reader."""

    def test_a_plan_with_a_widget_and_a_duplicates_value_lands_as_its_block_does(
        self, client, user_and_token, headers, project,
    ):
        user, _ = user_and_token
        # The plan route tests' scenarios case: a number widget with its
        # default and options, and a duplicate that sets it to 2.
        plan = scenario_routes._plan()
        factor = scenario_routes.FACTOR
        # Fenced, in a dataflow of its own.
        testing_provider.script_chat_capabilities(tools=False)
        fenced_project = _new_dataflow(client, headers)
        testing_provider.push_replies(scenario_routes._reply(plan))
        fenced = routes_proposals._landed_plan(
            _run(client, headers, fenced_project, _attach(client, headers, fenced_project, DFB)))
        # Native, as vLLM hands over Gemma 4's call.
        testing_provider.script_chat_capabilities(tools=True)
        testing_provider.push_replies(
            {"toolCalls": [_as_gemma4_calls("dataflow.plan.write", plan)]}, "The plan is on the canvas.",
        )
        body = _run(client, headers, project, _attach(client, headers, project, DFB))
        assert [p["tool"] for p in body["content"] if p["type"] == "change"] == ["dataflow.plan.write"], (
            _native_results())
        native = routes_proposals._landed_plan(body)
        assert native["summary"] == fenced["summary"] == "Plan · 4 nodes, 4 edges, 2 scenarios"
        assert native["plan"] == fenced["plan"]
        assert native["preview"] == fenced["preview"]
        # The dataflow holds the widget's numbers, the copy's value among them.
        saved = [n["metadata"]["widgets"] for n in _saved_nodes(user, project).values()
                 if (n.get("metadata") or {}).get("widgets")]
        assert sorted(saved, key=lambda widgets: "value" in widgets[0]) == [[factor], [{**factor, "value": 2}]]

    def test_a_created_nodes_widget_lands_as_its_block_does(self, client, user_and_token, headers, project):
        user, _ = user_and_token
        params = {"nodeType": CA, "content": "return input_0 * [!! scale !!]", "widgets": [dict(SCALE)]}
        testing_provider.script_chat_capabilities(tools=False)
        fenced_project = _new_dataflow(client, headers)
        testing_provider.push_replies(_block("node.create", params), "Added it.")
        _run(client, headers, fenced_project, _attach(client, headers, fenced_project, NB))
        testing_provider.script_chat_capabilities(tools=True)
        testing_provider.push_replies({"toolCalls": [_as_gemma4_calls("node.create", params)]}, "Added it.")
        body = _run(client, headers, project, _attach(client, headers, project, NB))
        assert [p["tool"] for p in body["content"] if p["type"] == "change"] == ["node.create"], _native_results()

        def created(where):
            (node,) = [n for n in _saved_nodes(user, where).values() if n["id"] != "n1"]
            return node["metadata"]

        assert created(project) == created(fenced_project) == {"widgets": [SCALE]}

    def test_a_widgets_value_in_a_created_node_lands_as_its_block_does(
        self, client, user_and_token, headers, project,
    ):
        """A widget's value, which a node.create gives a widget as a plan
        does, is JSON text in the schema as its default is, so the 3 Gemma 4
        writes bare reaches the widget's rule as the number it is."""
        user, _ = user_and_token
        params = {"nodeType": CA, "content": "return input_0 * [!! scale !!]", "widgets": [{**SCALE, "value": 3}]}
        testing_provider.script_chat_capabilities(tools=False)
        fenced_project = _new_dataflow(client, headers)
        testing_provider.push_replies(_block("node.create", params), "Added it.")
        _run(client, headers, fenced_project, _attach(client, headers, fenced_project, NB))
        testing_provider.script_chat_capabilities(tools=True)
        testing_provider.push_replies({"toolCalls": [_as_gemma4_calls("node.create", params)]}, "Added it.")
        body = _run(client, headers, project, _attach(client, headers, project, NB))
        assert [p["tool"] for p in body["content"] if p["type"] == "change"] == ["node.create"], _native_results()

        def created(where):
            (node,) = [n for n in _saved_nodes(user, where).values() if n["id"] != "n1"]
            return node["metadata"]

        assert created(project) == created(fenced_project) == {"widgets": [{**SCALE, "value": 3}]}

    def test_a_widgets_value_past_its_bounds_is_refused_by_the_widgets_rule(
        self, client, user_and_token, headers, project,
    ):
        params = {"nodeType": CA, "content": "return input_0 * [!! scale !!]", "widgets": [{**SCALE, "value": 9}]}
        testing_provider.push_replies({"toolCalls": [_as_gemma4_calls("node.create", params)]}, "I could not.")
        body = _run(client, headers, project, _attach(client, headers, project, NB))
        refused = _native_results()[0]
        assert refused.startswith("refused: ") and "params.widgets[0] ('scale'): Enter a number from 0.5 to 4." in (
            refused), refused
        assert not [p for p in body["content"] if p["type"] == "change"]

    def test_a_planned_widgets_value_lands_as_its_block_does(self, client, user_and_token, headers, project):
        user, _ = user_and_token
        plan = scenario_routes._plan(scenarios=None)
        plan["nodes"][1]["widgets"] = [{**scenario_routes.FACTOR, "value": 3}]
        testing_provider.script_chat_capabilities(tools=False)
        fenced_project = _new_dataflow(client, headers)
        testing_provider.push_replies(scenario_routes._reply(plan))
        fenced = routes_proposals._landed_plan(
            _run(client, headers, fenced_project, _attach(client, headers, fenced_project, DFB)))
        testing_provider.script_chat_capabilities(tools=True)
        testing_provider.push_replies(
            {"toolCalls": [_as_gemma4_calls("dataflow.plan.write", plan)]}, "The plan is on the canvas.",
        )
        body = _run(client, headers, project, _attach(client, headers, project, DFB))
        assert [p["tool"] for p in body["content"] if p["type"] == "change"] == ["dataflow.plan.write"], (
            _native_results())
        assert routes_proposals._landed_plan(body)["plan"] == fenced["plan"]
        saved = [n["metadata"]["widgets"] for n in _saved_nodes(user, project).values()
                 if (n.get("metadata") or {}).get("widgets")]
        assert saved == [[{**scenario_routes.FACTOR, "value": 3}]]

    def test_the_schema_offers_a_widgets_value_as_json_as_it_offers_its_default(self):
        plan = _offered_schema("dataflow.plan.write")["properties"]
        created = _offered_schema("node.create")["properties"]
        for widget in (plan["nodes"]["items"]["properties"]["widgets"]["items"], created["widgets"]["items"]):
            value, default = widget["properties"]["value"], widget["properties"]["default"]
            assert value.get("contentMediaType") == default.get("contentMediaType") == "application/json"
            assert value["type"] == default["type"] == "string"

    def test_a_widget_value_set_on_the_canvas_lands_as_its_block_does(
        self, client, user_and_token, headers, project,
    ):
        user, _ = user_and_token
        scaled = {"id": "scaled", "type": CA, "goal": "scale the rows", "content": "return input_0 * [!! scale !!]",
                  "x": 400, "y": 0, "metadata": {"widgets": [dict(SCALE)]}}
        params = {"nodeId": "scaled", "widgets": {"scale": 3}}
        testing_provider.script_chat_capabilities(tools=False)
        fenced_project = _new_dataflow(client, headers, [scaled])
        testing_provider.push_replies(_block("node.settings.write", params), "Changed it.")
        _run(client, headers, fenced_project, _attach(client, headers, fenced_project, NB))
        testing_provider.script_chat_capabilities(tools=True)
        native_project = _new_dataflow(client, headers, [scaled])
        testing_provider.push_replies({"toolCalls": [_as_gemma4_calls("node.settings.write", params)]}, "Changed it.")
        body = _run(client, headers, native_project, _attach(client, headers, native_project, NB))
        assert [p["tool"] for p in body["content"] if p["type"] == "change"] == ["node.settings.write"], (
            _native_results())
        assert (_saved_nodes(user, native_project)["scaled"]["metadata"]
                == _saved_nodes(user, fenced_project)["scaled"]["metadata"]
                == {"widgets": [{**SCALE, "value": 3}]})

    def test_a_text_that_is_no_json_is_still_a_text_and_judged_as_one(
        self, client, user_and_token, headers, project,
    ):
        """A text given as it is, with no JSON quotes, is still that text: the
        widget's own rule judges it, as it judges a fenced block's."""
        user, _ = user_and_token
        season = {"name": "season", "type": "choice", "default": "summer",
                  "options": {"choices": ["summer", "winter"]}}
        node = {"id": "season", "type": CA, "goal": "the season", "content": "return [!! season !!]",
                "x": 400, "y": 0, "metadata": {"widgets": [season]}}
        native_project = _new_dataflow(client, headers, [node])
        testing_provider.push_replies(
            {"toolCalls": [_as_gemma4_calls("node.settings.write", {"nodeId": "season", "widgets": {"season": "spring"}})]},
            {"toolCalls": [_as_gemma4_calls("node.settings.write", {"nodeId": "season", "widgets": {"season": "winter"}})]},
            "Changed it.",
        )
        body = _run(client, headers, native_project, _attach(client, headers, native_project, NB))
        refused = _native_results()[0]
        assert refused.startswith("refused: ") and (
            'params.widgets.season must be one of the season widget\'s choices: summer, winter; got "spring"'
        ) in refused, refused
        assert [p["tool"] for p in body["content"] if p["type"] == "change"] == ["node.settings.write"]
        assert _saved_nodes(user, native_project)["season"]["metadata"]["widgets"] == [{**season, "value": "winter"}]

    def test_the_schema_types_a_widget_as_the_trill_schema_does_and_gives_its_values_as_json(self):
        """Each value of a widget is typed where its type is fixed, as
        ``$defs.widget`` types it, and is JSON text where its type is its
        widget's: a default, a duplicate's values, a value set on the canvas."""
        from pathlib import Path

        trill = json.loads((Path(__file__).resolve().parents[4] / "docs" / "schemas" / "trill.v1.json")
                           .read_text(encoding="utf-8"))["$defs"]["widget"]["properties"]
        plan = _offered_schema("dataflow.plan.write")["properties"]
        created = _offered_schema("node.create")["properties"]
        # An option whose JSON type the trill schema does not fix, the
        # choices (a list, or the map of a dataset widget an input picks), is
        # JSON text, as a value is.
        loose = {key for key, value in trill["options"]["properties"].items() if isinstance(value["type"], list)}
        assert loose == {"choices"}
        for widget in (plan["nodes"]["items"]["properties"]["widgets"]["items"], created["widgets"]["items"]):
            options = (widget["properties"].get("options") or {}).get("properties") or {}
            assert {key: value.get("type") for key, value in options.items()} == {
                key: "string" if key in loose else value["type"]
                for key, value in trill["options"]["properties"].items()}
            assert all(options[key].get("contentMediaType") == "application/json" for key in loose)
            assert (widget["properties"].get("default") or {}).get("contentMediaType") == "application/json"
        values = plan["scenarios"]["items"]["properties"]["values"]
        assert values.get("additionalProperties", {}).get("additionalProperties", {}).get(
            "contentMediaType") == "application/json"
        settings = _offered_schema("node.settings.write")["properties"]["widgets"]
        assert settings["type"] == "object"
        assert settings.get("additionalProperties", {}).get("contentMediaType") == "application/json"


class TestARefusedCallsRecord:
    def test_the_record_keeps_the_whole_refusal_and_the_calls_arguments(
        self, client, headers, project,
    ):
        """A turn's record kept only a refusal's first line, so the 11-03 runs
        could not say why their plans were refused. A refused call's record now
        keeps the whole refusal and the params it gave, each bounded, with URL
        query strings cut as its reason has them; the chat's event still
        carries only the reason."""
        plan = {"goal": "", "nodes": [
            {"ref": "a", "nodeType": CA, "title": "Fetch https://example.org/rows?key=sk-live-0123456789",
             "intent": "", "content": "x" * 6000},
        ]}
        testing_provider.push_replies({"toolCalls": [_call("dataflow.plan.write", plan)]}, "I could not.")
        att = _attach(client, headers, project, DFB)
        events = _stream(client, headers, project, att)
        (record,) = _last_turn(client, headers, project, att)["execution"]["toolCalls"]
        assert (record["tool"], record["status"]) == ("dataflow.plan.write", "refused")
        assert record["reason"] == agent_text.message("mint.plan-params-invalid", listed="").strip()
        detail = record.get("detail") or ""
        assert "- goal must not be empty" in detail and "- nodes[0].intent must not be empty" in detail, record
        arguments = record.get("arguments") or ""
        assert arguments.startswith('{"goal": "", "nodes": [{"ref": "a"'), record
        assert "https://example.org/rows?…" in arguments and "sk-live-0123456789" not in arguments
        assert len(arguments) <= 4000 and arguments.endswith("…")
        (result,) = [data for kind, data in events if kind == "tool_result"]
        assert set(result) == {"tool", "status", "reason"}


def _written_as_offered(value, schema):
    """What a model that writes the schema it was offered writes for a value
    meant as *value*: each value the schema gives as JSON text
    (``contentMediaType`` application/json) as that text, every other value as
    it is. A text is the text the model wrote, as it is."""
    if not isinstance(schema, dict):
        return value
    if schema.get("contentMediaType") == tools.JSON_TEXT:
        return value if isinstance(value, str) else json.dumps(value)
    if isinstance(value, dict):
        properties = schema.get("properties") or {}
        others = schema.get("additionalProperties")
        return {key: _written_as_offered(item, properties.get(key, others)) for key, item in value.items()}
    if isinstance(value, list):
        return [_written_as_offered(item, schema.get("items")) for item in value]
    return value


def _as_gemma4_writes(name: str, arguments: dict, schema: dict) -> dict:
    """A native call of the tool offered as *name* with the params schema
    *schema*, meant as *arguments*: written as that schema asks, then handed
    over as a vLLM server hands over the call Gemma 4 makes
    (``_support/gemma4_vllm``)."""
    return _call(name, gemma4_vllm.delivered(_written_as_offered(arguments, schema), schema))


def _delegate_schema(capability: str) -> dict:
    """The params schema of the delegation tool, as a run that may delegate
    *capability* is offered it."""
    (spec,) = tools.native_tools([], [capability])
    return spec["parameters"]


def _delegated_inputs() -> list[dict]:
    """The inputs each delegated run of the test was handed, in call order: the
    JSON object after its task's frame (``delegation._frame_inputs``)."""
    handed = []
    for messages in testing_provider.captured():
        last = messages[-1] if messages else {}
        text = str(last.get("content") or "") if isinstance(last, dict) else ""
        if text.startswith("[delegated task from "):
            handed.append(json.JSONDecoder().raw_decode(text[text.index("{"):])[0])
    return handed


def _proposals(body: dict) -> list[dict]:
    """The run's proposal parts, each without the id it was minted with."""
    return [{key: value for key, value in part.items() if key != "proposalId"}
            for part in body["content"] if part["type"] == "proposal"]


def _open_objects(schema, where: str) -> list[str]:
    """The paths of the objects in *schema* that list no properties and whose
    values no schema types: no ``additionalProperties`` that ends in JSON text."""
    if not isinstance(schema, dict):
        return []
    found = []
    if schema.get("type") == "object" and not schema.get("properties"):
        leaf = schema
        while isinstance(leaf, dict) and leaf.get("type") == "object" and not leaf.get("properties"):
            leaf = leaf.get("additionalProperties")
        if not (isinstance(leaf, dict) and leaf.get("contentMediaType") == tools.JSON_TEXT):
            found.append(where)
    for key, value in (schema.get("properties") or {}).items():
        found += _open_objects(value, f"{where}.{key}")
    if isinstance(schema.get("items"), dict):
        found += _open_objects(schema["items"], f"{where}[]")
    return found


class TestOpenObjectsInANativeCall:
    """vLLM's parser for Gemma 4 keeps a bare number or true/false as its text
    and types a value only where the offered schema names its type
    (``_support/gemma4_vllm``). After #1282 two objects of the native tools
    still named none: a package draft's ``manifest`` and a delegation's
    ``inputs``, so every number and true/false in them reached Curio as text.
    A native draft's ``compatibility.major`` of 1 came as "1", which the build
    refuses, and a delegate was handed "2" and "true" where the fenced block's
    delegate is handed 2 and true.

    Both are now JSON text, read back as a fenced block is read
    (``tools.native_arguments``). Each call below is written as the schema it
    was offered asks, handed over as vLLM hands over Gemma 4's, and lands as
    its fenced block does. An object left open holds texts alone, which the
    parser keeps as written."""

    @pytest.fixture(autouse=True)
    def _fresh_build_jobs(self):
        from utk_curio.backend.app.packages.builder import jobs as build_jobs

        build_jobs.reset_registry()
        yield
        build_jobs.reset_registry()

    def test_a_package_draft_lands_as_its_block_does(self, client, headers, project):
        # The proposal tests' draft: its manifest's compatibility.major is 1,
        # and its template's hasCode, hasWidgets and hasGrammar are true/false.
        params = routes_proposals.TestPackageBuilderTools()._draft_params()
        # Fenced, in a dataflow of its own.
        testing_provider.script_chat_capabilities(tools=False)
        fenced_project = _new_dataflow(client, headers)
        testing_provider.push_replies(_block("package.draft.apply", params), "Proposed it.")
        fenced = _proposals(_run(client, headers, fenced_project, _attach(client, headers, fenced_project, NB)))
        assert [p["tool"] for p in fenced] == ["package.draft.apply"]
        # Native, written as the offered schema asks and handed over as vLLM hands over Gemma 4's call.
        testing_provider.script_chat_capabilities(tools=True)
        testing_provider.push_replies(
            {"toolCalls": [_as_gemma4_writes("package.draft.apply", params, _offered_schema("package.draft.apply"))]},
            "Proposed it.",
        )
        native = _proposals(_run(client, headers, project, _attach(client, headers, project, NB)))
        assert native == fenced, _native_results()

    def test_a_delegations_inputs_reach_the_delegate_as_its_blocks_do(self, client, headers, project):
        # Numbers, true/false, a list and an object of them, beside a text that
        # reads as a number, which stays a text.
        inputs = {"intent": "suggest a next step", "steps": 2, "chartsOnly": True, "zip": "60601",
                  "bounds": [-87.94, 41.64], "style": {"rank": 1.5, "pinned": False}}
        request = {"capability": "workflow.suggest", "inputs": inputs}
        testing_provider.route_by_intent({"suggest a next step": "Add a chart."})
        testing_provider.script_chat_capabilities(tools=False)
        fenced_project = _new_dataflow(client, headers)
        testing_provider.push_replies(
            "```curio.v1\n" + json.dumps({"delegateRequest": request}) + "\n```", "Try a chart next.",
        )
        _run(client, headers, fenced_project, _attach(client, headers, fenced_project, DF))
        testing_provider.script_chat_capabilities(tools=True)
        testing_provider.push_replies(
            {"toolCalls": [_as_gemma4_writes("delegate", request, _delegate_schema("workflow.suggest"))]},
            "Try a chart next.",
        )
        _run(client, headers, project, _attach(client, headers, project, DF))
        fenced, native = _delegated_inputs()
        assert native == fenced, _native_results()
        assert {key: native.get(key) for key in inputs} == inputs

    def test_a_text_that_is_no_json_is_still_a_text_and_refused_as_one(self, client, headers, project):
        """A text given as it is where JSON is asked, with no JSON in it, is
        still that text: the reader refuses it as it refuses a fenced block's
        inputs or manifest that is a text, and the model can fix the call."""
        schema = _delegate_schema("workflow.suggest")
        testing_provider.route_by_intent({"suggest a next step": "Add a chart."})
        testing_provider.push_replies(
            {"toolCalls": [_as_gemma4_writes(
                "delegate", {"capability": "workflow.suggest", "inputs": "suggest a next step"}, schema)]},
            {"toolCalls": [_as_gemma4_writes(
                "delegate", {"capability": "workflow.suggest", "inputs": {"intent": "suggest a next step"}}, schema)]},
            "Try a chart next.",
        )
        body = _run(client, headers, project, _attach(client, headers, project, DF))
        refused = _run_calls()[1][-1]["content"]
        assert refused.startswith("invalid call, not run.") and (
            agent_text.message("request.delegate-inputs-not-object") in refused), refused
        assert [(p["capability"], p["status"]) for p in body["content"] if p["type"] == "delegation"] == [
            ("workflow.suggest", "ok")]

        draft_project = _new_dataflow(client, headers)
        params = {**routes_proposals.TestPackageBuilderTools()._draft_params(), "manifest": "a notes package"}
        testing_provider.push_replies(
            {"toolCalls": [_as_gemma4_writes("package.draft.apply", params, _offered_schema("package.draft.apply"))]},
            "I could not.",
        )
        _run(client, headers, draft_project, _attach(client, headers, draft_project, NB))
        assert _native_results()[0] == "refused: " + agent_text.message(
            "mint.draft-request-invalid", exc="manifest is required and must be an object")

    def test_every_object_a_native_call_leaves_open_holds_texts_alone(self):
        """vLLM's parser for Gemma 4 types no value of an object whose schema
        lists no properties. So each object a native tool leaves open holds
        texts alone, which the parser keeps as written, and its reader refuses
        any other value: a draft's files and dependencies, a duplicate's
        copies. An object whose values can be anything is JSON text."""
        specs = tools.native_tools(list(tools.REGISTRY), ["workflow.suggest"])
        found = sorted(path for spec in specs for key, value in spec["parameters"]["properties"].items()
                       for path in _open_objects(value, f"{spec['name']}.{key}"))
        assert found == [
            "dataflow__plan__write.scenarios[].copies",
            "package__draft__apply.dependencies",
            "package__draft__apply.files",
        ]
        manifest = _offered_schema("package.draft.apply")["properties"]["manifest"]
        inputs = _delegate_schema("workflow.suggest")["properties"]["inputs"]
        assert (manifest["type"], manifest.get("contentMediaType")) == ("string", "application/json")
        assert (inputs["type"], inputs.get("contentMediaType")) == ("string", "application/json")
        # Their readers take texts alone.
        from utk_curio.backend.app.packages.builder import models as build_models

        request = routes_proposals.TestPackageBuilderTools()._draft_params()
        request.pop("justification")
        for changed, refusal in (
            ({"files": {"starters/note-kind/Default.py": {"text": 1}}}, "text must be a string"),
            ({"dependencies": {"python": {"pandas": 2}}}, "constraint must be a non-empty bounded string"),
        ):
            with pytest.raises(build_models.BuildRequestError, match=refusal):
                build_models.parse_build_request({**request, **changed})
        plan = scenario_routes._plan()
        plan["scenarios"][1]["copies"] = {"shadows": 7}
        assert content.parse_dataflow_plan_verbose(plan)[1] == [
            agent_text.message("plan.field-not-string", where="scenarios[1].copies.shadows")]


#: The Autark document muse-glimmer sent as a JSON object in the Skill
#: evaluations pilot of 11-05 (CI run 41953187658): a histogram of the
#: buildings' heights that a person can brush.
HISTOGRAM = {"plot": {
    "dataRef": "table_osm_buildings", "mark": "bar", "axis": ["height", "@transform"],
    "title": "Building heights histogram",
    "transform": {"preset": "binning-1d", "options": {"bins": 20}}, "events": ["brushX"],
}}
#: What a call that gives a code node a JSON object as its content is told.
CODE_GIVEN_AN_OBJECT = (
    "refused: params.content is a JSON object, but a Python Computation node holds python code: "
    "send the code itself in params.content, as one string. Only a chart's or a map's node takes "
    "a JSON document as its content."
)


class TestADocumentGivenAsAnObject:
    """muse-glimmer's native calls in the Skill evaluations pilot of 11-05 (CI
    run 41953187658): node.create of an Autark node with its content written
    as a JSON object, not as that object's text. Curio refused the call as no
    string, the model sent the same object again and was refused again, then
    wrote the call's markup as its reply: 24 of its 57 calls were refused so.

    A node that holds a JSON document, a chart's or a map's, takes its
    document as the object it is: it lands as the document's JSON text, which
    the document check judges as it judges that text. A code node still
    refuses one, and says what to send. node.create, node.content.write and a
    plan read the same object the same way."""

    def _dataflow(self, client, user, headers, nodes=None) -> str:
        """A dataflow of the user's whose templates are a code node, a chart
        and a map (``test_document_proposals``)."""
        from utk_curio.backend.app.projects.services import _user_dir_key

        routes_proposals.TestNodeCreate()._write_builtin_package(
            _user_dir_key(user), templates=document_proposals.TEMPLATES)
        return _new_dataflow(client, headers, nodes)

    def test_a_map_given_as_an_object_lands_as_its_json_text(self, client, user_and_token, headers):
        user, _ = user_and_token
        pid = self._dataflow(client, user, headers)
        testing_provider.push_replies(
            {"toolCalls": [_call("node.create", {
                "nodeType": AUTK, "content": HISTOGRAM, "title": "Building heights histogram",
                "goal": "A histogram of the buildings' heights that a person can brush."})]},
            "Added the histogram.",
        )
        body = _run(client, headers, pid, _attach(client, headers, pid, NB))
        (result,) = _native_results()
        assert "must be a non-empty string" not in result, result
        assert "is on the canvas" in result, result
        assert [p["tool"] for p in body["content"] if p["type"] == "change"] == ["node.create"]
        (created,) = [n for n in _saved_nodes(user, pid).values() if n["id"] != "n1"]
        assert created["type"] == AUTK
        assert created["content"] == json.dumps(HISTOGRAM, indent=2, ensure_ascii=False)
        assert json.loads(created["content"]) == HISTOGRAM

    def test_a_code_node_given_an_object_is_refused_with_what_to_send(self, client, user_and_token, headers):
        user, _ = user_and_token
        pid = self._dataflow(client, user, headers)
        testing_provider.push_replies(
            {"toolCalls": [_call("node.create", {"nodeType": CA, "content": {"rows": 3}, "title": "Rows"})]},
            "I could not add it.",
        )
        body = _run(client, headers, pid, _attach(client, headers, pid, NB))
        (refused,) = [m for m in _run_calls()[-1] if m.get("role") == "tool"]
        assert refused["is_error"] is True
        assert "must be a non-empty string" not in refused["content"], refused["content"]
        assert refused["content"] == CODE_GIVEN_AN_OBJECT
        # No dict literal became the node's code: no node landed at all.
        assert not [p for p in body["content"] if p["type"] == "change"]
        assert list(_saved_nodes(user, pid)) == ["n1"]

    def test_a_content_write_reads_the_object_as_a_create_does(self, client, user_and_token, headers):
        user, _ = user_and_token
        heights = {"id": "heights", "type": AUTK, "goal": "the buildings' heights", "content": "",
                   "x": 400, "y": 0}
        pid = self._dataflow(client, user, headers, [heights])
        testing_provider.push_replies(
            {"toolCalls": [_call("node.content.write", {"nodeId": "n1", "content": {"rows": 3}})]},
            {"toolCalls": [_call("node.content.write", {"nodeId": "heights", "content": HISTOGRAM})]},
            "Wrote the histogram.",
        )
        body = _run(client, headers, pid, _attach(client, headers, pid, NB))
        refused, written = _native_results()
        assert "must be a non-empty string" not in refused, refused
        assert refused == CODE_GIVEN_AN_OBJECT
        assert not written.startswith("refused"), written
        assert [p["tool"] for p in body["content"] if p["type"] == "change"] == ["node.content.write"]
        saved = _saved_nodes(user, pid)
        assert saved["heights"]["content"] == json.dumps(HISTOGRAM, indent=2, ensure_ascii=False)
        assert saved["n1"]["content"] == "return 1"

    def test_a_plan_carrying_the_object_is_refused_as_one_carrying_its_text_is(
        self, client, user_and_token, headers,
    ):
        """A plan carries no content (``plan.nodes-carry-content``), the same
        document given as its text or as the object it is."""
        user, _ = user_and_token
        pid = self._dataflow(client, user, headers)
        node = {"ref": "h", "nodeType": AUTK, "title": "Heights", "intent": "a histogram of the heights"}
        plan = {"goal": "chart the heights", "edges": []}
        testing_provider.push_replies(
            {"toolCalls": [_call("dataflow.plan.write", {**plan, "nodes": [{**node, "content": json.dumps(HISTOGRAM)}]})]},
            {"toolCalls": [_call("dataflow.plan.write", {**plan, "nodes": [{**node, "content": HISTOGRAM}]})]},
            "I could not plan it.",
        )
        body = _run(client, headers, pid, _attach(client, headers, pid, DFB))
        as_text, as_object = _native_results()
        assert "must be a string" not in as_object, as_object
        assert as_object == as_text
        assert as_object.startswith("refused: plan nodes must not carry content"), as_object
        assert not [p for p in body["content"] if p["type"] == "change"]
