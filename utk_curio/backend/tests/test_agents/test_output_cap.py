"""A reply the output cap cut says so: it never passes as a whole one.

Every agent call goes out with the run policy's output cap (``max_tokens``,
4,096), and a model's server that stops a reply there says so by its finish
reason: ``length`` on an OpenAI-compatible server, ``max_tokens`` on Anthropic,
``MAX_TOKENS`` on Gemini. On 10-30 a Node Builder chat turn on vLLM (gemma4)
used exactly its 4,096 output tokens in 81 s and reached the user as an empty
reply with status ok. Nothing read the finish reason, on the blocking path or
the streamed one, and nothing read the model's thinking, which such a server
may stream apart from the reply (``reasoning_content``, or ``reasoning``).

The stub here is an OpenAI-compatible server on 127.0.0.1. It streams each
turn's scripted pieces, then ends the stream with a finish reason, or with none,
as a cut connection does. A delegate's call, the skill evaluations' grader and
the other providers' calls are scripted turns and fakes of their SDKs. What a
test checks is read as a value (``_outcome``, ``_message``), so a checkout
without the fix fails at an assertion.
"""

from __future__ import annotations

import enum
import json
import sys
import threading
import types
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from utk_curio.backend import config
from utk_curio.backend.app.agents.infrastructure import providers
from utk_curio.backend.app.agents.infrastructure.providers import ChatTurn, ProviderConfig
from utk_curio.backend.app.projects.services import _user_dir_key
from utk_curio.backend.tests._support.agent_routes import _auth

#: The run policy's output cap, which every turn's call carries.
CAP = 4096
#: The cap as a reply's line writes it.
LIMIT = "4,096"
COORD = "agent.curio.researcher@1"
MESSAGE = "Add two more bars to this chart: J with 60 and K with 33."
#: What the model wrote before the cap cut it, mid-sentence.
SO_FAR = ["J and K go in ", "the loading node's rows: ", "its DataFrame gains"]
#: The model's thinking, which a server may stream apart from its reply.
THINKING = ["The user wants two more bars. ", "The chart draws the table the node before it returns, so"]
WHOLE = ["Add J with 60 and K with 33 ", "to the rows the loading node returns."]
#: A reply the cap cut inside a request's block.
CUT_REQUEST = ["Let me read the dataflow first.\n\n", "```curio.v1\n",
               '{"toolRequest": {"tool": "dataflow.read", "par']
PATHS = ["run", "run/stream"]


# -- the stub server ----------------------------------------------------------

class _Reply:
    """One scripted reply: its pieces, each ``(field of the delta, text)``,
    and the finish reason its stream ends with, or None for a stream that
    ends with none."""

    def __init__(self, pieces, finish):
        self.pieces = list(pieces)
        self.finish = finish


def _content(texts):
    return [("content", text) for text in texts]


def _thinking(texts, field):
    return [(field, text) for text in texts]


