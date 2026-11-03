"""A model that thinks before it answers gets room to answer.

Every agent call goes out with the run policy's output cap (``max_tokens``,
4,096), and a server may count the model's thinking against it, as vLLM counts
gemma4's. In the scenarios skill's live evaluations of 11-03, 9 of 48 runs
ended with the line that the model "spent its whole output limit of 4,096
tokens thinking" and no answer, each cut call 84 to 86 s of thinking, while
the whole one-call turns wrote 510 to 3,518 tokens for replies of 227 to 550
characters. A model seen thinking now gets the run policy's room for its
thinking (8,192 tokens) on top of the cap: a reply the cap cut before it wrote
anything is asked again with the room, and the endpoint's later calls carry
it from the start. A model that does not think is asked as before.

The OpenAI-compatible stub (:class:`_Thinker`, on test_output_cap.py's
server) thinks before each round's reply and counts its thinking against the
request's cap as vLLM does. Anthropic and Gemini are fakes of their SDKs whose
models think the same way: Claude 5 and later think by default, and Gemini 2.5
and later count their thoughts against the cap. What a test checks is read as
a value (``_outcome``), so a checkout without the fix fails at an assertion.
"""

from __future__ import annotations

import json
import sys
import types

import pytest

from utk_curio.backend import config
from utk_curio.backend.app.agents.infrastructure import providers
from utk_curio.backend.app.agents.infrastructure.providers import ChatTurn, ProviderConfig
from utk_curio.backend.app.projects.services import _user_dir_key
from utk_curio.backend.tests._support.agent_routes import _auth
from utk_curio.backend.tests.test_agents.test_output_cap import (
    CAP,
    LIMIT,
    LIMIT_WITH_ROOM,
    MESSAGE,
    PATHS,
    ROOM,
    WITH_ROOM,
    _attach,
    _ended,
    _FinishReason,
    _last_turn,
    _message,
    _ModelServer,
    _outcome,
    _Reply,
    _ThinkingModel,
)

#: How long the model thinks before its reply: past the cap, inside the room.
THOUGHT = 6000
#: Past the cap and the room together.
ENDLESS = 40000
REPLY = "Add J with 60 and K with 33 to the rows the loading node returns: the chart then draws both bars."
TITLE = "Two More Bars"
#: The prompt tokens the stub's usage reports for every request.
PROMPT = 17619
#: The title call's own cap, and the room a model that thinks gets for it.
TITLE_CAP = 16
TITLE_ROOM = 1024


def _is_title(asked: dict) -> bool:
    """Whether *asked* is the conversation's title call."""
    from utk_curio.backend.app.agents.application.turns import titles

    messages = asked.get("messages") or []
    return bool(messages) and messages[0].get("content") == titles.title_prompt()


class _Thinker(_ModelServer):
    """A model that thinks before each reply, on a server that counts its
    thinking against the request's cap, as vLLM counts gemma4's
    (:meth:`_ThinkingModel.reply_for`). Each round of the chat is
    ``(thinking tokens, reply)``: a request whose cap cuts it gets the start
    of the round, cut where the cap falls (``length``), and the same round is
    asked again; a request with room for the whole round gets it whole
    (``stop``), and the next request is the next round. The title call gets
    :data:`TITLE` after *title_thinking* tokens of thinking. A request whose
    cap passes *refuse_above* is refused with a 400, as vLLM refuses one whose
    prompt and cap pass its context window."""

    def __init__(self, rounds, *, title_thinking: int = 0, refuse_above: int | None = None):
        super().__init__(())
        self.rounds = list(rounds)
        self.at = 0
        self.title_thinking = title_thinking
        self.refuse_above = refuse_above

    def answer(self, asked: dict) -> _Reply:
        self.requests.append(asked)
        cap = asked.get("max_tokens")
        if self.refuse_above is not None and cap is not None and cap > self.refuse_above:
            window = self.refuse_above + PROMPT
            return _Reply.refused(
                f"'max_tokens' or 'max_completion_tokens' is too large: {cap}. This model's maximum context "
                f"length is {window} tokens and your request has {PROMPT} input tokens ({cap} > {window} - {PROMPT}).")
        if _is_title(asked):
            return _ThinkingModel.reply_for(self.title_thinking, TITLE, cap)
        thinking, reply = self.rounds[min(self.at, len(self.rounds) - 1)]
        answer = _ThinkingModel.reply_for(thinking, reply, cap)
        if answer.finish == "stop":
            self.at += 1
        return answer

    @property
    def round_caps(self) -> list:
        """The cap each call of the chat's rounds and of its delegates carried, in order."""
        return [asked.get("max_tokens") for asked in self.requests if not _is_title(asked)]

    @property
    def title_caps(self) -> list:
        """The cap each title call carried, in order."""
        return [asked.get("max_tokens") for asked in self.requests if _is_title(asked)]


