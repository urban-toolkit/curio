"""Provider-neutral chat-completion port.

This is the one place raw LLM-provider SDKs are used, so LLM/provider behavior
stays out of the route/flow/node modules (the ``agents/`` ownership boundary in
the plan's module-encapsulation memo). Callers resolve a :class:`ProviderConfig`
(``provider_config.resolve_llm``: an LLM configuration, the Deployment default
or the guest configuration) and hand it to :func:`run_chat_turn`; they never
import ``openai`` / ``anthropic`` / ``google.generativeai`` directly.

A turn is typed (:class:`ChatTurn`), and a run loop takes one from
:func:`run_chat_turn` or :func:`stream_chat_turn`. :func:`run_chat_completion`
and :func:`stream_chat_completion` are their text-only forms.

**The system turn.** A message list is OpenAI-shaped (``[{"role",
"content"}]``). A system message built by ``contracts.system_message`` also
carries its ``slots`` (preamble, instruction, configuration, tool protocol,
runtime blocks), and each provider receives them its own way: Anthropic as one
text block per slot with the preamble marked cacheable, Gemini as a list of
system instructions, and an OpenAI-compatible server as the one joined system
message (some local chat templates reject several). A system message without
slots is sent as its text, as it always was.

**Usage.** ``inputTokens`` counts every input token, cached or not, on every
provider (Anthropic reports cache reads and writes apart from its input
count). ``cacheReadTokens`` and ``cacheWriteTokens`` are added when the
provider reports them.

**Native tools.** ``tools`` offers the model tools, each ``{name, description,
parameters}`` (``tools.native_tools``), and ``tool_choice`` is ``"auto"`` or
``"none"``. The turn then carries the calls the model made
(:class:`ToolCall`). The conversation stays one list with two more message
shapes: an assistant message may carry ``tool_calls`` (``[{id, name,
arguments}]``), and a ``{"role": "tool", "tool_call_id", "name", "content",
"is_error"}`` message answers one call. Each provider receives them its own way:
OpenAI's ``tool_calls`` and ``tool`` messages, Anthropic's ``tool_use`` and
``tool_result`` blocks, Gemini's function calls and responses. Gemini's schema
has no open objects, so an object whose keys a tool does not fix is offered as
a JSON string and read back as an object. An endpoint that answers a request
offering tools with a 400 or 422 raises :class:`NativeToolsRefused`, and the
run carries on with the fenced protocol. Without ``tools`` a request is exactly
what it was before tools existed.

**A reply schema.** ``reply_schema`` (``{name, schema}``, from
``reply_schemas``) holds the reply to a JSON schema: OpenAI's strict
``json_schema`` ``response_format``, Anthropic's ``output_config.format``. The
schema arrives already in the provider's flavor. An endpoint that answers such a
request with a 400 or 422 raises :class:`ReplySchemaRefused`, and the caller asks
again without one.

**An OpenAI-compatible turn is always streamed.** A server answers a request
that is not streamed only once the model has written the whole reply, and a
proxy before the server may cut a request that has sent nothing back for a
while (nginx cuts one silent for 60 s by default). A reply that took longer to
write then never arrived, and the SDK asked again twice, so the model wrote it
three times before the call failed with "Connection error.". So
:func:`run_chat_turn` asks for the same stream :func:`stream_chat_turn` reads,
whose pieces keep the connection busy while the model writes, and puts the turn
together from it. A stream that ends with no finish reason was cut: the turn
raises :class:`ReplyCutShort` rather than pass a part of the reply off as all
of it, whether it was asked for whole or streamed.

**A server that stops sending.** A server may stop feeding a stream it has
begun and leave the connection open, and the SDK alone waits 600 s for each
read. So every read of an OpenAI-compatible request waits at most
:data:`FIRST_CHUNK_S`, which bounds the wait for the answer's first chunk while
the server reads a long prompt in; once a chunk has come, a stream that sends
nothing for :data:`STREAM_SILENCE_S` is ended (:class:`_Silence`). Either
raises :class:`ServerStoppedSending`, whose message says the model's server
stopped sending, and for how long. The SDK sends the request once:
:func:`_ask_for_stream` sends it again when the server turned it down (a
refused or dropped connection, a 429, a 5xx other than a 504), never after a
read waited out :data:`FIRST_CHUNK_S`, and nothing is sent again once the
answer has begun.

**A turn the output cap cut.** A turn carries its provider's stop reason
(``ChatTurn.stop_reason``), on both paths: :func:`stream_chat_turn` writes it,
once the stream has ended, into the ``finish`` dict its caller hands it, as
:func:`run_chat_turn` reads it into its turn. A model that stopped because the
turn reached its output cap (``max_output_tokens``) says so by that reason: an
OpenAI-compatible server's ``length``, Anthropic's ``max_tokens``, Gemini's
``MAX_TOKENS``; its text and calls are then only the start of its reply
(``ChatTurn.cut_at_output_cap``). This module only reports it; what the reply
then says is the run's (``turns/turn_loop.py``, ``delegation.py``). A server
that streams the model's thinking apart from its reply (an OpenAI-compatible
delta's ``reasoning_content`` or ``reasoning``, as vLLM's reasoning parsers,
Ollama and DeepSeek send it) never has it read as the reply: the turn notes
only that it came (``ChatTurn.thinking``), so a turn that spent its cap
thinking can say so.

**A model that thinks.** A model's thinking may count against the turn's
output cap: vLLM counts gemma4's, Gemini 2.5 and later count their thoughts,
and Anthropic counts Claude's, which is on by default from Claude 5. Such a
model can spend the whole cap thinking before it writes a word of its reply.
So a caller may offer ``thinking_tokens``, the room a model that thinks gets
on top of the cap (a run's turns and delegates, and the title, do). An
endpoint whose model was seen thinking is asked for ``max_output_tokens +
thinking_tokens`` from then on in this process (:func:`_room_for`). It is seen
thinking by its stream's thinking, by an Anthropic thinking block, or by a
reply the cap cut before it wrote anything, whose tokens went to output that
does not show. A reply the cap cut before it wrote anything, asked without the
room, is asked again once with it: nothing of it reached the caller, which
sees only the second, and the tokens of both are counted. A model that never
thinks is asked as before. A request given the room that its server refuses
(a 400 or a 422, such as a context window the room does not fit in) is asked
again without it, and that endpoint gets no room again in this process; the
turn says so (``ChatTurn.thinking_room_refused``), and the refusal is never
read as one of the tools or the reply schema. ``ChatTurn.output_limit`` is the
cap the request that answered carried.

**The native-tools trial.** :func:`probe_native_tools` asks an
OpenAI-compatible endpoint whether its model calls tools natively, as a turn
is asked: one request offering one tool, streamed through the same reading
of thinking, calls and finish reasons, with the room a model that thinks
gets. Only its sizes are its own: a cap of :data:`TRIAL_MAX_TOKENS`, a room
of :data:`TRIAL_THINKING_TOKENS`, and reads that wait at most
:data:`TRIAL_WAIT_S`, since it runs before the run's first call. A trial its
limit still cut before a call answers nothing about the tools.

The dispatch below was extracted verbatim from ``app/api/routes.py::_call_llm``
(behavior-preserving) and is the seam a future LangChain adapter would sit behind.

User-facing overview: ``docs/AGENT-CATALOG.md``.
"""

from __future__ import annotations

import json
import socket
import threading
import time
import uuid
from dataclasses import dataclass, field, replace

from utk_curio.backend.app.agents.domain import agent_text


class NativeToolsRefused(RuntimeError):
    """The endpoint refused a request that offered native tools (a 400 or a
    422). The message is the endpoint's reason, with the key taken out."""


class ReplySchemaRefused(RuntimeError):
    """The endpoint refused a request that carried a reply schema (a 400 or a
    422). The message is the endpoint's reason, with the key taken out."""


class ReplyCutShort(RuntimeError):
    """The endpoint's stream ended before the model finished its reply: no
    finish reason came. What arrived is only a part of the reply, so a caller
    that waits for the whole turn gets this instead, and a streamed turn
    raises it after its last piece."""