class _Handler(BaseHTTPRequestHandler):
    """One request (HTTP/1.0: an answer ends when its connection closes)."""

    def log_message(self, *args):
        pass

    def do_POST(self):
        asked = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        reply = self.server.stub.answer(asked)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        self._event(self._chunk({"role": "assistant", "content": ""}))
        for field, text in reply.pieces:
            self._event(self._chunk({field: text}))
        if reply.finish is None:
            return
        self._event(self._chunk({}, reply.finish))
        self._event({"id": "chatcmpl-stub", "object": "chat.completion.chunk", "created": 0, "model": "test-model",
                     "choices": [], "usage": {"prompt_tokens": 17619, "completion_tokens": CAP,
                                              "total_tokens": 17619 + CAP}})
        self._event("[DONE]")

    def _event(self, payload):
        data = payload if isinstance(payload, str) else json.dumps(payload)
        self.wfile.write(f"data: {data}\n\n".encode())
        self.wfile.flush()

    @staticmethod
    def _chunk(delta, finish=None):
        return {"id": "chatcmpl-stub", "object": "chat.completion.chunk", "created": 0, "model": "test-model",
                "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}


class _ModelServer:
    """An OpenAI-compatible model server on 127.0.0.1 that streams scripted
    replies. A call with the turn's cap takes the next one (a short whole
    reply once none is left); any other call, such as the conversation's
    title, gets a short whole reply."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.requests: list[dict] = []
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self.httpd.daemon_threads = True
        self.httpd.stub = self
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def answer(self, asked: dict) -> _Reply:
        self.requests.append(asked)
        if asked.get("max_tokens") == CAP and self.replies:
            return self.replies.pop(0)
        return _Reply(_content(["Done."]), "stop")

    @property
    def turn_calls(self) -> list[dict]:
        """The calls a turn made with its cap: its rounds."""
        return [asked for asked in self.requests if asked.get("max_tokens") == CAP]

    @property
    def base_url(self) -> str:
        host, port = self.httpd.server_address[:2]
        return f"http://{host}:{port}/v1"

    def config(self) -> ProviderConfig:
        return ProviderConfig(api_key="test-key", api_type="openai_compatible",
                              base_url=self.base_url, model="test-model")

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(5)


@pytest.fixture()
def model_server(monkeypatch):
    """Start a stub with its scripted replies, as the deployment's model."""
    started: list[_ModelServer] = []

    def _start(*replies) -> _ModelServer:
        server = _ModelServer(replies)
        started.append(server)
        monkeypatch.setattr(config, "DEFAULT_LLM_BASE_URL", server.base_url)
        return server

    yield _start
    for server in started:
        server.close()


# -- reading what a turn did --------------------------------------------------

def _outcome(call):
    """What *call* returned, or the error it raised, as a value."""
    try:
        return call()
    except Exception as exc:  # noqa: BLE001 - the error is the outcome
        return exc


def _message(message_id: str, **values) -> str | None:
    """The message *message_id* of messages.md, filled; None when the page
    has no such message."""
    from utk_curio.backend.app.agents.domain import agent_text

    try:
        return agent_text.message(message_id, **values)
    except agent_text.AgentTextError:
        return None


def _attach(client, token, project_id) -> str:
    client.post(f"/api/agents/projects/{project_id}/install", json={"coord": COORD}, headers=_auth(token))
    return client.post(
        f"/api/agents/projects/{project_id}/attachments",
        json={"coord": COORD, "target": {"kind": "canvas"}}, headers=_auth(token),
    ).get_json()["attachmentId"]


def _ended(client, token, project_id, attachment_id, path) -> dict:
    """How the turn asked through *path* ended: the blocking answer's body or
    the stream's ``done``, or ``{"error": ...}`` as the answer or the stream
    said it."""
    answer = client.post(
        f"/api/agents/projects/{project_id}/attachments/{attachment_id}/{path}",
        json={"message": MESSAGE}, headers=_auth(token),
    )
    if path == "run":
        body = answer.get_json(silent=True) or {}
        return body if answer.status_code == 200 else {"error": body.get("error"), "status": answer.status_code}
    events = []
    for block in answer.get_data(as_text=True).strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line)
        if "event" in lines:
            events.append((lines["event"], json.loads(lines["data"])))
    for name, data in events:
        if name == "done":
            return data
        if name == "error":
            return {"error": data.get("error")}
    return {"events": events}


def _last_turn(client, token, project_id, attachment_id) -> dict:
    """The conversation's last turn, as it was saved."""
    turns = client.get(
        f"/api/agents/projects/{project_id}/attachments/{attachment_id}/session", headers=_auth(token),
    ).get_json()["turns"]
    return turns[-1]


# -- a chat turn the cap cut ----------------------------------------------------

@pytest.mark.parametrize("path", PATHS)
def test_a_turn_the_cap_cut_keeps_what_it_wrote_and_says_it_was_cut(
        client, user_and_token, tmp_curio, alice_project, model_server, path):
    """The model writes part of a sentence and stops at the cap. The reply
    keeps that part and ends with the line that says it was cut there, where
    it came back as if whole; the saved turn and its record say the same."""
    server = model_server(_Reply(_content(SO_FAR), "length"))
    _, token = user_and_token
    attachment_id = _attach(client, token, alice_project)
    ended = _ended(client, token, alice_project, attachment_id, path)
    so_far = "".join(SO_FAR)
    assert ended.get("reply") != so_far, f"the reply the cap cut came back as if whole: {ended!r}"
    assert ended.get("reply") == f"{so_far}\n\n{_message('turn.cut-at-output-limit', limit=LIMIT)}", ended
    assert ended.get("cutAtOutputLimit") is True, ended
    saved = _last_turn(client, token, alice_project, attachment_id)
    assert saved["text"] == ended["reply"]
    assert (saved["execution"]["status"], saved["execution"].get("cutAtOutputLimit")) == ("ok", True)
    (asked,) = server.turn_calls
    assert asked["stream"] is True