@pytest.fixture()
def thinker(monkeypatch):
    """Start a :class:`_Thinker` as the deployment's model."""
    started: list[_Thinker] = []

    def _start(*rounds, **options) -> _Thinker:
        server = _Thinker(rounds, **options)
        started.append(server)
        monkeypatch.setattr(config, "DEFAULT_LLM_BASE_URL", server.base_url)
        return server

    yield _start
    for server in started:
        server.close()


def _spent(*tokens: int) -> dict:
    """The usage of a turn whose requests wrote *tokens* each."""
    return {"inputTokens": PROMPT * len(tokens), "outputTokens": sum(tokens)}


# -- a chat turn ----------------------------------------------------------------

@pytest.mark.parametrize("path", PATHS)
def test_a_model_that_thinks_past_the_cap_gets_its_whole_reply(
        client, user_and_token, tmp_curio, alice_project, thinker, path):
    """The model thinks 6,000 tokens, past the cap's 4,096, then writes its
    reply. The turn ended with the line that it spent its whole limit
    thinking. Its first request is asked as before; the cap cuts it before a
    word, so it is asked again with the room, and the whole reply comes. Both
    requests' tokens are counted, and the record pins the room."""
    server = thinker((THOUGHT, REPLY))
    _, token = user_and_token
    attachment_id = _attach(client, token, alice_project)
    ended = _ended(client, token, alice_project, attachment_id, path)
    assert ended.get("reply") == REPLY, f"the model that thought {THOUGHT:,} tokens never answered: {ended!r}"
    assert "cutAtOutputLimit" not in ended
    assert server.round_caps == [CAP, WITH_ROOM]
    saved = _last_turn(client, token, alice_project, attachment_id)
    assert saved["text"] == REPLY
    execution = saved["execution"]
    assert "cutAtOutputLimit" not in execution and "thinkingRoomRefused" not in execution, execution
    assert execution["usage"] == _spent(CAP, THOUGHT + _ThinkingModel.tokens_of(REPLY))
    assert execution["pins"]["policy"] == {"maxOutputTokens": CAP, "thinkingTokens": ROOM}


@pytest.mark.parametrize("path", PATHS)
def test_a_model_seen_thinking_is_asked_with_the_room_from_then_on(
        client, user_and_token, tmp_curio, alice_project, thinker, path):
    """The model thinks 1,000 tokens, inside the cap, and answers whole: its
    server streamed the thinking, so its endpoint is seen thinking. Its next
    turn thinks 6,000 tokens and is asked with the room at once: one request,
    and the whole reply."""
    server = thinker((1000, "J and K are in."), (THOUGHT, REPLY))
    _, token = user_and_token
    attachment_id = _attach(client, token, alice_project)
    first = _ended(client, token, alice_project, attachment_id, path)
    assert first.get("reply") == "J and K are in.", first
    assert server.round_caps == [CAP]
    second = _ended(client, token, alice_project, attachment_id, path)
    assert second.get("reply") == REPLY, f"the second turn never answered: {second!r}"
    assert server.round_caps == [CAP, WITH_ROOM], "the endpoint seen thinking was not asked with the room at once"