class ServerStoppedSending(RuntimeError):
    """The model's server stopped sending: an OpenAI-compatible request that
    got no chunk of its answer for :data:`FIRST_CHUNK_S`, or a stream that sent
    nothing for :data:`STREAM_SILENCE_S` once a chunk had come. The message
    says which, and for how long; :func:`says_server_stopped_sending` finds it
    in the error a run answered."""


#: The stop reasons that say the model stopped because the turn reached its
#: output cap: an OpenAI-compatible server's ``length``, Anthropic's
#: ``max_tokens`` and Gemini's ``MAX_TOKENS`` (its finish reason's name).
_OUTPUT_CAP_STOP_REASONS = frozenset({"length", "max_tokens", "MAX_TOKENS"})

#: How long one read of an OpenAI-compatible request may wait: for the first
#: chunk of its answer, while the server reads a long prompt in, and, where no
#: silence can be watched, between two chunks. A proxy before the server cuts
#: sooner (nginx: 60 s of silence); a slow local server reading a long prompt
#: in may need minutes.
FIRST_CHUNK_S = 300.0
#: How long a stream may send nothing once a chunk has come. A healthy stream
#: sends a chunk every fraction of a second (a live vLLM stream at 47 tokens a
#: second was never silent for more than 1.1 s); a server that holds a whole
#: reply back until it ends, as a tool parser may hold a call, sends within the
#: time the model takes to write it: 87 s for the 4,096-token output cap at
#: that pace.
STREAM_SILENCE_S = 120.0
#: How long connecting may take: the SDK's own limit.
_CONNECT_S = 5.0
#: The waits before each new try of a request its server turned down at once
#: (:func:`_ask_for_stream`): the SDK's own first two.
_RESEND_WAITS_S = (0.5, 1.0)
#: The longest wait a server's ``retry-after`` may ask for: the SDK's own.
_RETRY_AFTER_MAX_S = 60.0

#: The endpoints whose model was seen thinking in this process, and those
#: whose server refused a request given room for it, each as
#: ``(api_type, base_url, model)`` (see the module docstring).
_thinking_endpoints: set[tuple[str, str, str]] = set()
_room_refused: set[tuple[str, str, str]] = set()
_thinking_lock = threading.Lock()


@dataclass(frozen=True)
class ProviderConfig:
    """Resolved, provider-neutral connection config for one chat completion.

    ``api_type`` selects the backend: ``"anthropic"``, ``"gemini"``, or
    ``"openai_compatible"`` (the default, used by OpenAI, the aiconn sage200
    endpoint, Ollama, vLLM, etc.). ``base_url`` applies only to the
    openai-compatible backend; the others ignore it.

    The rest say where the config came from (``provider_config.resolve_llm``):
    the LLM configuration's id and label, and ``source`` (``default``,
    ``deployment`` or ``guest``). ``on_deployment`` is True when it runs on
    this Curio's own endpoint, whose host never leaves the server. The key and
    the URL are left out of the repr, so a logged config never shows them.
    """

    api_key: str = field(repr=False)
    api_type: str
    base_url: str = field(repr=False)
    model: str
    config_id: str | None = None
    label: str = ""
    source: str = ""
    on_deployment: bool = False


def redacted_text(text: object, config: ProviderConfig | None) -> str:
    """Provider error text without the call's own key, and without any of
    this Curio's own endpoints: their keys, their URLs, their hosts and ports,
    or their hosts. For any message that is persisted, streamed, logged or
    returned."""
    from utk_curio.backend import config as settings
    from utk_curio.common.llm_endpoint import redact_endpoints
    from utk_curio.common.redaction import redact

    endpoints = tuple(settings.DEFAULT_LLM_ENDPOINTS or ())
    message = str(text)
    keys = {"llm-api-key": config.api_key if config is not None else ""}
    for number, endpoint in enumerate(endpoints, start=1):
        keys[f"llm-deployment-key-{number}"] = endpoint.api_key
    message = redact(message, {name: value for name, value in keys.items() if value}) or message
    return redact_endpoints(message, (endpoint.base_url for endpoint in endpoints))


def _redacted(exc: BaseException, config: ProviderConfig) -> str:
    """SDK error text as :func:`redacted_text` leaves it."""
    return redacted_text(exc, config)


@dataclass(frozen=True)
class ToolCall:
    """A tool the model asked for natively: the provider's call id, the tool's
    name and its arguments. Never persisted: a session keeps role and text, so
    an agent can move to another LLM mid-conversation."""

    id: str
    name: str
    arguments: dict = field(default_factory=dict)
    #: Why the arguments could not be read (not JSON, not an object), or "".
    error: str = ""


def _call_from_json(call_id: str, name: str, raw: str) -> ToolCall:
    """A call whose arguments arrived as JSON text (OpenAI's form)."""
    if not (raw or "").strip():
        return ToolCall(call_id, name, {})
    try:
        arguments = json.loads(raw)
    except ValueError as exc:
        return ToolCall(call_id, name, {}, error=agent_text.message("request.call-arguments-not-json", exc=exc))
    if not isinstance(arguments, dict):
        return ToolCall(call_id, name, {}, error=agent_text.message("request.call-arguments-not-json-object"))
    return ToolCall(call_id, name, arguments)


def _call_id() -> str:
    """An id for a call whose provider names none (Gemini)."""
    return f"call-{uuid.uuid4().hex[:12]}"


@dataclass(frozen=True)
class ChatTurn:
    """One model turn: its text, the native tool calls it made (none while no
    tools are offered), the provider's stop reason, and whether the endpoint
    sent the model's thinking apart from its reply (``thinking``; the text
    never holds it). ``output_limit`` is the output cap the request that
    answered carried, the room for thinking included (0 when no cap was
    asked, or for a turn no provider made), and ``thinking_room_refused``
    says the server refused that room, so the turn was asked without it (see
    the module docstring). Those two say how the turn was asked, not what it
    holds, so two turns that hold the same are equal whatever they say."""

    text: str
    tool_calls: tuple = ()
    stop_reason: str = ""
    thinking: bool = False
    output_limit: int = field(default=0, compare=False)
    thinking_room_refused: bool = field(default=False, compare=False)

    @property
    def cut_at_output_cap(self) -> bool:
        """Whether the model stopped because the turn reached its output cap
        (``max_output_tokens``): its text and calls are then only the start
        of its reply. A turn with no stop reason, such as a scripted one, is
        whole."""
        return self.stop_reason in _OUTPUT_CAP_STOP_REASONS

    @classmethod
    def of(cls, value) -> "ChatTurn":
        """*value* as a turn. A bare string is a text-only turn: what a
        fenced-protocol reply is, and what a scripted test fake returns."""
        if isinstance(value, ChatTurn):
            return value
        return cls(text="" if value is None else str(value))


def _capture_usage(usage_out: dict | None, input_tokens, output_tokens, *,
                   cache_read=None, cache_write=None) -> None:
    """Record Actual token usage into the caller's sink (memo dev/37).

    Best-effort: only populated when the provider reports both counts; the sink
    stays empty otherwise. Never estimated (memo dev/11's labeling rule). The
    cache counts are added when reported."""
    if usage_out is None:
        return
    if isinstance(input_tokens, int) and isinstance(output_tokens, int):
        usage_out["inputTokens"] = input_tokens
        usage_out["outputTokens"] = output_tokens
        if isinstance(cache_read, int):
            usage_out["cacheReadTokens"] = cache_read
        if isinstance(cache_write, int):
            usage_out["cacheWriteTokens"] = cache_write


def _anthropic_usage(usage_out: dict | None, usage) -> None:
    """Anthropic's ``input_tokens`` leaves out cache reads and writes; the
    record's ``inputTokens`` is every input token, as for the others."""
    if usage is None:
        return
    base = getattr(usage, "input_tokens", None)
    read = getattr(usage, "cache_read_input_tokens", None)
    write = getattr(usage, "cache_creation_input_tokens", None)
    total = base
    if isinstance(base, int):
        total = base + sum(n for n in (read, write) if isinstance(n, int))
    _capture_usage(usage_out, total, getattr(usage, "output_tokens", None),
                   cache_read=read, cache_write=write)


