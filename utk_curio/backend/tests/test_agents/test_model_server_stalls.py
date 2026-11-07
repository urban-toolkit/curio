"""A model server that stops sending without closing its stream.

A self-hosted OpenAI-compatible server (vLLM behind a proxy, say) can stop
feeding a stream it has begun and leave the connection open. The SDK alone
waits 600 s on each read, so a chat turn sat for ten minutes with no word, and
an evaluation's runner then ran the case twice more. A stream that sends
nothing past a bounded time fails within that time, saying that the model's
server stopped sending; its first chunk may take longer, while a long prompt
is read in; and a request the server held unanswered is not sent again.

The stub here is such a server on 127.0.0.1, with the limits scaled down
(``SILENCE_S`` once a chunk has come, ``FIRST_CHUNK_S`` for any one read). A
stalled answer stays open and silent until ``HOLD_S``, well past both, then
closes: what ends a call follows the stub's own schedule, never a measured
time, and a call with no limits of its own ends at the close instead, with
what the close says.
"""

from __future__ import annotations

import json
import threading
import time
import types
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from utk_curio.backend.app.agents.infrastructure import providers
from utk_curio.backend.app.agents.infrastructure.providers import ChatTurn, ProviderConfig
from utk_curio.backend.tests._support.agent_routes import _auth
from utk_curio.backend.tests._support import llm_deployment

#: The limits, scaled down: a stream's silence once a chunk has come, and any
#: one read (the wait for the first chunk).
SILENCE_S = 1.0
FIRST_CHUNK_S = 3.0
#: How long the stub holds a stalled answer open and silent before it closes it.
HOLD_S = 6.0
#: A slow but steady answer: its first chunk later than SILENCE_S, as while a
#: long prompt is read in, then a piece every PACE_S, the whole of it longer
#: than FIRST_CHUNK_S.
FIRST_WAIT_S = 1.5
PACE_S = 0.2
PIECES = ["The ", "factor ", "is ", "now ", "a ", "number ", "widget ", "named ",
          "factor, ", "set ", "to ", "25."]
REPLY = "".join(PIECES)
#: What a stalled answer sends before it stops.
BEFORE_THE_STALL = ["Reading ", "the ", "node."]
MESSAGES = [{"role": "user", "content": "Use 25 as the factor this node multiplies column b by."}]
#: What the failure of a call whose server stopped sending says.
STOPPED = "the model's server stopped sending"


def _chunk(delta, finish=None):
    return {"id": "chatcmpl-stub", "object": "chat.completion.chunk", "created": 0, "model": "test-model",
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}


class _Handler(BaseHTTPRequestHandler):
    """One request to the server. HTTP/1.0: an answer ends when its connection
    closes."""

    def log_message(self, *args):
        pass

    def do_POST(self):
        asked = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        stub = self.server.stub
        stub.requests.append(asked)
        if not asked.get("stream"):
            # The native-tools trial a chat makes first, which asks whole.
            self.status(400, "this server takes no tools")
            return
        # Each request takes the next answer; the last one answers the rest.
        answer = stub.answers.pop(0) if len(stub.answers) > 1 else stub.answers[0]
        _ANSWERS[answer](self, stub)

    def status(self, code, message):
        body = json.dumps({"error": {"message": message, "type": "server_error"}}).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def begin(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        if self.server.stub.chunked:
            self.send_header("Transfer-Encoding", "chunked")
            self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.flush()

    def send(self, payload):
        data = f"data: {payload if isinstance(payload, str) else json.dumps(payload)}\n\n".encode()
        if self.server.stub.chunked:
            data = b"%x\r\n%s\r\n" % (len(data), data)
        self.wfile.write(data)
        self.wfile.flush()

    def end(self):
        if self.server.stub.chunked:
            self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()


class _ChunkedHandler(_Handler):
    """The same server on HTTP/1.1, its answer sent in chunks (as uvicorn, and
    so vLLM, sends a stream): a connection that closes mid-answer is an error
    of the read, not the answer's end."""

    protocol_version = "HTTP/1.1"


def _stall(handler, stub):
    """A few pieces, then nothing, the connection held open."""
    handler.begin()
    handler.send(_chunk({"role": "assistant", "content": ""}))
    for piece in BEFORE_THE_STALL:
        time.sleep(0.05)
        handler.send(_chunk({"content": piece}))
    stub.released.wait(HOLD_S)


def _nothing(handler, stub):
    """No answer at all: the request held, then its connection closed."""
    stub.released.wait(HOLD_S)


def _headers_only(handler, stub):
    """The answer's headers, as from a server that begins its answer before it
    has read the prompt in, then nothing."""
    handler.begin()
    stub.released.wait(HOLD_S)


def _steady(handler, stub):
    """The first chunk FIRST_WAIT_S after the headers, then a piece every PACE_S."""
    handler.begin()
    time.sleep(FIRST_WAIT_S)
    handler.send(_chunk({"role": "assistant", "content": ""}))
    for piece in PIECES:
        time.sleep(PACE_S)
        handler.send(_chunk({"content": piece}))
    handler.send(_chunk({}, "stop"))
    handler.send("[DONE]")
    handler.end()


def _at_once(handler, stub):
    """The whole reply at once."""
    handler.begin()
    handler.send(_chunk({"role": "assistant", "content": ""}))
    for piece in PIECES:
        handler.send(_chunk({"content": piece}))
    handler.send(_chunk({}, "stop"))
    handler.send("[DONE]")
    handler.end()


def _turned_down(status):
    def _answer(handler, stub):
        handler.status(status, f"the server answered {status}")
    return _answer


_ANSWERS = {"stall": _stall, "nothing": _nothing, "headers only": _headers_only, "steady": _steady,
            "at once": _at_once, "503": _turned_down(503), "504": _turned_down(504)}


class _ModelServer:
    """An OpenAI-compatible model server on 127.0.0.1 that answers each
    streamed request with the next of *answers*."""

    def __init__(self, answers, *, chunked: bool):
        self.answers = list(answers)
        self.chunked = chunked
        self.requests: list[dict] = []
        self.released = threading.Event()
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), _ChunkedHandler if chunked else _Handler)
        self.httpd.daemon_threads = True
        self.httpd.stub = self
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    @property
    def base_url(self) -> str:
        host, port = self.httpd.server_address[:2]
        return f"http://{host}:{port}/v1"

    def config(self) -> ProviderConfig:
        return ProviderConfig(api_key="test-key", api_type="openai_compatible",
                              base_url=self.base_url, model="test-model")

    def close(self) -> None:
        self.released.set()
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(5)