@pytest.mark.parametrize("path", PATHS)
def test_a_model_that_thinks_past_the_room_still_says_it_was_cut(
        client, user_and_token, tmp_curio, alice_project, thinker, path):
    """The model thinks past the cap and the room together. It is asked again
    with the room and spends that thinking too: the turn ends with #1266's
    line, which names the whole limit the request carried, and holds nothing
    of the thinking."""
    server = thinker((ENDLESS, REPLY))
    _, token = user_and_token
    attachment_id = _attach(client, token, alice_project)
    ended = _ended(client, token, alice_project, attachment_id, path)
    assert ended.get("reply") == _message("turn.cut-while-thinking", limit=LIMIT_WITH_ROOM), ended
    assert ended.get("cutAtOutputLimit") is True
    assert server.round_caps == [CAP, WITH_ROOM]
    execution = _last_turn(client, token, alice_project, attachment_id)["execution"]
    assert execution.get("cutAtOutputLimit") is True
    assert execution["usage"] == _spent(CAP, WITH_ROOM)


@pytest.mark.parametrize("path", PATHS)
def test_a_model_that_does_not_think_is_asked_as_before(
        client, user_and_token, tmp_curio, alice_project, thinker, path):
    """No thinking: one request a turn, with the cap alone and no new field,
    the title call with its own 16 tokens, and each reply as it came. Passes
    without the fix too: a guard."""
    server = thinker((0, REPLY), (0, "Both bars are drawn."))
    _, token = user_and_token
    attachment_id = _attach(client, token, alice_project)
    first = _ended(client, token, alice_project, attachment_id, path)
    second = _ended(client, token, alice_project, attachment_id, path)
    assert (first.get("reply"), second.get("reply")) == (REPLY, "Both bars are drawn.")
    assert server.round_caps == [CAP, CAP]
    assert server.title_caps == [TITLE_CAP]
    for asked in server.requests:
        assert set(asked) == {"model", "messages", "stream", "stream_options", "max_tokens"}, sorted(asked)


# -- a delegate and the title ---------------------------------------------------

def test_a_delegate_on_a_model_that_thinks_gets_its_whole_reply(client, user_and_token, tmp_curio, thinker):
    """The Node Builder, attached to node n1, hands n1's code to its content
    mode, whose model thinks 6,000 tokens before the code. The delegate failed
    with the line that it spent its whole limit thinking, and its code was
    lost. Its request is asked again with the room and its code comes whole;
    the chat's next round is asked with the room from the start."""
    from utk_curio.backend.tests.test_agents import test_delegation as delegation_tests

    _, token = user_and_token
    project_id = delegation_tests._project(client, token)
    client.post(f"/api/agents/projects/{project_id}/install", json={"coord": delegation_tests.NB},
                headers=_auth(token))
    attachment_id = client.post(
        f"/api/agents/projects/{project_id}/attachments",
        json={"coord": delegation_tests.NB, "target": {"kind": "node", "targetId": "n1"}}, headers=_auth(token),
    ).get_json()["attachmentId"]
    code = "print('fixed')\n"
    server = thinker((0, delegation_tests._delegate_tail()), (THOUGHT, code), (0, "The print is fixed."))
    body = delegation_tests._run(client, token, project_id, attachment_id, message="fix the print").get_json()
    cut = _message("delegate.cut-while-thinking", coord=delegation_tests.NB, limit=LIMIT)
    entry = next((part for part in body.get("content") or [] if part["type"] == "delegation"), None)
    assert entry is not None and entry["status"] != "failed" and entry["summary"] != cut, (
        f"the delegate that thought {THOUGHT:,} tokens failed: {entry!r}")
    assert body.get("reply") == "The print is fixed.", body
    saved = _last_turn(client, token, project_id, attachment_id)
    (child,) = saved["execution"]["delegations"]
    assert (child["status"], child.get("cutAtOutputLimit")) == ("ok", None), child
    assert child["usage"] == _spent(CAP, THOUGHT + _ThinkingModel.tokens_of(code))
    assert server.round_caps == [CAP, CAP, WITH_ROOM, WITH_ROOM]