def _openai_usage(usage_out: dict | None, usage) -> None:
    """``prompt_tokens`` already counts cached input; the cached part is in
    ``prompt_tokens_details.cached_tokens`` when the server says."""
    if usage is None:
        return
    details = getattr(usage, "prompt_tokens_details", None)
    _capture_usage(
        usage_out, getattr(usage, "prompt_tokens", None), getattr(usage, "completion_tokens", None),
        cache_read=getattr(details, "cached_tokens", None) if details is not None else None,
    )


def _gemini_usage(usage_out: dict | None, meta) -> None:
    if meta is None:
        return
    _capture_usage(
        usage_out, getattr(meta, "prompt_token_count", None),
        getattr(meta, "candidates_token_count", None),
        cache_read=getattr(meta, "cached_content_token_count", None),
    )


def _has_slots(messages: list) -> bool:
    return any(m.get("role") == "system" and m.get("slots") for m in messages)


def _system_parts(messages: list) -> list[tuple[str, str]]:
    """``(kind, text)`` for the system turn: a system message's slots when it
    carries them, else its text as one part with no kind."""
    parts: list[tuple[str, str]] = []
    for m in messages:
        if m.get("role") != "system":
            continue
        slots = m.get("slots")
        if slots:
            parts.extend(
                (str(slot.get("kind") or ""), str(slot.get("text") or ""))
                for slot in slots if slot.get("text")
            )
        elif m.get("content"):
            parts.append(("", m["content"]))
    return parts


#: The slots a system turn opens with that an agent's runs share
#: (``contracts.compose_system``): the end of the last is the first place
#: Anthropic caches the turn up to.
_SHARED_SLOTS = ("preamble", "skill-catalog")
#: The slot of the skills a run is handed: the end of it is the second place.
_SKILLS_SLOT = "skills"


def _cache_breakpoints(kinds: list[str]) -> list[int]:
    """Which of the system turn's blocks, by their slots' *kinds*, end a part
    Anthropic caches: the last of the slots an agent's runs share, the
    longest part every run of the agent repeats, and the skills a run is
    handed, which every run on the same kind of node repeats."""
    shared = [at for at, kind in enumerate(kinds) if kind in _SHARED_SLOTS]
    handed = [at for at, kind in enumerate(kinds) if kind == _SKILLS_SLOT]
    return sorted({*shared[-1:], *handed[-1:]})


def _anthropic_system(messages: list, not_given):
    """Anthropic's ``system``: a text block per slot, with a cache breakpoint
    after the slots an agent's runs share and a second after the skills a run
    is handed (:func:`_cache_breakpoints`); without slots, the joined text as
    before."""
    parts = _system_parts(messages)
    if not parts:
        return not_given
    if not _has_slots(messages):
        return "\n".join(text for _, text in parts)
    blocks = [{"type": "text", "text": text} for _, text in parts]
    for at in _cache_breakpoints([kind for kind, _ in parts]):
        blocks[at]["cache_control"] = {"type": "ephemeral"}
    return blocks


def _gemini_system(messages: list):
    """Gemini's ``system_instruction``: a list of the slots' texts, or the
    joined text of a system turn without slots."""
    parts = _system_parts(messages)
    if not parts:
        return None
    if not _has_slots(messages):
        return "\n".join(text for _, text in parts)
    return [text for _, text in parts]


def _without_slots(message: dict) -> dict:
    return {k: v for k, v in message.items() if k != "slots"}


def _openai_message(m: dict) -> dict:
    if m.get("role") == "tool":
        # No error flag in OpenAI's shape: the content says the status.
        return {"role": "tool", "tool_call_id": m.get("tool_call_id") or "", "content": m.get("content") or ""}
    if m.get("role") == "assistant" and m.get("tool_calls"):
        return {
            "role": "assistant",
            # Empty rather than null: some local chat templates concatenate it.
            "content": m.get("content") or "",
            "tool_calls": [
                {
                    "id": call["id"],
                    "type": "function",
                    "function": {"name": call["name"], "arguments": json.dumps(call.get("arguments") or {})},
                }
                for call in m["tool_calls"]
            ],
        }
    return _without_slots(m)


def _openai_messages(messages: list) -> list:
    """The list as an OpenAI-compatible server takes it: one system message,
    its slots left behind (its content is their joined text)."""
    return [_openai_message(m) for m in messages]


def _chat_messages(messages: list) -> list:
    """The conversation without the system turn, for Anthropic and Gemini."""
    return [_without_slots(m) for m in messages if m.get("role") != "system"]


def _anthropic_messages(messages: list) -> list:
    """The conversation as Anthropic takes it: a call is a ``tool_use`` block
    of its assistant turn, and the results of one turn's calls are the
    ``tool_result`` blocks of the user turn that follows."""
    out: list = []
    for m in _chat_messages(messages):
        if m.get("role") == "tool":
            block = {"type": "tool_result", "tool_use_id": m.get("tool_call_id") or "",
                     "content": m.get("content") or ""}
            if m.get("is_error"):
                block["is_error"] = True
            if out and out[-1]["role"] == "user" and isinstance(out[-1]["content"], list):
                out[-1]["content"].append(block)
            else:
                out.append({"role": "user", "content": [block]})
        elif m.get("role") == "assistant" and m.get("tool_calls"):
            blocks = [{"type": "text", "text": m["content"]}] if m.get("content") else []
            blocks.extend(
                {"type": "tool_use", "id": call["id"], "name": call["name"],
                 "input": call.get("arguments") or {}}
                for call in m["tool_calls"]
            )
            out.append({"role": "assistant", "content": blocks})
        else:
            out.append(m)
    return out


def _anthropic_tools(tools: list) -> list:
    return [
        {"name": t["name"], "description": t["description"], "input_schema": t["parameters"]}
        for t in tools
    ]


def _openai_tools(tools: list) -> list:
    return [
        {"type": "function", "function": {
            "name": t["name"], "description": t["description"], "parameters": t["parameters"],
        }}
        for t in tools
    ]


def _open_object(schema: dict) -> bool:
    """An object whose keys the schema does not fix."""
    return schema.get("type") == "object" and not schema.get("properties")


def _gemini_schema(schema: dict) -> dict:
    """*schema* in the subset a Gemini function declaration takes: types,
    descriptions, string enums, items, properties and required keys. Gemini's
    schema has no open objects, so one is offered as a JSON string
    (:func:`_gemini_arguments` reads it back)."""
    if _open_object(schema):
        description = schema.get("description") or ""
        return {"type": "string", "description": (
            f"{description} Write it as a JSON object in a string.".strip()
        )}
    kind = schema.get("type") or "string"
    out: dict = {"type": kind}
    if schema.get("description"):
        out["description"] = schema["description"]
    if kind == "string" and schema.get("enum"):
        out["enum"] = [str(v) for v in schema["enum"]]
        out["format"] = "enum"
    if kind == "array":
        out["items"] = _gemini_schema(schema.get("items") or {"type": "string"})
    if kind == "object":
        out["properties"] = {k: _gemini_schema(v) for k, v in schema["properties"].items()}
        required = [k for k in schema.get("required") or () if k in out["properties"]]
        if required:
            out["required"] = required
    return out


def _gemini_tools(tools: list) -> list:
    declarations = []
    for t in tools:
        declaration = {"name": t["name"], "description": t["description"]}
        if (t.get("parameters") or {}).get("properties"):
            declaration["parameters"] = _gemini_schema(t["parameters"])
        declarations.append(declaration)
    return [{"function_declarations": declarations}]


def _gemini_arguments(value, schema):
    """A Gemini call's arguments as the tool's own schema reads them: a JSON
    string sent for an open object is parsed back into it."""
    if not isinstance(schema, dict):
        return value
    if _open_object(schema):
        if isinstance(value, str):
            try:
                return json.loads(value)
            except ValueError:
                return value  # left for the reader to refuse, with the reason
        return value
    if schema.get("type") == "object" and isinstance(value, dict):
        properties = schema.get("properties") or {}
        return {k: _gemini_arguments(v, properties.get(k)) for k, v in value.items()}
    if schema.get("type") == "array" and isinstance(value, list):
        return [_gemini_arguments(v, schema.get("items")) for v in value]
    return value


