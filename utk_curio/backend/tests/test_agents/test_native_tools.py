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
from utk_curio.backend.app.agents.domain import content
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
from utk_curio.backend.tests.test_agents import test_routes as _tr

_auth = _tr._auth

CHAT = "agent.chat-agent@1.0.0"
NB = "agent.node-builder@1.0.0"
DFB = "agent.dataflow-builder@1.0.0"
DF = "agent.dataset-finder@1.0.0"
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


@pytest.fixture()
def project(client, user_and_token):
    user, token = user_and_token
    from utk_curio.backend.app.projects.services import _user_dir_key

    _tr.TestNodeCreate()._write_builtin_package(_user_dir_key(user), templates=TEMPLATES)
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
        if not (messages and messages[0].get("content") == titles.TITLE_PROMPT)
    ]


def _offered() -> list[dict]:
    return [o for o, messages in zip(testing_provider.offered(), testing_provider.captured())
            if not (messages and messages[0].get("content") == titles.TITLE_PROMPT)]


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
        grants = tools.grant_descriptions(["catalog.search", "datalake.search"])
        native = content.tail_instruction(grants, native_tools=True)
        fenced = content.tail_instruction(grants)
        assert native.startswith(content.TAIL_INSTRUCTION)
        assert content.NATIVE_TOOLS_INSTRUCTION in native
        assert '"toolRequest"' in fenced and '"toolRequest"' not in native
        assert "- catalog.search:" in fenced and "- catalog.search:" not in native
        # The candidates block is no tool call, so both protocols keep its schema.
        assert content.CANDIDATES_INSTRUCTION in native and content.CANDIDATES_LAKE_ADDENDUM in native

    def test_the_native_delegation_paragraph_names_the_delegate_tool(self):
        entries = [("node.content.generate", "Node Content Builder")]
        native = content.delegation_instruction(entries, native_tools=True)
        assert "node.content.generate" in native and "Node Content Builder" in native
        assert "delegate tool" in native and "delegateRequest" not in native
        assert "delegateRequest" in content.delegation_instruction(entries)

    def test_a_native_run_is_told_how_to_call(self, client, headers, project):
        att = _attach(client, headers, project, CHAT)
        testing_provider.push_reply("Hello.")
        _run(client, headers, project, att)
        (system, *_), = _run_calls()
        assert content.NATIVE_TOOLS_INSTRUCTION in system["content"]
        assert '"toolRequest"' not in system["content"]
        assert [s["kind"] for s in system["slots"]][:2] == ["preamble", "instruction"]
        assert _offered()[0] == {
            "tools": ["dataflow__read", "node__read", "node__runtime__read"], "toolChoice": "auto",
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
        assert content.NATIVE_TOOLS_INSTRUCTION not in system["content"]
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
        assert last_result["content"].endswith(tool_rounds._FINAL_ROUND_NOTE)

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
    def test_a_native_create_call_mints_the_proposal(self, client, headers, project):
        att = _attach(client, headers, project, NB)
        testing_provider.push_replies(
            {"toolCalls": [_call("node.create", {"nodeType": CA, "content": "return 2", "title": "Two"})]},
            "Proposed a node.",
        )
        body = _run(client, headers, project, att)
        (proposal,) = [p for p in body["content"] if p["type"] == "proposal"]
        assert proposal["tool"] == "node.create"
        result = _run_calls()[1][-1]
        assert result["is_error"] is False and result["content"].startswith("proposal ")

    def test_a_refused_create_call_is_an_error_the_model_can_fix(self, client, headers, project):
        att = _attach(client, headers, project, NB)
        testing_provider.push_replies(
            {"toolCalls": [_call("node.create", {"nodeType": CA})]},
            {"toolCalls": [_call("node.create", {"nodeType": CA, "content": "return 3"})]},
            "Proposed.",
        )
        body = _run(client, headers, project, att)
        refused = _run_calls()[1][-1]
        assert refused["is_error"] is True
        assert refused["content"] == "refused: params.content must be a non-empty string"
        assert [p["tool"] for p in body["content"] if p["type"] == "proposal"] == ["node.create"]

    def test_the_plan_is_a_call_whose_errors_come_back_as_its_result(self, client, headers, project):
        att = _attach(client, headers, project, DFB)
        plan = {"goal": "count twice", "nodes": [
            {"ref": "a", "nodeType": CA, "title": "Count", "intent": "count the rows again"}],
            "edges": [{"from": "n1", "to": "a"}]}
        testing_provider.push_replies(
            {"toolCalls": [_call("dataflow.plan.write", {**plan, "goal": ""})]},
            {"toolCalls": [_call("dataflow.plan.write", plan)]},
            "Here is the plan.",
        )
        body = _run(client, headers, project, att)
        rejected = _run_calls()[1][-1]
        assert rejected["is_error"] is True and "goal" in rejected["content"]
        assert [p["tool"] for p in body["content"] if p["type"] == "proposal"] == ["dataflow.plan.write"]
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
        assert '"toolRequest"' in retry_system and content.NATIVE_TOOLS_INSTRUCTION not in retry_system
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
            if messages[0].get("content") == titles.TITLE_PROMPT:
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
                       self._cfg(api_type="testing"), self._cfg(model="t", trained=True)):
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