@pytest.mark.parametrize("turn_thinking, title_caps", [
    (THOUGHT, [TITLE_CAP + TITLE_ROOM]),
    (0, [TITLE_CAP, TITLE_CAP + TITLE_ROOM]),
], ids=["seen-thinking-in-its-turn", "seen-thinking-by-the-title"])
def test_a_model_that_thinks_names_its_conversation(
        client, user_and_token, tmp_curio, alice_project, thinker, turn_thinking, title_caps):
    """The title call asks for 16 tokens, which a model that thinks spends
    thinking: its conversation was never named. Seen thinking in the turn
    before, the title call is asked with its own small room at once; seen
    thinking only when the 16 tokens run out before a word, it is asked again
    with that room. Either way the conversation is named."""
    server = thinker((turn_thinking, REPLY), title_thinking=300)
    _, token = user_and_token
    attachment_id = _attach(client, token, alice_project)
    ended = _ended(client, token, alice_project, attachment_id, "run")
    assert ended.get("reply") == REPLY, ended
    listed = client.get(f"/api/agents/projects/{alice_project}/attachments", headers=_auth(token)).get_json()
    named = [record.get("title") for record in listed["attachments"] if record.get("attachmentId") == attachment_id]
    assert named == [TITLE], f"the conversation of a model that thinks is not named: {named!r}"
    assert server.title_caps == title_caps


# -- a server that refuses the room ---------------------------------------------

@pytest.mark.parametrize("protocol", ["fenced", "native"])
def test_a_server_that_refuses_the_room_is_asked_as_before(
        client, user_and_token, tmp_curio, alice_project, thinker, monkeypatch, protocol):
    """The server's context window holds the cap but not the room: it refuses
    the request that carries the room with a 400, as vLLM refuses one whose
    prompt and cap pass its window. The turn is asked again as before and
    says what it said before, that the model spent the cap thinking; its
    record says the room was refused. The refusal is never read as one of the
    native tools, which the account would remember and run fenced from then
    on, and the next turn is asked as before at once."""
    from utk_curio.backend.app.agents.repositories import model_catalog

    if protocol == "native":
        monkeypatch.setattr(providers, "probe_native_tools",
                            lambda config, usage_out=None: (True, "the model called the tool it was offered"))
    server = thinker((THOUGHT, REPLY), refuse_above=CAP)
    user, token = user_and_token
    attachment_id = _attach(client, token, alice_project)
    ended = _ended(client, token, alice_project, attachment_id, "run")
    assert ended.get("reply") == _message("turn.cut-while-thinking", limit=LIMIT), ended
    execution = _last_turn(client, token, alice_project, attachment_id)["execution"]
    assert execution.get("thinkingRoomRefused") is True, f"the record does not say the room was refused: {execution!r}"
    assert (execution["pins"].get("toolProtocol"), execution["pins"].get("nativeToolsRefused")) == (protocol, None)
    assert server.round_caps == [CAP, WITH_ROOM, CAP]
    _ended(client, token, alice_project, attachment_id, "run")
    assert server.round_caps == [CAP, WITH_ROOM, CAP, CAP], "the endpoint that refused the room was asked with it again"
    if protocol == "native":
        endpoint = server.config()
        remembered = model_catalog.remembered_chat_capabilities(
            _user_dir_key(user), endpoint.api_type, endpoint.base_url, endpoint.model)
        assert (remembered or {}).get("tools") is True, f"the room's refusal was read as the tools': {remembered!r}"


# -- Anthropic and Gemini -------------------------------------------------------

