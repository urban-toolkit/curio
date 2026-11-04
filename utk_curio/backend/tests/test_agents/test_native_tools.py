"""Native tool calls: a run whose LLM configuration calls tools natively.

Such a run is offered its grants and its delegates as tools (``tools.native_tools``)
instead of the fenced ``toolRequest`` / ``delegateRequest`` syntax, and the
model's first call takes the path a fenced request takes: the same parser and
budgets, grant check, mint, delegate and round accounting. Its result goes back
as a tool message answering the call, flagged when it is an error. Every other
call of the reply is answered as not run, the last round offers no call, and
an endpoint that refuses the tools puts the run on the fenced protocol, from
where it was. Runs go through the scripted provider, scripted to call tools
natively (``testing_provider.script_chat_capabilities``).
"""

from __future__ import annotations

import json

import pytest

from utk_curio.backend.app.agents.infrastructure import chat_capabilities
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
CA = "curio.builtin/computation-analysis"

TEMPLATES = [
    {
        "id": "computation-analysis", "label": "Computation Analysis",
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
    "\"nodeType\": \"curio.builtin/computation-analysis\"}}\n```"
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
        assert refused.startswith("refused: ") and "Pick one of the choices." in refused, refused
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
        for widget in (plan["nodes"]["items"]["properties"]["widgets"]["items"], created["widgets"]["items"]):
            options = (widget["properties"].get("options") or {}).get("properties") or {}
            assert {key: value.get("type") for key, value in options.items()} == {
                key: value["type"] for key, value in trill["options"]["properties"].items()}
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