@pytest.fixture()
def model_server(monkeypatch):
    monkeypatch.setattr(providers, "STREAM_SILENCE_S", SILENCE_S, raising=False)
    monkeypatch.setattr(providers, "FIRST_CHUNK_S", FIRST_CHUNK_S, raising=False)
    started: list[_ModelServer] = []

    def _start(*answers: str, chunked: bool = False) -> _ModelServer:
        assert PACE_S < SILENCE_S < FIRST_WAIT_S < FIRST_CHUNK_S < FIRST_WAIT_S + PACE_S * len(PIECES), (
            "the stub's times must keep their order")
        assert FIRST_CHUNK_S < HOLD_S, "a stalled answer must outlast both limits"
        server = _ModelServer(answers, chunked=chunked)
        started.append(server)
        return server

    yield _start
    for server in started:
        server.close()


def _outcome(call):
    """What *call* returned, or the error it raised, as a value, so that a
    test fails at its assertion whichever it was."""
    try:
        return call()
    except Exception as exc:  # noqa: BLE001 - the error is the outcome
        return exc


def _streamed(server, finish: dict | None = None):
    """The pieces a streamed turn yielded, and how it ended: None, or its error."""
    pieces = []
    try:
        for event in providers.stream_chat_turn(server.config(), MESSAGES, 256, finish=finish):
            pieces.append(event)
    except Exception as exc:  # noqa: BLE001 - the error is the outcome
        return pieces, exc
    return pieces, None


def _whole(server):
    return _outcome(lambda: providers.run_chat_turn(server.config(), MESSAGES, max_output_tokens=256))


@pytest.mark.parametrize("framing", ["until close", "chunked"])
@pytest.mark.parametrize("asked", ["whole", "streamed"])
def test_a_stream_its_server_stops_feeding_ends_once_silent_for_the_limit_and_says_so(model_server, asked, framing):
    """The answer sends three pieces, then holds its connection open with
    nothing more. The call ends SILENCE_S after the last piece, with an error
    that says the server stopped sending, and nothing is asked again."""
    server = model_server("stall", chunked=framing == "chunked")
    pieces, outcome = ([], _whole(server)) if asked == "whole" else _streamed(server)
    message = str(outcome)
    assert isinstance(outcome, Exception) and STOPPED in message, f"the call ended with {outcome!r}"
    assert f"nothing came for {SILENCE_S:g} s after the last piece of its reply" in message, message
    assert pieces == ([] if asked == "whole" else BEFORE_THE_STALL)
    assert len(server.requests) == 1, f"the model was asked {len(server.requests)} times"


@pytest.mark.parametrize("asked", ["whole", "streamed"])
def test_a_slow_but_steady_stream_stays_alive(model_server, asked):
    """Its first chunk comes later than SILENCE_S, as while a long prompt is
    read in, then a piece every PACE_S, and the whole answer takes longer than
    FIRST_CHUNK_S: the silence limit counts only once a chunk has come, and no
    limit is on the whole request."""
    server = model_server("steady")
    if asked == "whole":
        outcome = _whole(server)
        assert outcome == ChatTurn(text=REPLY, stop_reason="stop"), f"the call ended with {outcome!r}"
    else:
        finish: dict = {}
        pieces, outcome = _streamed(server, finish)
        assert (pieces, outcome, finish.get("reason")) == (PIECES, None, "stop"), f"the call ended with {outcome!r}"
    assert len(server.requests) == 1