class _Claude:
    """Claude 5 and later as Anthropic's SDK gives a turn of it: the model
    thinks first, by default, its thinking's text left out of the reply (a
    ``thinking`` block holding none), and the thinking counts toward
    ``max_tokens``."""

    def __init__(self, thinking: int, reply: str):
        self.thinking = thinking
        self.reply = reply
        self.caps: list[int] = []

    def _answer(self, max_tokens: int):
        self.caps.append(max_tokens)
        blocks = [types.SimpleNamespace(type="thinking", thinking="", signature="sig")]
        whole = _ThinkingModel.tokens_of(self.reply)
        if max_tokens < self.thinking + whole:
            spent, reason = max_tokens, "max_tokens"
            if max_tokens > self.thinking:
                cut = self.reply[:(max_tokens - self.thinking) * _ThinkingModel.CHARS]
                blocks.append(types.SimpleNamespace(type="text", text=cut))
        else:
            spent, reason = self.thinking + whole, "end_turn"
            blocks.append(types.SimpleNamespace(type="text", text=self.reply))
        usage = types.SimpleNamespace(input_tokens=PROMPT, output_tokens=spent,
                                      cache_read_input_tokens=None, cache_creation_input_tokens=None)
        return types.SimpleNamespace(content=blocks, stop_reason=reason, usage=usage)

    def module(self):
        claude = self

        class _Stream:
            def __init__(self, message):
                self.message = message
                self.text_stream = iter([block.text for block in message.content if block.type == "text"])

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def get_final_message(self):
                return self.message

        messages = types.SimpleNamespace(create=lambda **kwargs: claude._answer(kwargs["max_tokens"]),
                                         stream=lambda **kwargs: _Stream(claude._answer(kwargs["max_tokens"])))
        return types.SimpleNamespace(Anthropic=lambda **kwargs: types.SimpleNamespace(messages=messages),
                                     NOT_GIVEN="NG")


class _GeminiReply:
    """A Gemini reply as google.generativeai 0.8.6 gives it: its parts, its
    finish reason, its usage, and the SDK's text accessor, which raises on a
    reply with no part."""

    def __init__(self, text: str, reason, tokens: int):
        parts = [types.SimpleNamespace(text=text)] if text else []
        self.candidates = [types.SimpleNamespace(content=types.SimpleNamespace(parts=parts), finish_reason=reason)]
        self.usage_metadata = types.SimpleNamespace(prompt_token_count=PROMPT, candidates_token_count=tokens,
                                                    cached_content_token_count=None)

    @property
    def text(self) -> str:
        parts = self.candidates[0].content.parts
        if not parts:
            raise ValueError("Invalid operation: The `response.text` quick accessor requires the response to "
                             "contain a valid `Part`, but none were returned.")
        return "".join(part.text for part in parts)


class _Gemini:
    """Gemini 2.5 and later as google.generativeai gives a turn of it: the
    model thinks first, its thoughts counted against ``max_output_tokens``,
    and the SDK Curio ships (0.8.6) shows nothing of them, so a reply the cap
    cut while the model still thought has no part at all."""

    def __init__(self, thinking: int, reply: str):
        self.thinking = thinking
        self.reply = reply
        self.caps: list[int] = []

    def _answer(self, cap: int) -> _GeminiReply:
        self.caps.append(cap)
        whole = _ThinkingModel.tokens_of(self.reply)
        if cap < self.thinking + whole:
            written = max(0, cap - self.thinking)
            return _GeminiReply(self.reply[:written * _ThinkingModel.CHARS], _FinishReason.MAX_TOKENS, written)
        return _GeminiReply(self.reply, _FinishReason.STOP, whole)

    def modules(self):
        gemini = self

        class _Chat:
            def send_message(self, message, stream=False, **kwargs):
                reply = gemini._answer(kwargs["generation_config"]["max_output_tokens"])
                return iter([reply]) if stream else reply

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
        return google, fake


def _turn_on(cfg: ProviderConfig, path: str, usage: dict):
    """The turn *cfg*'s model answers :data:`MESSAGE` with on *path*, offered
    the room, as ``(text, stop reason, the cap its answer carried)``, or the
    error it raised as a value."""
    asked = [{"role": "user", "content": MESSAGE}]
    if path == "whole":
        turn = _outcome(lambda: providers.run_chat_turn(cfg, asked, CAP, usage, thinking_tokens=ROOM))
        if not isinstance(turn, ChatTurn):
            return turn
        return turn.text, turn.stop_reason, turn.output_limit
    finish: dict = {}
    events = _outcome(lambda: list(providers.stream_chat_turn(cfg, asked, CAP, usage, finish=finish,
                                                              thinking_tokens=ROOM)))
    if not isinstance(events, list):
        return events
    return "".join(event for event in events if isinstance(event, str)), finish.get("reason"), finish.get("limit")