def _plain(value):
    """A protobuf map or list (Gemini's call arguments) as plain Python. A
    number arrives as a float, so a whole one is read back as an int."""
    if isinstance(value, (str, bytes, bool)) or value is None:
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else value
    if hasattr(value, "items"):
        return {str(k): _plain(v) for k, v in value.items()}
    try:
        return [_plain(v) for v in value]
    except TypeError:
        return value


def _gemini_contents(messages: list) -> list:
    """The conversation as Gemini contents: a call is a ``function_call`` part
    of its model turn, and one turn's results are the ``function_response``
    parts of the user turn that follows. Text turns are what they always were."""
    contents: list = []
    for m in _chat_messages(messages):
        if m.get("role") == "tool":
            key = "error" if m.get("is_error") else "result"
            part = {"function_response": {"name": m.get("name") or "",
                                          "response": {key: m.get("content") or ""}}}
            last = contents[-1] if contents else None
            if last is not None and last["role"] == "user" and all(
                isinstance(p, dict) and "function_response" in p for p in last["parts"]
            ):
                last["parts"].append(part)
            else:
                contents.append({"role": "user", "parts": [part]})
        elif m.get("role") == "assistant" and m.get("tool_calls"):
            parts: list = [m["content"]] if m.get("content") else []
            parts.extend(
                {"function_call": {"name": call["name"], "args": call.get("arguments") or {}}}
                for call in m["tool_calls"]
            )
            contents.append({"role": "model", "parts": parts})
        else:
            role = "user" if m["role"] == "user" else "model"
            contents.append({"role": role, "parts": [m["content"]]})
    return contents


def _gemini_turn(messages: list):
    """``(history, message)`` for a Gemini chat: every content but the last,
    and the last as ``send_message`` takes it (its text, for a text turn)."""
    contents = _gemini_contents(messages)
    if not contents:
        return [], ""
    *history, last = contents
    if len(last["parts"]) == 1 and isinstance(last["parts"][0], str):
        return history, last["parts"][0]
    return history, last


def _anthropic_text(resp) -> str:
    return "".join(
        getattr(block, "text", "") or ""
        for block in getattr(resp, "content", None) or []
        if getattr(block, "type", "text") == "text"
    )


def _anthropic_thinking(resp) -> bool:
    """Whether an Anthropic reply holds thinking: a ``thinking`` block (its
    text left out unless asked for, as on Claude 5 and later) or a
    ``redacted_thinking`` one."""
    return any(
        getattr(block, "type", "") in ("thinking", "redacted_thinking")
        for block in getattr(resp, "content", None) or []
    )


def _anthropic_calls(resp) -> tuple:
    calls = []
    for block in getattr(resp, "content", None) or []:
        if getattr(block, "type", "") != "tool_use":
            continue
        arguments = getattr(block, "input", None)
        calls.append(ToolCall(
            str(getattr(block, "id", "") or _call_id()), str(getattr(block, "name", "") or ""),
            dict(arguments) if isinstance(arguments, dict) else {},
            error="" if isinstance(arguments, dict) else agent_text.message("request.call-arguments-not-object"),
        ))
    return tuple(calls)


def _gemini_parts(response) -> list:
    candidates = getattr(response, "candidates", None) or []
    content = getattr(candidates[0], "content", None) if candidates else None
    return list(getattr(content, "parts", None) or [])


def _gemini_text(response) -> str:
    """The text parts of a Gemini reply. ``response.text`` raises when a part
    is a function call, so the parts are read one by one when they are there.
    It raises too on a reply with no part at all, such as one the cap cut
    while the model still thought (Gemini 2.5 and later think, and their
    thoughts count against the cap), which holds no text."""
    parts = _gemini_parts(response)
    if parts:
        return "".join(getattr(part, "text", "") or "" for part in parts)
    try:
        return getattr(response, "text", "") or ""
    except ValueError:
        return ""


def _gemini_stop_reason(response) -> str:
    """The first candidate's finish reason by its name (``MAX_TOKENS``), or
    "" when it names none. The reason is an enum whose text is its number, so
    its name is read."""
    candidates = getattr(response, "candidates", None) or []
    reason = getattr(candidates[0], "finish_reason", None) if candidates else None
    if reason is None:
        return ""
    return str(getattr(reason, "name", None) or reason)


def _gemini_calls(response, tools: list | None) -> tuple:
    schemas = {t["name"]: t.get("parameters") for t in tools or ()}
    calls = []
    for part in _gemini_parts(response):
        function_call = getattr(part, "function_call", None)
        name = str(getattr(function_call, "name", "") or "") if function_call is not None else ""
        if not name:
            continue
        arguments = _plain(getattr(function_call, "args", None) or {})
        if not isinstance(arguments, dict):
            calls.append(ToolCall(_call_id(), name, {}, error=agent_text.message("request.call-arguments-not-object")))
            continue
        calls.append(ToolCall(_call_id(), name, _gemini_arguments(arguments, schemas.get(name))))
    return tuple(calls)


def _gemini_tool_config(tool_choice: str) -> dict:
    return {"function_calling_config": {"mode": "NONE" if tool_choice == "none" else "AUTO"}}


# -- a model that thinks (see the module docstring) ---------------------------

def _endpoint(config: ProviderConfig) -> tuple[str, str, str]:
    return (config.api_type, config.base_url or "", config.model)


def _note_thinking(config: ProviderConfig) -> None:
    """*config*'s model was seen thinking: its later turns get their room."""
    with _thinking_lock:
        _thinking_endpoints.add(_endpoint(config))


def _note_room_refused(config: ProviderConfig) -> None:
    """*config*'s server refused a request given room for thinking, and took
    it without: its later turns are asked without the room."""
    with _thinking_lock:
        _room_refused.add(_endpoint(config))


def _may_give_room(config: ProviderConfig, max_output_tokens, thinking_tokens) -> bool:
    """Whether a turn on *config* may be given room for thinking: its caller
    offers some, the turn asks for a cap, and the endpoint never refused it."""
    if not (max_output_tokens and thinking_tokens):
        return False
    with _thinking_lock:
        return _endpoint(config) not in _room_refused


def _room_for(config: ProviderConfig, max_output_tokens, thinking_tokens) -> int:
    """The room a turn on *config* is first asked with: *thinking_tokens*
    once its model was seen thinking, else none."""
    if not _may_give_room(config, max_output_tokens, thinking_tokens):
        return 0
    with _thinking_lock:
        seen = _endpoint(config) in _thinking_endpoints
    return int(thinking_tokens) if seen else 0


def _wrote_nothing(text: str, calls) -> bool:
    """Whether a reply holds neither text nor a call."""
    return not (text or "").strip() and not calls


def _summed_usage(usage_out: dict | None, sinks: list[dict]) -> None:
    """The usage of every request a turn sent, summed into *usage_out*: one
    request's usage as it was, two requests' added up."""
    if usage_out is None:
        return
    total: dict = {}
    for sink in sinks:
        for key, value in sink.items():
            if isinstance(value, int):
                total[key] = total.get(key, 0) + value
    usage_out.update(total)


def _asked_with_room(config: ProviderConfig, max_output_tokens, thinking_tokens, usage_out, ask) -> ChatTurn:
    """A whole turn, asked through ``ask(limit, usage_sink)``, with the room
    a model that thinks gets (see the module docstring)."""
    room = _room_for(config, max_output_tokens, thinking_tokens)
    refused = False
    sinks: list[dict] = []
    while True:
        limit = max_output_tokens + room if max_output_tokens else max_output_tokens
        sink: dict = {}
        sinks.append(sink)
        try:
            turn = ask(limit, sink)
        except Exception as exc:
            _summed_usage(usage_out, sinks)
            if room and _status_code_of(exc) in (400, 422):
                room, refused = 0, True
                continue
            raise
        _summed_usage(usage_out, sinks)
        if refused:
            _note_room_refused(config)
        if turn.thinking:
            _note_thinking(config)
        if turn.cut_at_output_cap and _wrote_nothing(turn.text, turn.tool_calls):
            _note_thinking(config)
            if not room and not refused and _may_give_room(config, max_output_tokens, thinking_tokens):
                room = int(thinking_tokens)
                continue
        return replace(turn, output_limit=limit or 0, thinking_room_refused=refused)