@pytest.mark.parametrize("field", ["reasoning_content", "reasoning"])
@pytest.mark.parametrize("path", PATHS)
def test_a_turn_that_spent_the_cap_thinking_says_so(
        client, user_and_token, tmp_curio, alice_project, model_server, path, field):
    """The server streams the model's thinking apart from its reply, under
    either name servers give it, until the cap: no reply text came. The reply
    says the model spent the cap thinking, where it was empty."""
    model_server(_Reply(_thinking(THINKING, field), "length"))
    _, token = user_and_token
    attachment_id = _attach(client, token, alice_project)
    ended = _ended(client, token, alice_project, attachment_id, path)
    assert ended.get("reply"), f"the turn that spent the cap thinking came back empty: {ended!r}"
    assert ended["reply"] == _message("turn.cut-while-thinking", limit=LIMIT), ended
    assert "".join(THINKING) not in ended["reply"]
    assert _last_turn(client, token, alice_project, attachment_id)["execution"].get("cutAtOutputLimit") is True


@pytest.mark.parametrize("path", PATHS)
def test_a_round_the_cap_cut_runs_nothing_it_asked_for(
        client, user_and_token, tmp_curio, alice_project, model_server, path):
    """The cap cuts the model inside a request's block. The half-written
    block is not shown, read as a request or sent back for a correction: the
    turn ends on that round with the text before the block and the line."""
    server = model_server(_Reply(_content(CUT_REQUEST), "length"))
    _, token = user_and_token
    attachment_id = _attach(client, token, alice_project)
    ended = _ended(client, token, alice_project, attachment_id, path)
    rounds = len(server.turn_calls)
    assert rounds == 1, f"the round the cap cut was followed by {rounds - 1} more: {ended!r}"
    assert ended.get("reply") == (
        f"{CUT_REQUEST[0].strip()}\n\n{_message('turn.cut-at-output-limit', limit=LIMIT)}"
    ), ended
    assert not _last_turn(client, token, alice_project, attachment_id)["execution"].get("toolCalls")


@pytest.mark.parametrize("path", PATHS)
def test_a_whole_reply_stays_as_it_is(client, user_and_token, tmp_curio, alice_project, model_server, path):
    """A reply the model finished (``stop``) is shown as it came, its
    thinking left out, and nothing says it was cut."""
    model_server(_Reply(_thinking(THINKING, "reasoning_content") + _content(WHOLE), "stop"))
    _, token = user_and_token
    attachment_id = _attach(client, token, alice_project)
    ended = _ended(client, token, alice_project, attachment_id, path)
    assert ended.get("reply") == "".join(WHOLE), ended
    assert "cutAtOutputLimit" not in ended
    saved = _last_turn(client, token, alice_project, attachment_id)
    assert saved["text"] == "".join(WHOLE)
    assert "cutAtOutputLimit" not in saved["execution"]


@pytest.mark.parametrize("path", PATHS)
def test_a_reply_whose_stream_ends_with_no_finish_reason_is_an_error_on_both_paths(
        client, user_and_token, tmp_curio, alice_project, model_server, path):
    """The server's stream ends before the model finished, with no finish
    reason (a connection cut). The blocking path failed the turn with the
    reason (#1261); the streamed one passed the part off as the whole reply."""
    model_server(_Reply(_content(SO_FAR), None))
    _, token = user_and_token
    attachment_id = _attach(client, token, alice_project)
    ended = _ended(client, token, alice_project, attachment_id, path)
    assert "reply" not in ended, f"a part of the reply came back as all of it: {ended!r}"
    assert "the model's server ended the reply before the model finished it" in str(ended.get("error")), ended
    assert _last_turn(client, token, alice_project, attachment_id).get("error")


# -- the provider port ----------------------------------------------------------

@pytest.mark.parametrize("field", ["reasoning_content", "reasoning"])
def test_an_openai_compatible_turn_carries_its_finish_reason_and_its_thinking_on_both_paths(model_server, field):
    """Through the SDK itself: a streamed turn writes how it ended into the
    dict its caller hands it, and a whole one into its turn, the thinking
    never read as reply text."""
    server = model_server(_Reply(_thinking(THINKING, field) + _content(SO_FAR), "length"),
                          _Reply(_thinking(THINKING, field) + _content(SO_FAR), "length"))
    messages = [{"role": "user", "content": MESSAGE}]
    finish: dict = {}
    events = _outcome(lambda: list(providers.stream_chat_turn(server.config(), messages, CAP, finish=finish)))
    assert finish == {"reason": "length", "thinking": True}, f"the stream ended with {events!r}, finish {finish!r}"
    assert events == SO_FAR
    turn = _outcome(lambda: providers.run_chat_turn(server.config(), messages, CAP))
    assert (getattr(turn, "text", None), getattr(turn, "stop_reason", None), getattr(turn, "thinking", None)) == (
        "".join(SO_FAR), "length", True), repr(turn)