@pytest.mark.parametrize("path", ["whole", "streamed"])
def test_claude_that_thinks_past_the_cap_gets_its_whole_reply(monkeypatch, path):
    """Claude 5 and later think by default, and their thinking counts toward
    ``max_tokens``: past the cap, the reply came back with no text, cut. The
    reply holds a thinking block and nothing else, so it is asked again with
    the room, and both requests' tokens are counted."""
    claude = _Claude(THOUGHT, REPLY)
    monkeypatch.setitem(sys.modules, "anthropic", claude.module())
    cfg = ProviderConfig(api_key="k", api_type="anthropic", base_url="", model="claude-opus-5-5")
    usage: dict = {}
    outcome = _turn_on(cfg, path, usage)
    assert outcome == (REPLY, "end_turn", WITH_ROOM), f"the turn of a Claude that thinks ended with {outcome!r}"
    assert claude.caps == [CAP, WITH_ROOM]
    assert usage == _spent(CAP, THOUGHT + _ThinkingModel.tokens_of(REPLY))


@pytest.mark.parametrize("path", ["whole", "streamed"])
def test_gemini_that_thinks_past_the_cap_gets_its_whole_reply(monkeypatch, path):
    """Gemini 2.5 and later count their thoughts against
    ``max_output_tokens``: past the cap, the reply had no part, and reading
    its text raised. A reply the cap cut before a word is asked again with
    the room."""
    gemini = _Gemini(THOUGHT, REPLY)
    google, fake = gemini.modules()
    monkeypatch.setitem(sys.modules, "google", google)
    monkeypatch.setitem(sys.modules, "google.generativeai", fake)
    cfg = ProviderConfig(api_key="k", api_type="gemini", base_url="", model="gemini-2.5-pro")
    outcome = _turn_on(cfg, path, {})
    assert outcome == (REPLY, "STOP", WITH_ROOM), f"the turn of a Gemini that thinks ended with {outcome!r}"
    assert gemini.caps == [CAP, WITH_ROOM]


# -- the evaluations' record ----------------------------------------------------

def test_an_evaluation_run_records_each_model_call():
    """The skill evaluations' worker records each model call of a run in its
    run.json: its output tokens, the cap its answer carried, whether its
    model's thinking came apart, whether the cap cut it and whether its
    server refused the room, so a live run shows how long the model thought,
    call by call."""
    from utk_curio.tools import skill_eval_worker

    record = getattr(skill_eval_worker, "_model_call", None)
    assert callable(record), "the worker records no model call of its own"
    whole = ChatTurn(text=REPLY, stop_reason="stop", thinking=True, output_limit=WITH_ROOM)
    cut = ChatTurn(text="", stop_reason="length", thinking=True, output_limit=WITH_ROOM)
    refused = ChatTurn(text="", stop_reason="length", thinking=True, output_limit=CAP, thinking_room_refused=True)
    assert record({"inputTokens": 2 * PROMPT, "outputTokens": CAP + 6034}, whole) == {
        "outputTokens": CAP + 6034, "outputLimit": WITH_ROOM, "thinking": True}
    assert record({"outputTokens": CAP + WITH_ROOM}, cut) == {
        "outputTokens": CAP + WITH_ROOM, "outputLimit": WITH_ROOM, "thinking": True, "cut": True}
    assert record({"outputTokens": 2 * CAP}, refused) == {
        "outputTokens": 2 * CAP, "outputLimit": CAP, "thinking": True, "cut": True, "thinkingRoomRefused": True}
    assert record({}, ChatTurn(text="ok", stop_reason="stop")) == {}