@pytest.mark.parametrize("answer", ["nothing", "headers only"])
def test_a_request_its_server_never_answers_ends_at_the_first_chunk_limit_and_is_sent_once(model_server, answer):
    """The server holds the request past FIRST_CHUNK_S, with no answer at all
    or with only its headers. The call ends then, saying so, and the request
    is not sent again: a new try would wait as long."""
    server = model_server(answer)
    outcome = _whole(server)
    message = str(outcome)
    assert isinstance(outcome, Exception) and STOPPED in message, f"the call ended with {outcome!r}"
    assert f"nothing came for {FIRST_CHUNK_S:g} s after it was asked" in message, message
    assert len(server.requests) == 1, f"the model was asked {len(server.requests)} times"


@pytest.mark.parametrize("status, asks", [(503, 2), (504, 1)])
def test_a_request_turned_down_at_once_is_sent_again_and_a_gateway_timeout_is_not(model_server, status, asks):
    """A 503 came back at once, before the server began to answer: the request
    is sent again, as the SDK's own retries did, and the reply arrives. A 504
    says a gateway before the server gave up waiting on it, which a new try
    would wait on as long: the call fails with it."""
    server = model_server(str(status), "at once")
    outcome = _whole(server)
    if status == 503:
        assert outcome == ChatTurn(text=REPLY, stop_reason="stop"), f"the call ended with {outcome!r}"
    else:
        assert getattr(outcome, "status_code", None) == 504, f"the call ended with {outcome!r}"
    assert len(server.requests) == asks, f"the model was asked {len(server.requests)} times"


def test_a_turn_whose_model_server_stops_sending_answers_that_it_stopped(
        client, user_and_token, tmp_curio, alice_project, model_server, monkeypatch):
    """The blocking run route, which a delegated run's call shares: the turn
    answers 502 with what happened, where it waited out each read."""
    server = model_server("stall")
    llm_deployment.change_first(monkeypatch, base_url=server.base_url)
    _, token = user_and_token
    coord = "agent.curio.researcher@1"
    client.post(f"/api/agents/projects/{alice_project}/install", json={"coord": coord}, headers=_auth(token))
    attachment = client.post(
        f"/api/agents/projects/{alice_project}/attachments",
        json={"coord": coord, "target": {"kind": "canvas"}}, headers=_auth(token),
    ).get_json()
    answer = client.post(
        f"/api/agents/projects/{alice_project}/attachments/{attachment['attachmentId']}/run",
        json={"message": MESSAGES[0]["content"]}, headers=_auth(token),
    )
    body = answer.get_json()
    assert (answer.status_code, STOPPED in str(body.get("error"))) == (502, True), body


def test_the_evaluation_runs_no_case_again_whose_model_server_stopped_sending(model_server):
    """The run route answers 502 for every turn whose model call failed, and
    the evaluation's runner runs such a case again, but not one whose server
    stopped sending: the new try would wait out the silence too."""
    from utk_curio.tools import skill_eval_worker

    assert skill_eval_worker._transient(502, "the run answered 502: agent run failed: Connection error.")
    server = model_server("stall")
    error = f"the run answered 502: agent run failed: {_whole(server)}"
    assert not skill_eval_worker._transient(502, error), error


def test_the_grader_is_not_asked_again_once_its_model_server_stopped_sending(model_server, monkeypatch, tmp_path):
    """The evaluation's grader asks again after a failed call, but not after
    one whose server stopped sending."""
    from utk_curio.backend.app.agents.evaluation import skill_evals
    from utk_curio.tools import skill_eval_worker

    server = model_server("stall")
    monkeypatch.setattr(skill_eval_worker, "RETRY_WAITS_S", (0, 0))
    monkeypatch.setattr(skill_eval_worker.provider_config, "resolve_llm", lambda *args, **kwargs: server.config())
    worker = skill_eval_worker.Worker.__new__(skill_eval_worker.Worker)
    worker.results, worker.user_key = tmp_path, "grader"
    worker.endpoint = types.SimpleNamespace(model="test-model")
    task = skill_evals.Task(
        kind=skill_evals.TASK, skill="nodes", key="eval-1/with_skill/run-1", condition=skill_evals.WITH_SKILL,
        run=1, message=MESSAGES[0]["content"], context=None, case=1, expected_output="The factor is 25.",
        assertions=("The reply sets the factor to 25.",),
    )
    grading = worker._grade(task, {"reply": REPLY}, {"changed": {}})
    assert STOPPED in str(grading.get("error")), grading
    assert len(server.requests) == 1, f"the grader was asked {len(server.requests)} times"