def _streamed_with_room(config: ProviderConfig, max_output_tokens, thinking_tokens, usage_out, finish, ask):
    """A streamed turn, asked through ``ask(limit, usage_sink, ended)``, with
    the room a model that thinks gets (see the module docstring). A request
    is asked again only before it showed a word or a call, so its caller
    reads the second as the turn. *finish*, when given, gets how the turn
    ended once it has: the stop reason, ``thinking``, ``limit`` and
    ``thinking_room_refused``."""
    room = _room_for(config, max_output_tokens, thinking_tokens)
    refused = False
    sinks: list[dict] = []
    while True:
        limit = max_output_tokens + room if max_output_tokens else max_output_tokens
        sink: dict = {}
        ended: dict = {}
        sinks.append(sink)
        wrote = False
        events = ask(limit, sink, ended)
        try:
            for event in events:
                if isinstance(event, ToolCall) or (isinstance(event, str) and event.strip()):
                    wrote = True
                yield event
        except Exception as exc:
            _summed_usage(usage_out, sinks)
            if room and not wrote and _status_code_of(exc) in (400, 422):
                room, refused = 0, True
                continue
            raise
        finally:
            events.close()
        _summed_usage(usage_out, sinks)
        if refused:
            _note_room_refused(config)
        if ended.get("thinking"):
            _note_thinking(config)
        if ended.get("reason") in _OUTPUT_CAP_STOP_REASONS and not wrote:
            _note_thinking(config)
            if not room and not refused and _may_give_room(config, max_output_tokens, thinking_tokens):
                room = int(thinking_tokens)
                continue
        if finish is not None:
            finish.update(ended)
            if limit:
                finish["limit"] = limit
            if refused:
                finish["thinking_room_refused"] = True
        return


def run_chat_turn(
    config: ProviderConfig,
    messages: list,
    max_output_tokens: int | None = None,
    usage_out: dict | None = None,
    *,
    tools: list | None = None,
    tool_choice: str = "auto",
    reply_schema: dict | None = None,
    thinking_tokens: int | None = None,
) -> ChatTurn:
    """One model turn from the configured provider.

    ``messages`` is the OpenAI-style ``[{"role", "content"}, ...]`` list, whose
    system message may carry ``slots`` (see the module docstring).
    ``max_output_tokens`` is the effective resource policy (memo dev/24); when
    unset the anthropic backend keeps its former 4096 and the others use
    provider defaults. ``thinking_tokens`` is the room a model that thinks
    gets on top of it (see the module docstring); none when unset. ``tools``
    and ``tool_choice`` offer native tools, and ``reply_schema`` holds the
    reply to a schema (see the module docstring); an endpoint that refuses
    either raises :class:`NativeToolsRefused` or :class:`ReplySchemaRefused`.
    An OpenAI-compatible endpoint is asked for a stream, read whole; one that
    ends it before the model finished raises :class:`ReplyCutShort`, and one
    that stops sending raises :class:`ServerStoppedSending`. A turn the
    output cap cut is returned as it came, its stop reason saying so
    (:attr:`ChatTurn.cut_at_output_cap`).
    """
    try:
        return _run_chat_turn(
            config, messages, max_output_tokens, usage_out, tools, tool_choice, reply_schema, thinking_tokens
        )
    except Exception as exc:
        if _status_code_of(exc) in (400, 422):
            if tools:
                raise NativeToolsRefused(_redacted(exc, config)) from exc
            if reply_schema:
                raise ReplySchemaRefused(_redacted(exc, config)) from exc
        raise


def _run_chat_turn(
    config, messages, max_output_tokens, usage_out, tools, tool_choice, reply_schema=None, thinking_tokens=None
) -> ChatTurn:
    if config.api_type == "testing":
        # Scripted, deterministic, no network. Guarded on CURIO_TESTING inside
        # run_scripted_turn, so this branch cannot be reached on a real
        # deployment even if a config names it. See agents/testing_provider.py.
        from utk_curio.backend.app.agents.infrastructure.testing_provider import run_scripted_turn

        return run_scripted_turn(
            messages, usage_out=usage_out, config=config, tools=tools, tool_choice=tool_choice,
            reply_schema=reply_schema,
        )
    return _asked_with_room(
        config, max_output_tokens, thinking_tokens, usage_out,
        lambda limit, sink: _one_turn(config, messages, limit, sink, tools, tool_choice, reply_schema),
    )


def _one_turn(config, messages, max_output_tokens, usage_out, tools, tool_choice, reply_schema) -> ChatTurn:
    """One request of a whole turn, *max_output_tokens* its cap."""
    api_type = config.api_type
    if api_type == "anthropic":
        import anthropic
        client = anthropic.Anthropic(api_key=config.api_key)
        create_kwargs = {}
        if tools:
            create_kwargs = {"tools": _anthropic_tools(tools), "tool_choice": {"type": tool_choice}}
        if reply_schema:
            create_kwargs["output_config"] = {
                "format": {"type": "json_schema", "schema": reply_schema["schema"]}
            }
        resp = client.messages.create(
            model=config.model,
            system=_anthropic_system(messages, anthropic.NOT_GIVEN),
            messages=_anthropic_messages(messages),
            max_tokens=max_output_tokens or 4096,
            **create_kwargs,
        )
        _anthropic_usage(usage_out, getattr(resp, "usage", None))
        return ChatTurn(
            text=_anthropic_text(resp),
            tool_calls=_anthropic_calls(resp) if tools else (),
            stop_reason=str(getattr(resp, "stop_reason", "") or ""),
            thinking=_anthropic_thinking(resp),
        )
    elif api_type == "gemini":
        import google.generativeai as genai
        genai.configure(api_key=config.api_key)
        history, last = _gemini_turn(messages)
        gen_model = genai.GenerativeModel(config.model, system_instruction=_gemini_system(messages))
        chat = gen_model.start_chat(history=history)
        send_kwargs = {}
        if max_output_tokens:
            send_kwargs["generation_config"] = {"max_output_tokens": max_output_tokens}
        if tools:
            send_kwargs["tools"] = _gemini_tools(tools)
            send_kwargs["tool_config"] = _gemini_tool_config(tool_choice)
        response = chat.send_message(last, **send_kwargs)
        _gemini_usage(usage_out, getattr(response, "usage_metadata", None))
        return ChatTurn(
            text=_gemini_text(response),
            tool_calls=_gemini_calls(response, tools) if tools else (),
            stop_reason=_gemini_stop_reason(response),
        )
    else:  # openai_compatible (default)
        return _openai_whole_turn(
            config, messages, max_output_tokens, usage_out, tools, tool_choice, reply_schema
        )


def _openai_whole_turn(config, messages, max_output_tokens, usage_out, tools, tool_choice,
                       reply_schema, *, first_chunk_s: float | None = None) -> ChatTurn:
    """One OpenAI-compatible turn, read whole from its stream (see the module
    docstring): its text, its native calls, its finish reason and whether the
    model's thinking came apart. A stream that ends with no finish reason
    raises :class:`ReplyCutShort`. *first_chunk_s* is the longest any one
    read waits (:data:`FIRST_CHUNK_S` when None)."""
    started = time.monotonic()
    finish: dict = {}
    texts: list[str] = []
    calls: list = []
    for event in _openai_events(config, messages, max_output_tokens, usage_out, tools, tool_choice,
                                reply_schema=reply_schema, finish=finish, first_chunk_s=first_chunk_s):
        if isinstance(event, ToolCall):
            calls.append(event)
        else:
            texts.append(event)
    _finished(finish, started)
    # A reply that only calls tools has no content.
    return ChatTurn(text="".join(texts), tool_calls=tuple(calls), stop_reason=finish["reason"],
                    thinking=bool(finish.get("thinking")))


