"""A model server behind a proxy that limits how long a request may run.

A self-hosted OpenAI-compatible server, such as vLLM, often sits behind a
proxy like nginx, which cuts a request whose answer has sent nothing back for
a while (60 s by default), with its 504 page or by dropping the connection. A
request that is not streamed gets nothing back until the model has written the
whole reply, so a reply that took longer than that to write never arrived: the
turn ended in "agent run failed: Connection error." after the SDK had asked
twice more, and the model had written the reply three times.

The stub here is such a server on 127.0.0.1, with its times scaled down: the
model writes a reply in pieces, one every ``PACE_S``, and a proxy before it
cuts what has been silent for ``LIMIT_S``, or, with a limit on the whole
request, any answer still running at ``LIMIT_S``. What the proxy cuts follows
the stub's own schedule, never a measured time, so a slow runner cannot change
an outcome.
"""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from utk_curio.backend import config
from utk_curio.backend.app.agents.infrastructure import providers
from utk_curio.backend.app.agents.infrastructure.providers import ChatTurn, ProviderConfig
from utk_curio.backend.tests._support.agent_routes import _auth

#: The model writes one piece every PACE_S.
PACE_S = 0.1
#: The proxy's limit: on silence, or on the whole request.
LIMIT_S = 0.5
REPLY_PIECES = ["The ", "factor ", "is ", "now ", "a ", "number ", "widget ", "named ",
                "factor, ", "set ", "to ", "25."]
REPLY = "".join(REPLY_PIECES)
#: The pieces a limit on the whole request lets through: LIMIT_S of PACE_S.
PIECES_WITHIN_THE_LIMIT = 5
USAGE = {"prompt_tokens": 21000, "completion_tokens": 12, "total_tokens": 21012}
MESSAGES = [{"role": "user", "content": "Use 25 as the factor this node multiplies column b by."}]
#: What nginx answers when it gives up on the server.
NGINX_504 = ("<html>\r\n<head><title>504 Gateway Time-out</title></head>\r\n<body>\r\n"
             "<center><h1>504 Gateway Time-out</h1></center>\r\n<hr><center>nginx</center>\r\n"
             "</body>\r\n</html>\r\n")


class _Handler(BaseHTTPRequestHandler):
    """One request to the server, through the proxy (HTTP/1.0: an answer ends
    when its connection closes)."""

    def log_message(self, *args):
        pass

    def do_POST(self):
        asked = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        stub = self.server.stub
        stub.requests.append(asked)
        if asked.get("stream"):
            self._stream(stub)
        else:
            self._whole(stub)

    def _whole(self, stub):
        """The answer would begin once the whole reply is written, which takes
        longer than LIMIT_S; it is silent until then, so the proxy cuts it at
        LIMIT_S under either limit."""
        time.sleep(LIMIT_S)
        if stub.cut == "504":
            page = NGINX_504.encode()
            self.send_response(504, "Gateway Time-out")
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(page)))
            self.end_headers()
            self.wfile.write(page)
        # "drop": the connection closes with no answer at all.

    def _event(self, payload):
        data = payload if isinstance(payload, str) else json.dumps(payload)
        self.wfile.write(f"data: {data}\n\n".encode())
        self.wfile.flush()

    def _chunk(self, delta, finish=None):
        return {"id": "chatcmpl-stub", "object": "chat.completion.chunk", "created": 0, "model": "test-model",
                "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}

    def _stream(self, stub):
        """Each piece as the model writes it, PACE_S apart, so the answer is
        never silent for LIMIT_S. A limit on the whole request ends it after
        the pieces that fit in LIMIT_S, with no finish reason."""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        self._event(self._chunk({"role": "assistant", "content": ""}))
        for index, piece in enumerate(REPLY_PIECES):
            if stub.limit == "whole request" and index == PIECES_WITHIN_THE_LIMIT:
                return
            time.sleep(PACE_S)
            self._event(self._chunk({"content": piece}))
        self._event(self._chunk({}, "stop"))
        self._event({"id": "chatcmpl-stub", "object": "chat.completion.chunk", "created": 0,
                     "model": "test-model", "choices": [], "usage": USAGE})
        self._event("[DONE]")


class _ModelServer:
    """An OpenAI-compatible model server behind a proxy, on 127.0.0.1.
    *limit* is what the proxy limits ("silence" or "whole request"), *cut*
    how it cuts a request that is not streamed ("drop" or "504")."""

    def __init__(self, *, limit: str, cut: str):
        self.limit = limit
        self.cut = cut
        self.requests: list[dict] = []
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
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
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(5)


@pytest.fixture()
def model_server():
    started: list[_ModelServer] = []

    def _start(*, limit: str, cut: str = "drop") -> _ModelServer:
        assert PACE_S < LIMIT_S < PACE_S * len(REPLY_PIECES), "the stub's times must keep their order"
        server = _ModelServer(limit=limit, cut=cut)
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


@pytest.mark.parametrize("cut", ["drop", "504"])
def test_a_reply_that_takes_longer_to_write_than_the_proxys_silence_limit_arrives_whole(model_server, cut):
    server = model_server(limit="silence", cut=cut)
    usage: dict = {}
    outcome = _outcome(lambda: providers.run_chat_turn(
        server.config(), MESSAGES, max_output_tokens=4096, usage_out=usage))
    assert outcome == ChatTurn(text=REPLY, stop_reason="stop"), f"the call ended with {outcome!r}"
    assert usage == {"inputTokens": 21000, "outputTokens": 12}
    assert len(server.requests) == 1, f"the model was asked for the reply {len(server.requests)} times"
    assert server.requests[0]["max_tokens"] == 4096


def test_a_reply_cut_short_by_a_limit_on_the_whole_request_is_an_error_that_says_so(model_server):
    server = model_server(limit="whole request")
    outcome = _outcome(lambda: providers.run_chat_turn(server.config(), MESSAGES, max_output_tokens=4096))
    assert not isinstance(outcome, ChatTurn), f"a part of the reply came back as all of it: {outcome!r}"
    assert "the model's server ended the reply before the model finished it" in str(outcome), repr(outcome)


def test_a_turn_whose_reply_outlasts_the_proxys_silence_limit_answers_it(
        client, user_and_token, tmp_curio, alice_project, model_server, monkeypatch):
    """The blocking run route, which a delegated run's call shares: the turn
    answers its reply, where it answered 502 "agent run failed: Connection
    error." once the proxy had cut each try."""
    server = model_server(limit="silence")
    monkeypatch.setattr(config, "DEFAULT_LLM_BASE_URL", server.base_url)
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
    assert (answer.status_code, body.get("reply")) == (200, REPLY), body