def test_anthropic_names_the_cap_on_both_paths(monkeypatch):
    """Anthropic's ``max_tokens``: the whole turn carried it; the streamed
    one now writes it too, read off the stream's final message."""
    final = types.SimpleNamespace(content=[types.SimpleNamespace(type="text", text="par")], usage=None,
                                  stop_reason="max_tokens")

    class _Stream:
        text_stream = iter(["par"])

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def get_final_message(self):
            return final

    messages = types.SimpleNamespace(create=lambda **kwargs: final, stream=lambda **kwargs: _Stream())
    fake = types.SimpleNamespace(Anthropic=lambda **kwargs: types.SimpleNamespace(messages=messages),
                                 NOT_GIVEN="NG")
    monkeypatch.setitem(sys.modules, "anthropic", fake)
    cfg = ProviderConfig(api_key="k", api_type="anthropic", base_url="", model="m")
    asked = [{"role": "user", "content": MESSAGE}]
    assert providers.run_chat_turn(cfg, asked, CAP).stop_reason == "max_tokens"
    finish: dict = {}
    events = _outcome(lambda: list(providers.stream_chat_turn(cfg, asked, CAP, finish=finish)))
    assert (events, finish.get("reason")) == (["par"], "max_tokens"), finish


class _FinishReason(enum.IntEnum):
    """Gemini's finish reason as its SDK gives it: an enum whose text is its number."""

    FINISH_REASON_UNSPECIFIED = 0
    STOP = 1
    MAX_TOKENS = 2


def test_gemini_names_the_cap_on_both_paths(monkeypatch):
    """Gemini's ``MAX_TOKENS``, by the finish reason's name: no Gemini turn
    carried a stop reason at all."""

    def _response(text, reason):
        part = types.SimpleNamespace(text=text)
        candidate = types.SimpleNamespace(content=types.SimpleNamespace(parts=[part]), finish_reason=reason)
        return types.SimpleNamespace(candidates=[candidate], usage_metadata=None)

    class _Chat:
        def send_message(self, message, stream=False, **kwargs):
            if stream:
                return iter([_response("pa", _FinishReason.FINISH_REASON_UNSPECIFIED),
                             _response("r", _FinishReason.MAX_TOKENS)])
            return _response("par", _FinishReason.MAX_TOKENS)

    class _Model:
        def __init__(self, model, system_instruction=None):
            pass

        def start_chat(self, history):
            return _Chat()

    fake = types.ModuleType("google.generativeai")
    fake.configure = lambda api_key: None
    fake.GenerativeModel = _Model
    google = types.ModuleType("google")
    google.generativeai = fake
    monkeypatch.setitem(sys.modules, "google", google)
    monkeypatch.setitem(sys.modules, "google.generativeai", fake)
    cfg = ProviderConfig(api_key="k", api_type="gemini", base_url="", model="m")
    asked = [{"role": "user", "content": MESSAGE}]
    turn = providers.run_chat_turn(cfg, asked, CAP)
    assert (turn.text, turn.stop_reason) == ("par", "MAX_TOKENS")
    finish: dict = {}
    events = _outcome(lambda: list(providers.stream_chat_turn(cfg, asked, CAP, finish=finish)))
    assert (events, finish.get("reason")) == (["pa", "r"], "MAX_TOKENS"), finish


# -- a delegate the cap cut -----------------------------------------------------

@pytest.mark.parametrize("stop_reason", ["length", "max_tokens", "MAX_TOKENS"],
                         ids=["openai-compatible", "anthropic", "gemini"])