def _finished(finish: dict, started: float) -> None:
    """Raise :class:`ReplyCutShort` for an OpenAI-compatible stream, begun at
    *started*, that ended with no finish reason (*finish*, as
    :func:`_openai_events` filled it)."""
    if not finish.get("reason"):
        raise ReplyCutShort(agent_text.message(
            "turn.reply-cut-short", seconds=f"{time.monotonic() - started:.0f}"))


def _openai_events(config, messages, max_output_tokens, usage_out, tools, tool_choice, *,
                   reply_schema=None, finish: dict | None = None, first_chunk_s: float | None = None):
    """An OpenAI-compatible turn as the endpoint streams it: each text delta
    as it arrives, then each native call whole. *finish* gets the choice's
    finish reason (``reason``), and ``thinking`` once a delta carries the
    model's thinking apart from its reply (``reasoning_content``, or
    ``reasoning``), which is never yielded. A server that stops sending raises
    :class:`ServerStoppedSending` (see the module docstring). A streamed turn
    and a whole one both ask through here, and so does the native-tools
    trial, whose reads wait less (*first_chunk_s*, :data:`FIRST_CHUNK_S` for
    a turn)."""
    import openai
    first_chunk_s = FIRST_CHUNK_S if first_chunk_s is None else first_chunk_s
    kwargs = {"api_key": config.api_key or "no-key", "max_retries": 0,
              "timeout": openai.Timeout(first_chunk_s, connect=_CONNECT_S)}
    if config.base_url:
        kwargs["base_url"] = config.base_url
    client = openai.OpenAI(**kwargs)
    create_kwargs = {
        "model": config.model,
        "messages": _openai_messages(messages),
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    if max_output_tokens:
        create_kwargs["max_tokens"] = max_output_tokens
    if tools:
        create_kwargs["tools"] = _openai_tools(tools)
        create_kwargs["tool_choice"] = tool_choice
    if reply_schema:
        create_kwargs["response_format"] = {"type": "json_schema", "json_schema": {
            "name": reply_schema["name"], "schema": reply_schema["schema"], "strict": True,
        }}
    stream = _ask_for_stream(client, create_kwargs, first_chunk_s)
    silence = _Silence(stream)
    # A call arrives in pieces, by index: its id and name first, then its
    # arguments as fragments of one JSON text.
    pending: dict = {}
    chunks = 0
    finished = False
    try:
        for chunk in stream:
            chunks += 1
            silence.heard()
            _openai_usage(usage_out, getattr(chunk, "usage", None))
            choices = getattr(chunk, "choices", None) or []
            choice = choices[0] if choices else None
            delta = getattr(choice, "delta", None)
            reason = getattr(choice, "finish_reason", None)
            if reason:
                finished = True
                if finish is not None:
                    finish["reason"] = str(reason)
            if delta is not None and finish is not None and (
                getattr(delta, "reasoning_content", None) or getattr(delta, "reasoning", None)
            ):
                finish["thinking"] = True
            text = getattr(delta, "content", None) if delta is not None else None
            if text:
                # The time the caller takes with a piece is not the server's.
                silence.hold()
                yield text
                silence.heard()
            for piece in (getattr(delta, "tool_calls", None) or []) if tools else ():
                slot = pending.setdefault(getattr(piece, "index", None) or 0,
                                          {"id": "", "name": "", "arguments": ""})
                if getattr(piece, "id", None):
                    slot["id"] = piece.id
                function = getattr(piece, "function", None)
                if function is not None:
                    if getattr(function, "name", None) and not slot["name"]:
                        slot["name"] = function.name
                    if getattr(function, "arguments", None):
                        slot["arguments"] += function.arguments
    except Exception as exc:
        # A reply that finished before the cut is whole: the cut only ended
        # what follows its finish reason (the usage, the end of the stream).
        if not (silence.cut and finished):
            stopped = _stopped_reading(exc, cut=silence.cut, chunks=chunks, first_chunk_s=first_chunk_s)
            if stopped is None:
                raise
            raise stopped from exc
    finally:
        silence.end()
    if silence.cut and not finished:
        # A server that ends its answer by closing the connection ends it
        # cleanly when its socket is shut: the stream simply stopped.
        raise _stopped_sending(STREAM_SILENCE_S, began=True)
    for index in sorted(pending):
        slot = pending[index]
        yield _call_from_json(slot["id"] or _call_id(), slot["name"], slot["arguments"])


def _ask_for_stream(client, create_kwargs, first_chunk_s: float):
    """The stream an OpenAI-compatible server answers *create_kwargs* with.

    The SDK sends the request once (``max_retries=0``). A request the server
    turned down is sent again, after each wait of :data:`_RESEND_WAITS_S` or
    what its ``retry-after`` asks, up to :data:`_RETRY_AFTER_MAX_S`, as the
    SDK's own retries did: a refused or dropped connection, a 408, 409 or 429,
    or a 5xx other than a 504. A request held past the limit is not: a read
    that waited out *first_chunk_s* (:data:`FIRST_CHUNK_S` for a turn) raises
    :class:`ServerStoppedSending`, and a 504 says a gateway gave up waiting on
    the server, which a new try would wait on as long. A connection a proxy
    drops while it holds the request (after 60 s of silence, say) is a
    dropped connection like any other, and is sent again, as the SDK sent
    it."""
    import openai

    for wait in (*_RESEND_WAITS_S, None):
        try:
            return client.chat.completions.create(**create_kwargs)
        except openai.APIStatusError as exc:
            status = exc.status_code
            if wait is None or not (status in (408, 409, 429) or (status >= 500 and status != 504)):
                raise
            wait = _asked_wait(exc.response, wait)
        except openai.APIConnectionError as exc:  # APITimeoutError is one
            if _read_timed_out(exc):
                raise _stopped_sending(first_chunk_s, began=False) from exc
            if wait is None:
                raise
        time.sleep(wait)


def _asked_wait(response, default: float) -> float:
    """The wait, in seconds, a server's ``retry-after`` header asks for, when
    it asks for one up to :data:`_RETRY_AFTER_MAX_S`; else *default*."""
    try:
        asked = float(response.headers.get("retry-after"))
    except (AttributeError, TypeError, ValueError):
        return default
    return asked if 0 < asked <= _RETRY_AFTER_MAX_S else default


class _Silence:
    """Ends an OpenAI-compatible stream its server stopped feeding without
    closing it. Once a chunk has come, a thread waits for the next one: when
    none comes for :data:`STREAM_SILENCE_S`, it shuts the stream's socket down,
    which wakes the read waiting on it, and :attr:`cut` says so. Only the time
    the stream waits on its server counts (:meth:`hold`). A stream whose socket
    cannot be reached (a test's fake) is never cut; each of its reads still
    waits at most :data:`FIRST_CHUNK_S`."""

    def __init__(self, stream):
        self._socket = _socket_of(stream)
        self._lock = threading.Lock()
        self._deadline: float | None = None
        self._ended = threading.Event()
        self._thread: threading.Thread | None = None
        self.cut = False

    def heard(self) -> None:
        """A chunk came, or the caller handed the stream back: the server has
        :data:`STREAM_SILENCE_S` to send the next."""
        if self._socket is None:
            return
        with self._lock:
            self._deadline = time.monotonic() + STREAM_SILENCE_S
        if self._thread is None:
            self._thread = threading.Thread(target=self._watch, name="model-stream-silence", daemon=True)
            self._thread.start()

    def hold(self) -> None:
        """The caller has a piece: no silence counts until :meth:`heard`."""
        with self._lock:
            self._deadline = None

    def end(self) -> None:
        """The stream ended, by any way: the watch ends."""
        self._ended.set()

    def _watch(self) -> None:
        while True:
            with self._lock:
                deadline = self._deadline
                if deadline is not None and time.monotonic() >= deadline:
                    self.cut = True
                    break
            if self._ended.wait(STREAM_SILENCE_S if deadline is None else deadline - time.monotonic()):
                return
        try:
            # The socket's own shutdown, not an SSL socket's: that one would
            # also unwrap it under the read in progress.
            socket.socket.shutdown(self._socket, socket.SHUT_RDWR)
        except OSError:
            pass  # the connection is gone already


def _socket_of(stream):
    """The socket an SDK stream reads from, or None: its HTTP response's
    ``network_stream`` (an HTTP/1.1 connection of httpx, or of httpx2 in the
    newer SDKs), which a test's fake has none of."""
    try:
        sock = stream.response.extensions.get("network_stream").get_extra_info("socket")
    except Exception:  # noqa: BLE001 - a stream without one is only not watched
        return None
    return sock if isinstance(sock, socket.socket) else None


def _read_timed_out(exc: BaseException | None) -> bool:
    """Whether *exc*, or an error it was raised from, is a read that waited
    out its timeout: the HTTP library's ``ReadTimeout`` (httpx's, or httpx2's
    in the newer SDKs), which the SDK raises bare from a stream or wraps in its
    ``APITimeoutError``. A connection that could not be made is not one."""
    seen: set[int] = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        if type(exc).__name__ == "ReadTimeout":
            return True
        exc = exc.__cause__
    return False


def _stopped_reading(exc: BaseException, *, cut: bool, chunks: int, first_chunk_s: float):
    """The :class:`ServerStoppedSending` a stream's failed read means, after
    *chunks* chunks, or None: the stream :class:`_Silence` *cut*, or a read
    that waited out *first_chunk_s*."""
    if cut:
        return _stopped_sending(STREAM_SILENCE_S, began=True)
    if _read_timed_out(exc):
        return _stopped_sending(first_chunk_s, began=chunks > 0)
    return None


def _stopped_sending(seconds: float, *, began: bool) -> ServerStoppedSending:
    """The error of a server that sent nothing for *seconds*: after a piece of
    the reply when the reply *began*, else after the request."""
    shown = f"{seconds:g}"
    if began:
        return ServerStoppedSending(agent_text.message("turn.server-stopped-sending", seconds=shown))
    return ServerStoppedSending(agent_text.message("turn.server-sent-nothing", seconds=shown))


def says_server_stopped_sending(text: str | None) -> bool:
    """Whether *text*, such as the error a run answered, holds the message of
    a :class:`ServerStoppedSending`: either of its messages, up to the place
    of its seconds."""
    openings = (
        agent_text.message("turn.server-stopped-sending", seconds="\0"),
        agent_text.message("turn.server-sent-nothing", seconds="\0"),
    )
    return bool(text) and any(opening.split("\0")[0] in text for opening in openings)


def run_chat_completion(
    config: ProviderConfig,
    messages: list,
    max_output_tokens: int | None = None,
    usage_out: dict | None = None,
) -> str:
    """The text of one model turn (:func:`run_chat_turn`), for a caller that
    needs nothing else."""
    return run_chat_turn(config, messages, max_output_tokens, usage_out).text


def stream_chat_turn(
    config: ProviderConfig,
    messages: list,
    max_output_tokens: int | None = None,
    usage_out: dict | None = None,
    *,
    tools: list | None = None,
    tool_choice: str = "auto",
    finish: dict | None = None,
    thinking_tokens: int | None = None,
):
    """Streaming twin of :func:`run_chat_turn`: yields the turn's events as they
    arrive. A text delta is a bare string; a native tool call is a
    :class:`ToolCall`, yielded once the call is complete. *finish*, when
    given, gets what the whole turn's :class:`ChatTurn` carries besides them
    once the stream has ended: the stop reason (``reason``), ``thinking``
    when the model's thinking came apart from its reply, the cap the request
    that answered carried (``limit``), and ``thinking_room_refused``.
    ``thinking_tokens`` is the room a model that thinks gets (see the module
    docstring).

    Same provider dispatch and message handling. Callers that stop iterating
    close the underlying provider stream. A refusal of the offered tools raises
    :class:`NativeToolsRefused`, which an endpoint gives before any event. An
    OpenAI-compatible stream that ends with no finish reason raises
    :class:`ReplyCutShort` after its last event, and one whose server stops
    sending raises :class:`ServerStoppedSending`.
    """
    events = _stream_chat_turn(config, messages, max_output_tokens, usage_out, tools, tool_choice, finish,
                               thinking_tokens)
    started = False
    try:
        for event in events:
            started = True
            yield event
    except Exception as exc:
        if tools and not started and _status_code_of(exc) in (400, 422):
            raise NativeToolsRefused(_redacted(exc, config)) from exc
        raise
    finally:
        events.close()


def _stream_chat_turn(config, messages, max_output_tokens, usage_out, tools, tool_choice, finish=None,
                      thinking_tokens=None):
    if config.api_type == "testing":
        # The scripted reply, delivered as a single chunk. Splitting it would
        # only test the splitter: what the SSE runtime needs from a provider
        # is a deterministic sequence of deltas, and one is a sequence.
        from utk_curio.backend.app.agents.infrastructure.testing_provider import run_scripted_turn

        turn = run_scripted_turn(
            messages, usage_out=usage_out, config=config, tools=tools, tool_choice=tool_choice
        )
        if turn.text or not turn.tool_calls:
            yield turn.text
        yield from turn.tool_calls
        if finish is not None:
            finish.update(reason=turn.stop_reason, thinking=turn.thinking)
        return
    yield from _streamed_with_room(
        config, max_output_tokens, thinking_tokens, usage_out, finish,
        lambda limit, sink, ended: _one_stream(config, messages, limit, sink, tools, tool_choice, ended),
    )


def _one_stream(config, messages, max_output_tokens, usage_out, tools, tool_choice, finish):
    """One request of a streamed turn, *max_output_tokens* its cap: its
    events, and how it ended, in *finish*."""
    api_type = config.api_type
    if api_type == "anthropic":
        import anthropic
        client = anthropic.Anthropic(api_key=config.api_key)
        create_kwargs = {}
        if tools:
            create_kwargs = {"tools": _anthropic_tools(tools), "tool_choice": {"type": tool_choice}}
        with client.messages.stream(
            model=config.model,
            system=_anthropic_system(messages, anthropic.NOT_GIVEN),
            messages=_anthropic_messages(messages),
            max_tokens=max_output_tokens or 4096,
            **create_kwargs,
        ) as stream:
            for text in stream.text_stream:
                if text:
                    yield text
            try:
                final = stream.get_final_message()
            except Exception:
                final = None  # usage is best-effort; the reply already streamed
            if final is not None:
                _anthropic_usage(usage_out, getattr(final, "usage", None))
                finish["reason"] = str(getattr(final, "stop_reason", "") or "")
                if _anthropic_thinking(final):
                    finish["thinking"] = True
                if tools:
                    yield from _anthropic_calls(final)
    elif api_type == "gemini":
        import google.generativeai as genai
        genai.configure(api_key=config.api_key)
        history, last = _gemini_turn(messages)
        gen_model = genai.GenerativeModel(config.model, system_instruction=_gemini_system(messages))
        chat = gen_model.start_chat(history=history)
        send_kwargs = {}
        if max_output_tokens:
            send_kwargs["generation_config"] = {"max_output_tokens": max_output_tokens}
        if tools:
            send_kwargs["tools"] = _gemini_tools(tools)
            send_kwargs["tool_config"] = _gemini_tool_config(tool_choice)
        last_chunk = None
        calls: list = []
        reason = ""
        for chunk in chat.send_message(last, stream=True, **send_kwargs):
            last_chunk = chunk
            # The last chunk that names a finish reason has the turn's.
            reason = _gemini_stop_reason(chunk) or reason
            text = _gemini_text(chunk)
            if text:
                yield text
            if tools:
                calls.extend(_gemini_calls(chunk, tools))
        _gemini_usage(usage_out, getattr(last_chunk, "usage_metadata", None))
        finish["reason"] = reason
        yield from calls
    else:  # openai_compatible (default)
        started = time.monotonic()
        yield from _openai_events(config, messages, max_output_tokens, usage_out, tools, tool_choice,
                                  finish=finish)
        _finished(finish, started)


def stream_chat_completion(
    config: ProviderConfig,
    messages: list,
    max_output_tokens: int | None = None,
    usage_out: dict | None = None,
):
    """The text deltas of :func:`stream_chat_turn`, for a caller that needs
    nothing else."""
    for event in stream_chat_turn(config, messages, max_output_tokens, usage_out):
        if isinstance(event, str):
            yield event


#: The one tool a native-tools trial offers, in the shape a run's tools are
#: given. It does nothing: the trial only learns whether the model calls it.
_TRIAL_TOOL = {
    "name": "ping",
    "description": "Answer this check by calling ping.",
    "parameters": {"type": "object", "properties": {}},
}
_TRIAL_MESSAGES = ({"role": "user", "content": "Call the ping tool."},)
#: The trial's output cap, and the room a model that thinks gets on top of it
#: (see the module docstring). On 11-03 gemma4 behind vLLM, which counts its
#: thinking against the cap, spent the trial's 32 tokens thinking (finish
#: ``length``, no call) when the trial had no room, so every account on it
#: kept "fenced"; with the room it called the tool after 47 tokens, in 0.6 s.
#: The trial runs before the run's first call, so its room stays small, as
#: the title's does.
TRIAL_MAX_TOKENS = 32
TRIAL_THINKING_TOKENS = 1024
#: How long any one read of the trial waits, where a turn waits
#: :data:`FIRST_CHUNK_S`. The trial's whole reply with the room, 1,056 tokens,
#: takes 22 s at the 48 tokens a second that vLLM server streamed gemma4 at,
#: so a server that holds the whole reply back until it ends, as a tool
#: parser may hold a call, answers inside this wait at half that pace; a
#: proxy before the server cuts a request silent this long anyway (nginx:
#: 60 s). It is half of :data:`STREAM_SILENCE_S`, so the trial never comes to
#: that limit.
TRIAL_WAIT_S = 60.0
#: Why a trial answered as it did (``probe_native_tools``): the model called
#: the tool; the endpoint refused it (a 400 or a 422); the model ended its
#: reply without calling it; the trial's limit cut the reply before a call,
#: the room included; or the endpoint could not be asked.
TRIAL_CALLED = "called"
TRIAL_REFUSED = "refused"
TRIAL_IGNORED = "ignored"
TRIAL_CUT = "cut"
TRIAL_UNANSWERED = "unanswered"


def probe_native_tools(config: ProviderConfig, usage_out: dict | None = None) -> tuple[bool | None, str, str]:
    """Ask an OpenAI-compatible endpoint whether ``config.model`` calls tools
    natively: a short request offering one tool, asked as a turn is
    (:func:`_openai_whole_turn`, streamed) with the room a model that thinks
    gets (:func:`_asked_with_room`). A trial the cap cut before a word or a
    call is asked again once with :data:`TRIAL_THINKING_TOKENS` of room, and
    an endpoint seen thinking is asked with it at once. Each read waits at
    most :data:`TRIAL_WAIT_S`.

    Returns ``(tools, reason, cause)``, the cause one of the ``TRIAL_*``
    values: ``True`` when the reply calls the tool; ``False`` on a 400 or 422
    (the server takes no tools for this model) or a reply that ends without
    calling it; ``None`` when the trial's limit still cut the reply before a
    call, which says nothing of the tools, or when the endpoint could not
    answer at all. The requests are charged; their usage, summed, lands in
    *usage_out*.
    """
    try:
        turn = _asked_with_room(
            config, TRIAL_MAX_TOKENS, TRIAL_THINKING_TOKENS, usage_out,
            lambda limit, sink: _openai_whole_turn(
                config, list(_TRIAL_MESSAGES), limit, sink, [_TRIAL_TOOL],
                # As a run asks: some servers take tools but refuse a stated choice.
                "auto", None, first_chunk_s=TRIAL_WAIT_S,
            ),
        )
    except Exception as exc:  # noqa: BLE001 - every failure is an answer here
        if _status_code_of(exc) in (400, 422):
            return False, f"the endpoint refused a tool: {_redacted(exc, config)}", TRIAL_REFUSED
        return None, f"could not ask the endpoint: {_redacted(exc, config)}", TRIAL_UNANSWERED
    if turn.tool_calls:
        return True, "the model called the tool it was offered", TRIAL_CALLED
    if turn.cut_at_output_cap:
        how = ("while the model was still thinking" if turn.thinking and _wrote_nothing(turn.text, ())
               else "before the model called the tool")
        return None, f"the trial's output limit of {turn.output_limit:,} tokens ran out {how}", TRIAL_CUT
    return False, "the model answered without calling the tool it was offered", TRIAL_IGNORED


class ModelListingUnavailable(RuntimeError):
    """The endpoint could not be asked what it serves.

    Carries the reason so API Settings can say *why* the list is missing rather
    than only that it is: a rejected key, an unreachable host and an endpoint
    with no listing route are three different things for the user to fix.
    """


def list_provider_models(config: ProviderConfig) -> list[str]:
    """The model ids *config*'s endpoint says it serves.

    Lives here for the same reason every other provider call does: this module
    is the one place raw provider SDKs are imported (see the module docstring).
    The route used to import ``openai`` directly, which also meant Anthropic and
    Gemini were reported as unlistable when in fact nobody had asked them
    (#241) - both SDKs have had a models endpoint for some time.

    Raises :class:`ModelListingUnavailable` when the endpoint cannot answer. The
    caller decides what to do about that; ``model_catalog`` holds the fallback.
    """
    api_type = (config.api_type or "").strip()

    if not (config.api_key or "").strip():
        # No credential means no listing anywhere: OpenAI, Anthropic and Gemini
        # all authenticate their models endpoint. Refusing here rather than
        # sending "no-key" keeps a user who has not pasted a key yet from
        # waiting out a socket timeout for a foregone 401.
        raise ModelListingUnavailable(
            "Add an API key above to ask this provider what it serves."
        )

    try:
        if api_type == "anthropic":
            import anthropic

            client = anthropic.Anthropic(api_key=config.api_key, timeout=20.0)
            return sorted(
                {m.id for m in client.models.list() if getattr(m, "id", None)}
            )

        if api_type == "gemini":
            import google.generativeai as genai

            genai.configure(api_key=config.api_key)
            out: set[str] = set()
            for m in genai.list_models():
                methods = getattr(m, "supported_generation_methods", None) or []
                # Embedding and tuning-only models are listed too, and offering
                # one as the chat model produces a failure at the first agent
                # run rather than here.
                if "generateContent" not in methods:
                    continue
                name = getattr(m, "name", "") or ""
                # The API returns "models/gemini-2.0-flash"; every other place
                # in Curio names the bare id.
                out.add(name.split("/", 1)[-1] if name.startswith("models/") else name)
            return sorted(n for n in out if n)

        # openai_compatible (default), which also covers Ollama, vLLM, Groq, ...
        from openai import OpenAI

        kwargs: dict = {"api_key": config.api_key, "timeout": 20.0}
        if config.base_url:
            kwargs["base_url"] = config.base_url
        listing = OpenAI(**kwargs).models.list()
        return sorted({m.id for m in listing.data if getattr(m, "id", None)})
    except Exception as exc:  # noqa: BLE001 - every SDK failure is one answer here
        # A rejected key, an unreachable host and an endpoint without a models
        # route all mean "cannot offer a live choice".
        raise ModelListingUnavailable(f"Could not list models: {_redacted(exc, config)}") from exc


def _status_code_of(exc: Exception) -> int | None:
    # ``code`` is where Gemini's errors keep it (google.api_core).
    for attribute in ("status_code", "status", "http_status", "code"):
        value = getattr(exc, attribute, None)
        if isinstance(value, int):
            return value
    response = getattr(exc, "response", None)
    value = getattr(response, "status_code", None)
    return value if isinstance(value, int) else None
