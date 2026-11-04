"""The native-tools trial is fair to a model that thinks before it answers.

An OpenAI-compatible endpoint the capability table does not know is asked once
per model whether it calls tools natively (``chat_capabilities``, through
``providers.probe_native_tools``), and the account keeps the answer. The trial
asked for 32 tokens, not streamed, and a server may count the model's thinking
against that cap, as vLLM counts gemma4's. On 11-03 the owner's server, which
takes native tools, answered the trial in 0.7 s with finish ``length``, 118
characters of thinking sent apart, no call and an empty reply. The trial read
that as "the model answered without calling the tool it was offered", so the
account kept "fenced", and all 1,354 gemma4 turn records of the live
evaluations ran fenced. Asked with room to think (32 + 1,024 tokens), the same
request called the tool after 47 tokens, in 0.6 s.

The trial now asks as a turn does, with the room a model that thinks gets
(#1278's ``_asked_with_room``): a trial cut before a word or a call is asked
again with the room, and one its limit still cut is no answer. An answer an
account kept before, fenced for a reply without a call, may have been such a
cut, so it is tried again.

The stub is a vLLM-like server on 127.0.0.1 whose model thinks before it
answers and counts its thinking against the request's cap. It answers a request
whole or streamed, as vLLM does, so a checkout without the fix asks it as it
always did, and fails at an assertion for the reason the live server showed.
Nothing the fix adds is imported at the top: a module that cannot import on a
checkout without it would hide every other test's failure there.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from utk_curio.backend import config
from utk_curio.backend.app.agents.infrastructure import chat_capabilities as cc
from utk_curio.backend.app.agents.infrastructure import providers
from utk_curio.backend.app.agents.infrastructure.providers import ProviderConfig
from utk_curio.backend.app.agents.repositories import ledger, model_catalog
from utk_curio.backend.tests.test_agents.test_output_cap import CAP, ROOM, _attach, _ended, _last_turn

USER = "7"
#: The deployment default's model and key in the agents' suite (conftest.py).
MODEL = "test-model"
KEY = "test-key"
#: The trial's cap, and the room a model that thinks gets for it.
TRIAL_CAP = 32
TRIAL_ROOM = 1024
TRIAL_WITH_ROOM = TRIAL_CAP + TRIAL_ROOM
#: The prompt tokens the stub reports for every request, as the live server
#: did for the trial, and what a call of ping costs: with the room, gemma4's
#: whole trial wrote 47 tokens.
PROMPT_TOKENS = 47
CALL_TOKENS = 7
#: The stub's model thinks in pieces of PIECE tokens, each sent as THOUGHT,
#: and writes a token for every CHARS characters of a reply.
PIECE = 16
THOUGHT = "The user wants ping called. "
CHARS = 3
#: What the stub's model answers a request that is not the trial.
TURN_REPLY = "Done."
#: vLLM's refusal of a request offering tools, on a server started without tool calling.
NO_TOOLS = '"auto" tool choice requires --enable-auto-tool-choice and --tool-call-parser to be set'
#: The reason the trial gave, before the fix, for any reply without a call.
REASON_BEFORE_THE_FIX = "the model answered without calling the tool it was offered"
#: The pace the owner's vLLM server streamed gemma4 at in the live evaluations.
LIVE_TOKENS_A_SECOND = 48
#: The trial's wait, scaled down, and how long a server that sends nothing holds the request.
SCALED_WAIT_S = 0.5
HOLD_S = 3.0

_REAL_PROBE = providers.probe_native_tools


@pytest.fixture(autouse=True)
def _the_trial_runs(monkeypatch, _endpoint_not_asked_about_tools):
    """These tests are about the trial, so it asks the stub."""
    monkeypatch.setattr(providers, "probe_native_tools", _REAL_PROBE)


# -- the stub server ------------------------------------------------------------

def _is_trial(asked: dict) -> bool:
    """Whether *asked* is the trial: a request offering ping."""
    return any((tool.get("function") or {}).get("name") == "ping" for tool in asked.get("tools") or [])


def _tokens_of(text: str) -> int:
    return -(-len(text) // CHARS)


def _reply(thinking: int, call: bool, text: str, cap: int | None) -> dict:
    """What a model that thinks *thinking* tokens, then calls ping (*call*)
    or writes *text*, sends a request whose cap is *cap*, its server counting
    the thinking against the cap as vLLM counts gemma4's: the pieces of its
    thinking, its text, whether its call came, its finish reason and the
    tokens it wrote. The cap stops it where it falls (``length``): a call it
    did not finish never comes."""
    thought, sent = [], 0
    while sent < thinking:
        size = min(PIECE, thinking - sent)
        if cap is not None and sent + size > cap:
            if cap > sent:
                thought.append(THOUGHT)
            return {"thought": thought, "text": "", "call": False, "finish": "length", "tokens": cap}
        thought.append(THOUGHT)
        sent += size
    need = CALL_TOKENS if call else _tokens_of(text)
    if cap is not None and sent + need > cap:
        written = "" if call else text[:(cap - sent) * CHARS]
        return {"thought": thought, "text": written, "call": False, "finish": "length", "tokens": cap}
    return {"thought": thought, "text": "" if call else text, "call": call,
            "finish": "tool_calls" if call else "stop", "tokens": sent + need}


_CALL = {"id": "call-ping", "type": "function", "function": {"name": "ping", "arguments": "{}"}}


class _Handler(BaseHTTPRequestHandler):
    """One request (HTTP/1.0: an answer ends when its connection closes)."""

    def log_message(self, *args):
        pass

    def do_POST(self):
        asked = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        stub = self.server.stub
        stub.requests.append(asked)
        cap = asked.get("max_tokens")
        if stub.refuses_tools and asked.get("tools"):
            self._refused(NO_TOOLS)
        elif stub.refuse_above is not None and cap is not None and cap > stub.refuse_above:
            window = stub.refuse_above + PROMPT_TOKENS
            self._refused(f"'max_tokens' or 'max_completion_tokens' is too large: {cap}. This model's maximum "
                          f"context length is {window} tokens and your request has {PROMPT_TOKENS} input tokens "
                          f"({cap} > {window} - {PROMPT_TOKENS}).")
        elif stub.hold and _is_trial(asked):
            # Nothing at all: the request is held, then its connection closes.
            stub.released.wait(HOLD_S)
        elif asked.get("stream"):
            self._streamed(stub.reply_to(asked))
        else:
            self._whole(stub.reply_to(asked))

    def _send_json(self, status: int, body: dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _refused(self, message: str) -> None:
        """The server's refusal of the request, as vLLM answers one."""
        self._send_json(400, {"object": "error", "message": message, "type": "BadRequestError",
                              "param": None, "code": 400})

    @staticmethod
    def _usage(reply: dict) -> dict:
        return {"prompt_tokens": PROMPT_TOKENS, "completion_tokens": reply["tokens"],
                "total_tokens": PROMPT_TOKENS + reply["tokens"]}

    def _whole(self, reply: dict) -> None:
        """The reply whole, as vLLM answers a request that is not streamed:
        the thinking apart from the reply (``reasoning_content``)."""
        message = {"role": "assistant", "content": reply["text"] or None,
                   "reasoning_content": "".join(reply["thought"]) or None,
                   "tool_calls": [_CALL] if reply["call"] else []}
        self._send_json(200, {"id": "chatcmpl-stub", "object": "chat.completion", "created": 0, "model": MODEL,
                              "choices": [{"index": 0, "message": message, "finish_reason": reply["finish"]}],
                              "usage": self._usage(reply)})

    def _streamed(self, reply: dict) -> None:
        """The reply as vLLM streams it: the thinking in pieces apart from the
        reply, then the reply's text or its call, the finish reason and the
        usage."""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        self._event(self._chunk({"role": "assistant", "content": ""}))
        for piece in reply["thought"]:
            self._event(self._chunk({"reasoning_content": piece}))
        if reply["text"]:
            self._event(self._chunk({"content": reply["text"]}))
        if reply["call"]:
            self._event(self._chunk({"tool_calls": [{"index": 0, **_CALL}]}))
        self._event(self._chunk({}, reply["finish"]))
        self._event({"id": "chatcmpl-stub", "object": "chat.completion.chunk", "created": 0, "model": MODEL,
                     "choices": [], "usage": self._usage(reply)})
        self._event("[DONE]")

    def _event(self, payload) -> None:
        data = payload if isinstance(payload, str) else json.dumps(payload)
        self.wfile.write(f"data: {data}\n\n".encode())
        self.wfile.flush()

    @staticmethod
    def _chunk(delta: dict, finish: str | None = None) -> dict:
        return {"id": "chatcmpl-stub", "object": "chat.completion.chunk", "created": 0, "model": MODEL,
                "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}


class _Server:
    """A vLLM-like server whose model thinks *thinking* tokens before it
    answers the trial, then calls ping (*calls*) or answers "pong" without
    it, and thinks *turn_thinking* tokens before it answers anything else
    with :data:`TURN_REPLY`. *refuses_tools*: it refuses any request offering
    tools, as vLLM does without tool calling. *refuse_above*: it refuses any
    request whose cap passes that, as vLLM refuses one whose prompt and cap
    pass its window. *hold*: it holds the trial's request and sends nothing."""

    def __init__(self, *, thinking: int = 0, calls: bool = True, turn_thinking: int = 0,
                 refuses_tools: bool = False, refuse_above: int | None = None, hold: bool = False):
        self.thinking = thinking
        self.calls = calls
        self.turn_thinking = turn_thinking
        self.refuses_tools = refuses_tools
        self.refuse_above = refuse_above
        self.hold = hold
        self.requests: list[dict] = []
        self.released = threading.Event()
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self.httpd.daemon_threads = True
        self.httpd.stub = self
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def reply_to(self, asked: dict) -> dict:
        cap = asked.get("max_tokens")
        if _is_trial(asked):
            return _reply(self.thinking, self.calls, "" if self.calls else "pong", cap)
        return _reply(self.turn_thinking, False, TURN_REPLY, cap)

    @property
    def trial_requests(self) -> list[dict]:
        return [asked for asked in self.requests if _is_trial(asked)]

    @property
    def trial_caps(self) -> list:
        """The cap each request of the trial carried, in order."""
        return [asked.get("max_tokens") for asked in self.trial_requests]

    @property
    def base_url(self) -> str:
        host, port = self.httpd.server_address[:2]
        return f"http://{host}:{port}/v1"

    def config(self) -> ProviderConfig:
        return ProviderConfig(api_key=KEY, api_type="openai_compatible", base_url=self.base_url, model=MODEL)

    def close(self) -> None:
        self.released.set()
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(5)


@pytest.fixture()
def model_server(monkeypatch):
    """Start a :class:`_Server` as the deployment's model."""
    started: list[_Server] = []

    def _start(**options) -> _Server:
        server = _Server(**options)
        started.append(server)
        monkeypatch.setattr(config, "DEFAULT_LLM_BASE_URL", server.base_url)
        return server

    yield _start
    for server in started:
        server.close()


# -- reading what the trial did ---------------------------------------------------

def _remembered(server: _Server) -> dict | None:
    """What the account keeps of the stub's endpoint and model."""
    return model_catalog.remembered_chat_capabilities(USER, "openai_compatible", server.base_url, MODEL)


def _kept_before(server: _Server, **answer) -> None:
    """The account keeps *answer* for the stub's endpoint, as a trial wrote it
    before the fix."""
    model_catalog.remember_chat_capabilities(
        USER, "openai_compatible", server.base_url, MODEL, {"structuredOutput": False, **answer})


def _charged() -> list[dict]:
    """The usage the ledger charged for each trial."""
    return [entry["usage"] for entry in ledger._read_entries(USER, ledger._today())
            if entry.get("note") == "capability-probe"]


def _seen_thinking(server: _Server) -> None:
    """A call without tools, as a conversation's title is asked, on which
    the endpoint's model is seen thinking."""
    providers.run_chat_turn(server.config(), [{"role": "user", "content": "Name this conversation."}], 16,
                            thinking_tokens=1024)


# -- a model that thinks ----------------------------------------------------------

@pytest.mark.parametrize("thinking", [40, 600], ids=["as-gemma4", "a-longer-thought"])
def test_a_model_that_thinks_before_it_calls_the_tool_is_found_to_call_tools(tmp_curio, model_server, thinking):
    """The model thinks before it calls ping: 40 tokens, as gemma4 thought
    118 characters and called after 47 tokens on 11-03, or 600. Its server
    counts the thinking against the trial's 32 tokens, which ran out while it
    thought, and the account kept the fenced protocol. The trial is asked
    again with the room, the call comes, and native tools are kept; both
    requests are charged."""
    server = model_server(thinking=thinking)
    found = cc.chat_capabilities(server.config(), USER)
    assert (found.protocol, found.source) == ("native", "trial"), f"the trial of a model that thinks said {found!r}"
    assert server.trial_caps == [TRIAL_CAP, TRIAL_WITH_ROOM]
    assert (_remembered(server) or {}).get("tools") is True
    assert _charged() == [{"inputTokens": 2 * PROMPT_TOKENS, "outputTokens": TRIAL_CAP + thinking + CALL_TOKENS}]


def test_a_model_seen_thinking_is_tried_with_the_room_at_once(tmp_curio, model_server):
    """An endpoint already seen thinking in this process, here by a call
    without tools as a conversation's title is asked, is tried with the room
    from the start: one request, and the call."""
    server = model_server(thinking=40, turn_thinking=100)
    _seen_thinking(server)
    found = cc.chat_capabilities(server.config(), USER)
    assert (found.protocol, found.source) == ("native", "trial"), f"the trial of a model seen thinking said {found!r}"
    assert server.trial_caps == [TRIAL_WITH_ROOM]


def test_a_trial_its_room_still_cut_is_no_answer_and_is_asked_again(tmp_curio, model_server):
    """The model thinks past the trial's room too: 5,000 tokens. A cut trial
    never counts as "the server takes no tools": the run goes fenced, the
    account keeps nothing, and the next run asks again, with the room at
    once, since the model was seen thinking."""
    server = model_server(thinking=5000)
    found = cc.chat_capabilities(server.config(), USER)
    assert (found.protocol, found.source) == ("fenced", "unknown"), f"a cut trial was taken for an answer: {found!r}"
    assert f"{TRIAL_WITH_ROOM:,}" in found.reason, found.reason
    assert _remembered(server) is None
    assert server.trial_caps == [TRIAL_CAP, TRIAL_WITH_ROOM]
    again = cc.chat_capabilities(server.config(), USER)
    assert (again.protocol, again.source) == ("fenced", "unknown"), again
    assert server.trial_caps == [TRIAL_CAP, TRIAL_WITH_ROOM, TRIAL_WITH_ROOM]


def test_a_server_that_refuses_the_room_is_no_answer_either(tmp_curio, model_server):
    """The server's window holds the trial's 32 tokens but not the room: it
    refuses the request that carries the room with a 400, as vLLM refuses one
    whose prompt and cap pass its window. That refusal is the room's, never
    the tools': the trial is asked again without the room, the model's
    thinking runs out again, and the trial is no answer."""
    server = model_server(thinking=40, refuse_above=TRIAL_CAP)
    found = cc.chat_capabilities(server.config(), USER)
    assert (found.protocol, found.source) == ("fenced", "unknown"), f"the room's refusal was taken for an answer: {found!r}"
    assert _remembered(server) is None
    assert server.trial_caps == [TRIAL_CAP, TRIAL_WITH_ROOM, TRIAL_CAP]


# -- a server that takes no tools ---------------------------------------------------

@pytest.mark.parametrize("seen_thinking", [False, True], ids=["first-asked", "seen-thinking"])
def test_a_server_that_refuses_tools_is_still_fenced(tmp_curio, model_server, seen_thinking):
    """vLLM started without tool calling answers any request offering tools
    with a 400. The trial says the fenced protocol, the account keeps it, and
    the next run asks nothing. On an endpoint seen thinking, the trial is
    asked with the room first; that request's refusal is taken for the
    room's, and the one asked without the room, refused too, decides. Passes
    without the fix too: a guard."""
    server = model_server(refuses_tools=True, turn_thinking=100)
    if seen_thinking:
        _seen_thinking(server)
    found = cc.chat_capabilities(server.config(), USER)
    assert (found.protocol, found.source) == ("fenced", "trial"), f"a server that takes no tools was found {found!r}"
    assert "refused a tool" in found.reason and "--enable-auto-tool-choice" in found.reason, found.reason
    assert (_remembered(server) or {}).get("tools") is False
    assert server.trial_caps[-1] == TRIAL_CAP
    asked = len(server.trial_requests)
    again = cc.chat_capabilities(server.config(), USER)
    assert (again.protocol, again.source) == ("fenced", "remembered"), again
    assert len(server.trial_requests) == asked


# -- an account kept fenced from a cut trial ----------------------------------------

def test_an_account_kept_fenced_from_a_cut_trial_is_tried_again(tmp_curio, model_server):
    """Before the fix the account kept what the trial said of the model that
    thinks: the fenced protocol, because "the model answered without calling
    the tool it was offered", the reason the trial gave a reply its 32 tokens
    cut while the model thought as well as one that ignored the tool. Nothing
    told the two apart, so the next run tries the endpoint again, with no one
    doing anything, and the trial's answer replaces the old one."""
    server = model_server(thinking=40)
    _kept_before(server, tools=False, reason=REASON_BEFORE_THE_FIX)
    found = cc.chat_capabilities(server.config(), USER)
    assert (found.protocol, found.source) == ("native", "trial"), (
        f"the account kept fenced from a cut trial was not tried again: {found!r}")
    assert server.trial_caps == [TRIAL_CAP, TRIAL_WITH_ROOM]
    assert (_remembered(server) or {}).get("tools") is True
    again = cc.chat_capabilities(server.config(), USER)
    assert (again.protocol, again.source) == ("native", "remembered"), again
    assert len(server.trial_requests) == 2


@pytest.mark.parametrize("kept", [
    {"tools": False, "reason": "the endpoint refused a tool: Error code: 400 - tools are not supported"},
    {"tools": False, "reason": "the endpoint refused a run's native tools: tools are not supported"},
    {"tools": True, "reason": "the model called the tool it was offered"},
], ids=["the-trial-was-refused", "a-run-was-refused", "the-model-called"])
def test_an_answer_kept_before_the_fix_that_was_no_cut_stands(tmp_curio, model_server, kept):
    """What an account kept before the fix stands when it cannot have been a
    cut: the endpoint refused the trial's tool, it refused a run's tools, or
    the model called the tool. The endpoint is not asked again. Passes
    without the fix too: a guard."""
    server = model_server(thinking=40)
    _kept_before(server, **kept)
    found = cc.chat_capabilities(server.config(), USER)
    assert (found.tools, found.source) == (kept["tools"], "remembered"), found
    assert server.trial_requests == []


# -- a model that does not think ----------------------------------------------------

@pytest.mark.parametrize("calls", [True, False], ids=["calls-the-tool", "answers-without-it"])
def test_a_model_that_does_not_think_is_tried_as_before(tmp_curio, model_server, calls):
    """No thinking: one request of 32 tokens offering ping, with tool choice
    auto, and its answer kept: native tools when the model calls ping, the
    fenced protocol when it answers "pong" without it. The next run asks
    nothing. Passes without the fix too: a guard."""
    server = model_server(thinking=0, calls=calls)
    found = cc.chat_capabilities(server.config(), USER)
    assert (found.protocol, found.source) == ("native" if calls else "fenced", "trial"), found
    (asked,) = server.trial_requests
    assert (asked.get("max_tokens"), asked.get("tool_choice")) == (TRIAL_CAP, "auto")
    assert asked.get("messages") == [{"role": "user", "content": "Call the ping tool."}]
    assert [tool["function"]["name"] for tool in asked["tools"]] == ["ping"]
    assert (_remembered(server) or {}).get("tools") is calls
    again = cc.chat_capabilities(server.config(), USER)
    assert again.source == "remembered" and len(server.trial_requests) == 1, again


# -- the trial is short and bounded --------------------------------------------------

def test_the_trials_wait_holds_a_held_back_reply_and_stays_below_the_turns_limits():
    """The trial's reads wait a time of their own. Its whole reply with the
    room, 1,056 tokens, takes 22 s at the 48 tokens a second the owner's vLLM
    server streamed gemma4 at, so a server that holds it all back until it
    ends, as a tool parser may hold a call, still answers inside the wait at
    half that pace. The wait stays below #1272's 120 s silence limit, which
    the trial so never comes to, and below a turn's 300 s wait for its first
    chunk."""
    wait = getattr(providers, "TRIAL_WAIT_S", None)
    assert isinstance(wait, (int, float)), "the trial has no wait of its own"
    assert 2 * TRIAL_WITH_ROOM / LIVE_TOKENS_A_SECOND <= wait < providers.STREAM_SILENCE_S < providers.FIRST_CHUNK_S


def test_a_server_that_sends_nothing_is_given_up_on_at_the_trials_wait(tmp_curio, model_server, monkeypatch):
    """The server holds the trial's request and sends nothing. The trial ends
    at its own wait, saying so, asks once, and the account keeps nothing, so
    the next run asks again. Scaled down: a wait of 0.5 s, a request held
    3 s."""
    monkeypatch.setattr(providers, "TRIAL_WAIT_S", SCALED_WAIT_S, raising=False)
    server = model_server(hold=True)
    found = cc.chat_capabilities(server.config(), USER)
    assert (found.protocol, found.source) == ("fenced", "unknown"), found
    assert f"nothing came for {SCALED_WAIT_S:g} s after it was asked" in found.reason, found.reason
    assert len(server.trial_requests) == 1
    assert _remembered(server) is None


# -- a run on the model that thinks --------------------------------------------------

def test_a_run_on_a_model_that_thinks_is_offered_its_tools_natively(
        client, user_and_token, tmp_curio, alice_project, model_server):
    """The run route, as the live evaluations ran gemma4: the account's first
    run with tools tries the endpoint, whose model thinks before it calls
    ping. The run is offered its tools natively, and its record says so. The
    trial saw the model think, so each round is asked with its room at
    once."""
    server = model_server(thinking=40, turn_thinking=100)
    _, token = user_and_token
    attachment_id = _attach(client, token, alice_project)
    ended = _ended(client, token, alice_project, attachment_id, "run")
    assert ended.get("reply") == TURN_REPLY, ended
    pins = _last_turn(client, token, alice_project, attachment_id)["execution"]["pins"]
    assert pins.get("toolProtocol") == "native", f"the run on a model that thinks ran {pins.get('toolProtocol')!r}"
    rounds = [asked for asked in server.requests if asked.get("tools") and not _is_trial(asked)]
    assert rounds and [asked.get("max_tokens") for asked in rounds] == [CAP + ROOM] * len(rounds), (
        [asked.get("max_tokens") for asked in rounds])