def test_a_delegate_the_cap_cut_fails_and_lands_none_of_its_code(
        client, user_and_token, tmp_curio, monkeypatch, stop_reason):
    """The Node Builder, attached to node n1, hands n1's code to its content
    mode, whose model stops at the cap after a line that parses. That code
    used to land in n1 as if whole. Now the delegate fails with the reason, n1
    keeps its code, and the run carries on to its answer."""
    from utk_curio.backend.app.projects import storage as projects_storage
    from utk_curio.backend.tests.test_agents import test_delegation as delegation_tests

    user, token = user_and_token
    project_id = delegation_tests._project(client, token)
    _, calls = delegation_tests._setup(client, token, project_id, monkeypatch, replies=[
        delegation_tests._delegate_tail(),
        ChatTurn(text="print('fixed')\n", stop_reason=stop_reason),
        "The code was cut off.",
    ])
    attachment_id = client.post(
        f"/api/agents/projects/{project_id}/attachments",
        json={"coord": delegation_tests.NB, "target": {"kind": "node", "targetId": "n1"}}, headers=_auth(token),
    ).get_json()["attachmentId"]
    body = delegation_tests._run(client, token, project_id, attachment_id, message="fix the print").get_json()
    spec = projects_storage.read_spec(_user_dir_key(user), project_id)
    code = next(node for node in spec["dataflow"]["nodes"] if node["id"] == "n1")["content"]
    assert code == "print(1)", f"the code the cap cut landed in n1: {code!r}"
    assert not [part for part in body["content"] if part["type"] == "change"]
    entry = next(part for part in body["content"] if part["type"] == "delegation")
    cut = _message("delegate.cut-at-output-limit", coord=delegation_tests.NB, limit=LIMIT)
    assert (entry["status"], entry["summary"]) == ("failed", cut), entry
    assert cut in calls[2][-1]["content"]
    assert body["reply"] == "The code was cut off."
    saved = _last_turn(client, token, project_id, attachment_id)
    (child,) = saved["execution"]["delegations"]
    assert (child["status"], child.get("cutAtOutputLimit")) == ("error", True)


def test_a_solve_round_the_cap_cut_stops_with_the_reason_and_runs_none_of_it(
        client, user_and_token, tmp_curio, monkeypatch):
    """Solve this node, on an empty node: its content mode's model stops at
    the cap after code that would run. That code used to run and land in the
    node as if whole. Now the round stops with the reason as its generation
    error, and the code never runs or lands."""
    from utk_curio.backend.app.agents.application.turns import titles
    from utk_curio.backend.tests.test_agents import test_verified_rounds as verified_rounds

    user, token = user_and_token
    harness = verified_rounds.TestSolveNode()
    ctx = harness._setup(client, user, token, monkeypatch, content="")
    code = harness.LOADER.replace("{DATASET}", ctx["dataset_id"])

    def _fake_run(config, messages, **kwargs):
        if messages and messages[0].get("content") == titles.title_prompt():
            return "Title"
        ctx["calls"].append(messages)
        return ChatTurn(text=code, stop_reason="length")

    monkeypatch.setattr(providers, "run_chat_turn", _fake_run)
    done = harness._solve_node(client, token, ctx)[-1][1]
    assert harness._content(ctx) == "", f"the code the cap cut landed in the node: {done!r}"
    assert ctx["payloads"] == [], "the code the cap cut was run"
    assert (done.get("verdict"), done["attempts"][-1].get("kind")) == ("fail", "generation-error"), done
    assert done["attempts"][-1]["detail"] == _message("delegate.cut-at-output-limit", coord=harness.NB, limit=LIMIT)


# -- the skill evaluations' grader ---------------------------------------------

def test_a_grade_the_cap_cut_is_not_read_and_says_it_was_cut(
        client, user_and_token, tmp_curio, tmp_path, monkeypatch):
    """The grader stops at its output cap inside its JSON, on every try. The
    grade said the grader's reply was in the wrong shape; it says the reply
    was cut off at the grader's limit."""
    from utk_curio.backend.app.agents.evaluation import skill_evals
    from utk_curio.tools import skill_eval_worker

    asked: list = []

    def _fake_run(config, messages, max_output_tokens=None, usage_out=None, **kwargs):
        asked.append(max_output_tokens)
        return ChatTurn(text='{"assertion_results": [{"text": "J and K", "passed": true, "evidence": "The rep',
                        stop_reason="length")

    monkeypatch.setattr(providers, "run_chat_turn", _fake_run)
    user, _ = user_and_token
    worker = skill_eval_worker.Worker.__new__(skill_eval_worker.Worker)
    worker.results, worker.user_key = tmp_path, _user_dir_key(user)
    worker.endpoint = types.SimpleNamespace(model="test-model")
    context = skill_evals.Context(agent="agent.curio.node-builder@1", dataflow=None)
    task = skill_evals.Task(kind=skill_evals.TASK, skill="node-control", key="eval-3/with_skill/run-1",
                            condition=skill_evals.WITH_SKILL, run=1, message=MESSAGE, context=context, case=3,
                            assertions=("The answer adds J and K to the rows of the loading node.",))
    grading = _outcome(lambda: worker._grade(task, {"reply": "J and K go in the rows."}, {"changed": {}}))
    limit = f"{skill_eval_worker.GRADER_MAX_TOKENS:,}"
    assert isinstance(grading, dict) and grading.get("error") == (
        f"its reply was cut off at the grader's output limit of {limit} tokens"), grading
    assert asked == [skill_eval_worker.GRADER_MAX_TOKENS] * skill_eval_worker.GRADER_ATTEMPTS
