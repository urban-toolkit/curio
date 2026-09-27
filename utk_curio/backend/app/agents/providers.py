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

The dispatch below was extracted verbatim from ``app/api/routes.py::_call_llm``
(behavior-preserving) and is the seam a future LangChain adapter would sit behind.

User-facing overview: ``docs/AGENT-CATALOG.md``.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field


class NativeToolsRefused(RuntimeError):
    """The endpoint refused a request that offered native tools (a 400 or a
    422). The message is the endpoint's reason, with the key taken out."""


@dataclass(frozen=True)
class ProviderConfig:
    """Resolved, provider-neutral connection config for one chat completion.

    ``api_type`` selects the backend: ``"anthropic"``, ``"gemini"``, or
    ``"openai_compatible"`` (the default, used by OpenAI, the aiconn sage200
    endpoint, Ollama, vLLM, etc.). ``base_url`` applies only to the
    openai-compatible backend; the others ignore it.

    The rest say where the config came from (``provider_config.resolve_llm``):
    the LLM configuration's id and label, ``source`` (``default``,
    ``deployment`` or ``guest``), and whether its model was trained in Curio.
    The key is left out of the repr, so a logged config never shows it.
    """

    api_key: str = field(repr=False)
    api_type: str
    base_url: str
    model: str
    config_id: str | None = None
    label: str = ""
    source: str = ""
    trained: bool = False


def _redacted(exc: BaseException, config: ProviderConfig) -> str:
    """SDK error text with the call's own key taken out, for any message that
    is persisted, streamed, logged or returned."""
    from utk_curio.common.redaction import redact

    text = str(exc)
    return (redact(text, {"llm-api-key": config.api_key}) or text) if config.api_key else text


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
        return ToolCall(call_id, name, {}, error=f"the arguments are not valid JSON: {exc}")
    if not isinstance(arguments, dict):
        return ToolCall(call_id, name, {}, error="the arguments must be a JSON object")
    return ToolCall(call_id, name, arguments)


def _call_id() -> str:
    """An id for a call whose provider names none (Gemini)."""
    return f"call-{uuid.uuid4().hex[:12]}"


@dataclass(frozen=True)
class ChatTurn:
    """One model turn: its text, the native tool calls it made (none while no
    tools are offered), and the provider's stop reason."""

    text: str
    tool_calls: tuple = ()
    stop_reason: str = ""

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


def _anthropic_system(messages: list, not_given):
    """Anthropic's ``system``: a text block per slot, the preamble marked
    cacheable (it is the longest part, and every run of the agent repeats it);
    without slots, the joined text as before."""
    parts = _system_parts(messages)
    if not parts:
        return not_given
    if not _has_slots(messages):
        return "\n".join(text for _, text in parts)
    blocks = []
    for kind, text in parts:
        block = {"type": "text", "text": text}
        if kind == "preamble":
            block["cache_control"] = {"type": "ephemeral"}
        blocks.append(block)
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


def _anthropic_calls(resp) -> tuple:
    calls = []
    for block in getattr(resp, "content", None) or []:
        if getattr(block, "type", "") != "tool_use":
            continue
        arguments = getattr(block, "input", None)
        calls.append(ToolCall(
            str(getattr(block, "id", "") or _call_id()), str(getattr(block, "name", "") or ""),
            dict(arguments) if isinstance(arguments, dict) else {},
            error="" if isinstance(arguments, dict) else "the arguments must be an object",
        ))
    return tuple(calls)


def _openai_calls(message) -> tuple:
    calls = []
    for call in getattr(message, "tool_calls", None) or []:
        function = getattr(call, "function", None)
        calls.append(_call_from_json(
            str(getattr(call, "id", "") or _call_id()),
            str(getattr(function, "name", "") or ""),
            str(getattr(function, "arguments", "") or ""),
        ))
    return tuple(calls)


def _gemini_parts(response) -> list:
    candidates = getattr(response, "candidates", None) or []
    content = getattr(candidates[0], "content", None) if candidates else None
    return list(getattr(content, "parts", None) or [])


def _gemini_text(response) -> str:
    """The text parts of a Gemini reply. ``response.text`` raises when a part
    is a function call, so the parts are read one by one when they are there."""
    parts = _gemini_parts(response)
    if parts:
        return "".join(getattr(part, "text", "") or "" for part in parts)
    return getattr(response, "text", "") or ""


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
            calls.append(ToolCall(_call_id(), name, {}, error="the arguments must be an object"))
            continue
        calls.append(ToolCall(_call_id(), name, _gemini_arguments(arguments, schemas.get(name))))
    return tuple(calls)


def _gemini_tool_config(tool_choice: str) -> dict:
    return {"function_calling_config": {"mode": "NONE" if tool_choice == "none" else "AUTO"}}


def run_chat_turn(
    config: ProviderConfig,
    messages: list,
    max_output_tokens: int | None = None,
    usage_out: dict | None = None,
    *,
    tools: list | None = None,
    tool_choice: str = "auto",
) -> ChatTurn:
    """One model turn from the configured provider.

    ``messages`` is the OpenAI-style ``[{"role", "content"}, ...]`` list, whose
    system message may carry ``slots`` (see the module docstring).
    ``max_output_tokens`` is the effective resource policy (memo dev/24); when
    unset the anthropic backend keeps its former 4096 and the others use
    provider defaults. ``tools`` and ``tool_choice`` offer native tools (see
    the module docstring); an endpoint that refuses them raises
    :class:`NativeToolsRefused`.
    """
    try:
        return _run_chat_turn(config, messages, max_output_tokens, usage_out, tools, tool_choice)
    except Exception as exc:
        if tools and _status_code_of(exc) in (400, 422):
            raise NativeToolsRefused(_redacted(exc, config)) from exc
        raise


def _run_chat_turn(config, messages, max_output_tokens, usage_out, tools, tool_choice) -> ChatTurn:
    api_type = config.api_type
    if api_type == "testing":
        # Scripted, deterministic, no network. Guarded on CURIO_TESTING inside
        # run_scripted_turn, so this branch cannot be reached on a real
        # deployment even if a config names it. See agents/testing_provider.py.
        from utk_curio.backend.app.agents.testing_provider import run_scripted_turn

        return run_scripted_turn(
            messages, usage_out=usage_out, config=config, tools=tools, tool_choice=tool_choice
        )
    if api_type == "anthropic":
        import anthropic
        client = anthropic.Anthropic(api_key=config.api_key)
        create_kwargs = {}
        if tools:
            create_kwargs = {"tools": _anthropic_tools(tools), "tool_choice": {"type": tool_choice}}
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
        )
    else:  # openai_compatible (default)
        from openai import OpenAI
        kwargs = {"api_key": config.api_key or "no-key"}
        if config.base_url:
            kwargs["base_url"] = config.base_url
        client = OpenAI(**kwargs)
        create_kwargs = {"model": config.model, "messages": _openai_messages(messages)}
        if max_output_tokens:
            create_kwargs["max_tokens"] = max_output_tokens
        if tools:
            create_kwargs["tools"] = _openai_tools(tools)
            create_kwargs["tool_choice"] = tool_choice
        completion = client.chat.completions.create(**create_kwargs)
        _openai_usage(usage_out, getattr(completion, "usage", None))
        choice = completion.choices[0]
        # A reply that only calls tools has no content.
        return ChatTurn(
            text=getattr(choice.message, "content", None) or "",
            tool_calls=_openai_calls(choice.message) if tools else (),
            stop_reason=str(getattr(choice, "finish_reason", "") or ""),
        )


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
):
    """Streaming twin of :func:`run_chat_turn`: yields the turn's events as they
    arrive. A text delta is a bare string; a native tool call is a
    :class:`ToolCall`, yielded once the call is complete.

    Same provider dispatch and message handling. Callers that stop iterating
    close the underlying provider stream. A refusal of the offered tools raises
    :class:`NativeToolsRefused`, which an endpoint gives before any event.
    """
    events = _stream_chat_turn(config, messages, max_output_tokens, usage_out, tools, tool_choice)
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


def _stream_chat_turn(config, messages, max_output_tokens, usage_out, tools, tool_choice):
    api_type = config.api_type
    if api_type == "testing":
        # The scripted reply, delivered as a single chunk. Splitting it would
        # only test the splitter: what the SSE runtime needs from a provider
        # is a deterministic sequence of deltas, and one is a sequence.
        from utk_curio.backend.app.agents.testing_provider import run_scripted_turn

        turn = run_scripted_turn(
            messages, usage_out=usage_out, config=config, tools=tools, tool_choice=tool_choice
        )
        if turn.text or not turn.tool_calls:
            yield turn.text
        yield from turn.tool_calls
        return
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
        for chunk in chat.send_message(last, stream=True, **send_kwargs):
            last_chunk = chunk
            text = _gemini_text(chunk)
            if text:
                yield text
            if tools:
                calls.extend(_gemini_calls(chunk, tools))
        _gemini_usage(usage_out, getattr(last_chunk, "usage_metadata", None))
        yield from calls
    else:  # openai_compatible (default)
        from openai import OpenAI
        kwargs = {"api_key": config.api_key or "no-key"}
        if config.base_url:
            kwargs["base_url"] = config.base_url
        client = OpenAI(**kwargs)
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
        stream = client.chat.completions.create(**create_kwargs)
        # A call arrives in pieces, by index: its id and name first, then its
        # arguments as fragments of one JSON text.
        pending: dict = {}
        for chunk in stream:
            _openai_usage(usage_out, getattr(chunk, "usage", None))
            choices = getattr(chunk, "choices", None) or []
            delta = choices[0].delta if choices else None
            text = getattr(delta, "content", None) if delta is not None else None
            if text:
                yield text
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
        for index in sorted(pending):
            slot = pending[index]
            yield _call_from_json(slot["id"] or _call_id(), slot["name"], slot["arguments"])


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


#: The one tool a native-tools trial offers. It does nothing: the trial only
#: learns whether the model calls it.
_TRIAL_TOOL = {
    "type": "function",
    "function": {
        "name": "ping",
        "description": "Answer this check by calling ping.",
        "parameters": {"type": "object", "properties": {}},
    },
}


def probe_native_tools(config: ProviderConfig, usage_out: dict | None = None) -> tuple[bool | None, str]:
    """Ask an OpenAI-compatible endpoint whether ``config.model`` calls tools
    natively: one short request offering one tool.

    Returns ``(True, reason)`` when the reply calls it, ``(False, reason)`` on
    a 400 or 422 (the server takes no tools for this model) or a reply that
    ignores the tool, and ``(None, reason)`` when the endpoint could not
    answer at all. The request is charged; its usage lands in *usage_out*.
    """
    from openai import OpenAI

    # No retries: the trial runs before the run's own first call, and an
    # endpoint that cannot answer now is asked again on the next run.
    kwargs: dict = {"api_key": config.api_key or "no-key", "timeout": 30.0, "max_retries": 0}
    if config.base_url:
        kwargs["base_url"] = config.base_url
    try:
        completion = OpenAI(**kwargs).chat.completions.create(
            model=config.model,
            messages=[{"role": "user", "content": "Call the ping tool."}],
            tools=[_TRIAL_TOOL],
            # As a run asks: some servers take tools but refuse a stated choice.
            tool_choice="auto",
            max_tokens=32,
        )
    except Exception as exc:  # noqa: BLE001 - every SDK failure is an answer here
        if _status_code_of(exc) in (400, 422):
            return False, f"the endpoint refused a tool: {_redacted(exc, config)}"
        return None, f"could not ask the endpoint: {_redacted(exc, config)}"
    _openai_usage(usage_out, getattr(completion, "usage", None))
    choices = getattr(completion, "choices", None) or []
    message = getattr(choices[0], "message", None) if choices else None
    if getattr(message, "tool_calls", None):
        return True, "the model called the tool it was offered"
    return False, "the model answered without calling the tool it was offered"


class ModelListingUnavailable(RuntimeError):
    """The endpoint could not be asked what it serves.

    Carries the reason so AI Settings can say *why* the list is missing rather
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


# ---------------------------------------------------------------------------
# Fine-tuning (memo dev/122, ``DEC-078``)
# ---------------------------------------------------------------------------
#
# Same rule as everything above: the SDK is imported here and nowhere else, and
# the answer to "can this endpoint do it" is obtained by ASKING the endpoint.
# A table of which providers support tuning would drift exactly the way the
# table of model ids drifted (#241) and could say nothing about a custom
# endpoint — and "OpenAI-compatible" spans endpoints that implement the tuning
# routes and endpoints that implement only chat (Ollama, LM Studio, vLLM).
#
# These calls do not pass through ``agents/egress.py``, for the same reason no
# other provider call does: that chokepoint polices URLs a MODEL chose, while
# this host is one the account holder typed into AI Settings. It is also the
# only option — ``egress.fetch`` has no request body and caps responses, so it
# cannot express a training-file upload.


class FineTuningUnavailable(RuntimeError):
    """This endpoint cannot fine-tune, and this is why.

    A sibling of :class:`ModelListingUnavailable` and for the same reason: "no
    such feature here", "your key lacks the scope" and "the host is
    unreachable" are three different things for a user to act on, so the reason
    travels with the refusal instead of being flattened into a boolean.
    """


#: Job statuses Curio normalizes to. ``raw_status`` on the job keeps whatever
#: the endpoint actually said, because a status we have never seen must not be
#: displayed as one we have.
JOB_STATUSES = ("queued", "running", "succeeded", "failed", "cancelled")

_OPENAI_STATUS_MAP = {
    "validating_files": "queued",
    "queued": "queued",
    "pending": "queued",
    "running": "running",
    "succeeded": "succeeded",
    "failed": "failed",
    "cancelled": "cancelled",
    "canceled": "cancelled",
}


@dataclass(frozen=True)
class FineTuningCapabilities:
    """What *this* endpoint said about tuning, and when it said it."""

    supported: bool
    reason: str
    base_models: tuple = ()
    surface: str = ""            # "openai_compatible_v1" when recognised
    probed_at: str = ""

    def as_dict(self) -> dict:
        return {
            "supported": self.supported,
            "reason": self.reason,
            "baseModels": list(self.base_models),
            "surface": self.surface,
            "probedAt": self.probed_at,
        }


@dataclass(frozen=True)
class FineTuningJob:
    """One tuning job as the endpoint reports it."""

    id: str
    status: str                  # one of JOB_STATUSES
    raw_status: str = ""
    base_model: str = ""
    trained_model: str | None = None
    trained_tokens: int | None = None
    error: str | None = None

    @property
    def terminal(self) -> bool:
        return self.status in ("succeeded", "failed", "cancelled")

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "status": self.status,
            "rawStatus": self.raw_status,
            "baseModel": self.base_model,
            "trainedModel": self.trained_model,
            "trainedTokens": self.trained_tokens,
            "error": self.error,
        }


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _openai_client(config: ProviderConfig, *, timeout: float = 30.0):
    from openai import OpenAI

    kwargs: dict = {"api_key": config.api_key or "no-key", "timeout": timeout}
    if config.base_url:
        kwargs["base_url"] = config.base_url
    return OpenAI(**kwargs)


def _status_code_of(exc: Exception) -> int | None:
    # ``code`` is where Gemini's errors keep it (google.api_core).
    for attribute in ("status_code", "status", "http_status", "code"):
        value = getattr(exc, attribute, None)
        if isinstance(value, int):
            return value
    response = getattr(exc, "response", None)
    value = getattr(response, "status_code", None)
    return value if isinstance(value, int) else None


def fine_tuning_capabilities(config: ProviderConfig) -> FineTuningCapabilities:
    """Ask *config*'s endpoint whether it can fine-tune.

    Never raises: an unanswerable endpoint is an answer with a reason, which is
    what a settings panel needs in order to say *why* rather than only *no*
    (the dev/11 posture: show Unavailable, never a substitute).
    """
    api_type = (config.api_type or "").strip()
    probed_at = _now_iso()

    if api_type == "testing":
        from utk_curio.backend.app.agents import testing_provider

        return testing_provider.scripted_fine_tuning_capabilities(probed_at=probed_at)

    if api_type == "anthropic":
        return FineTuningCapabilities(
            supported=False,
            reason=(
                "Anthropic's API has no fine-tuning endpoint: it publishes "
                "Messages, Message Batches, Token Counting, Models, Files and "
                "Skills, plus the beta Agents, Sessions and Environments APIs. "
                "Nothing here can tune a Claude model."
            ),
            probed_at=probed_at,
        )

    if api_type == "gemini":
        return FineTuningCapabilities(
            supported=False,
            reason=(
                "Gemini tunes through its tunedModels API, a different contract "
                "Curio has not implemented. Chat and model listing work as usual."
            ),
            probed_at=probed_at,
        )

    if not (config.api_key or "").strip():
        return FineTuningCapabilities(
            supported=False,
            reason=(
                "Add an API key above: every endpoint authenticates its "
                "fine-tuning routes, so there is nothing to ask yet."
            ),
            probed_at=probed_at,
        )

    # openai_compatible (the default) — and being OpenAI-compatible for chat
    # says nothing about tuning, so the routes are what get asked.
    try:
        client = _openai_client(config, timeout=20.0)
        client.fine_tuning.jobs.list(limit=1)
    except Exception as exc:  # noqa: BLE001 - one answer per failure shape
        status = _status_code_of(exc)
        if status in (401, 403):
            return FineTuningCapabilities(
                supported=False,
                reason=(
                    f"This key cannot list fine-tuning jobs ({status}). The "
                    "endpoint may still support tuning — a key with the scope "
                    "would tell us."
                ),
                probed_at=probed_at,
            )
        if status in (404, 405, 501):
            return FineTuningCapabilities(
                supported=False,
                reason=(
                    f"This endpoint serves chat but not fine-tuning ({status} "
                    "from its fine-tuning route). Ollama, LM Studio and vLLM "
                    "answer this way."
                ),
                probed_at=probed_at,
            )
        return FineTuningCapabilities(
            supported=False,
            reason=f"Could not ask this endpoint about fine-tuning: {_redacted(exc, config)}",
            probed_at=probed_at,
        )

    return FineTuningCapabilities(
        supported=True,
        reason="This endpoint answers its fine-tuning routes.",
        base_models=_openai_tunable_models(config),
        surface="openai_compatible_v1",
        probed_at=probed_at,
    )


def _openai_tunable_models(config: ProviderConfig) -> tuple:
    """Base models the endpoint says can be tuned, or nothing.

    Nothing is guessed: an endpoint that does not advertise tunability gets an
    empty tuple and the panel asks the user to type a base model, exactly as
    the Model field already works. A hand-written list of "probably tunable"
    ids is the drift #241 was filed about.
    """
    try:
        listing = _openai_client(config, timeout=20.0).models.list()
    except Exception:  # noqa: BLE001 - a missing hint is not a failure
        return ()
    out: set = set()
    for model in getattr(listing, "data", None) or []:
        model_id = getattr(model, "id", None)
        if not model_id:
            continue
        # Only an explicit signal counts. Some endpoints report permissions or
        # capability flags; where none exists the tuple stays empty.
        allows = getattr(model, "allow_fine_tuning", None)
        if allows is None:
            capabilities = getattr(model, "capabilities", None)
            allows = (
                capabilities.get("fine_tuning")
                if isinstance(capabilities, dict)
                else None
            )
        if allows:
            out.add(str(model_id))
    return tuple(sorted(out))


def _require_openai_surface(config: ProviderConfig) -> None:
    api_type = (config.api_type or "").strip()
    if api_type in ("anthropic", "gemini"):
        raise FineTuningUnavailable(
            fine_tuning_capabilities(config).reason
        )


def upload_training_file(
    config: ProviderConfig, *, filename: str, content: bytes
) -> str:
    """Upload a JSONL training file and return the endpoint's file id."""
    api_type = (config.api_type or "").strip()
    if api_type == "testing":
        from utk_curio.backend.app.agents import testing_provider

        return testing_provider.scripted_upload_training_file(filename, content)
    _require_openai_surface(config)
    try:
        result = _openai_client(config).files.create(
            file=(filename, content), purpose="fine-tune",
        )
    except Exception as exc:  # noqa: BLE001
        raise FineTuningUnavailable(f"Could not upload the training file: {_redacted(exc, config)}") from exc
    file_id = getattr(result, "id", None)
    if not file_id:
        raise FineTuningUnavailable(
            "The endpoint accepted the upload but reported no file id."
        )
    return str(file_id)


def create_fine_tuning_job(
    config: ProviderConfig,
    *,
    training_file: str,
    base_model: str,
    suffix: str | None = None,
) -> FineTuningJob:
    """Start a tuning job at the endpoint and return it as reported."""
    api_type = (config.api_type or "").strip()
    if api_type == "testing":
        from utk_curio.backend.app.agents import testing_provider

        return testing_provider.scripted_create_fine_tuning_job(
            training_file=training_file, base_model=base_model, suffix=suffix
        )
    _require_openai_surface(config)
    payload: dict = {"training_file": training_file, "model": base_model}
    if suffix:
        payload["suffix"] = suffix
    try:
        job = _openai_client(config).fine_tuning.jobs.create(**payload)
    except Exception as exc:  # noqa: BLE001
        raise FineTuningUnavailable(f"The endpoint refused the job: {_redacted(exc, config)}") from exc
    return _job_from_openai(job, fallback_base_model=base_model)


def get_fine_tuning_job(config: ProviderConfig, job_id: str) -> FineTuningJob:
    """The endpoint's current word on a job."""
    api_type = (config.api_type or "").strip()
    if api_type == "testing":
        from utk_curio.backend.app.agents import testing_provider

        return testing_provider.scripted_get_fine_tuning_job(job_id)
    _require_openai_surface(config)
    try:
        job = _openai_client(config).fine_tuning.jobs.retrieve(job_id)
    except Exception as exc:  # noqa: BLE001
        raise FineTuningUnavailable(f"Could not read job {job_id}: {_redacted(exc, config)}") from exc
    return _job_from_openai(job)


def cancel_fine_tuning_job(config: ProviderConfig, job_id: str) -> FineTuningJob:
    """Ask the endpoint to cancel a job; return what it says afterwards.

    A cancel the endpoint refuses (already finished) is that refusal, reported
    — never a local status change that would make the record disagree with the
    provider.
    """
    api_type = (config.api_type or "").strip()
    if api_type == "testing":
        from utk_curio.backend.app.agents import testing_provider

        return testing_provider.scripted_cancel_fine_tuning_job(job_id)
    _require_openai_surface(config)
    try:
        job = _openai_client(config).fine_tuning.jobs.cancel(job_id)
    except Exception as exc:  # noqa: BLE001
        raise FineTuningUnavailable(f"Could not cancel job {job_id}: {_redacted(exc, config)}") from exc
    return _job_from_openai(job)


def _job_from_openai(job, *, fallback_base_model: str = "") -> FineTuningJob:
    raw = str(getattr(job, "status", "") or "")
    error = getattr(job, "error", None)
    message = None
    if error is not None:
        message = getattr(error, "message", None)
        if message is None and isinstance(error, dict):
            message = error.get("message")
        if message is not None:
            message = str(message) or None
    trained_tokens = getattr(job, "trained_tokens", None)
    return FineTuningJob(
        id=str(getattr(job, "id", "") or ""),
        # An unrecognised status stays "running" rather than being called
        # terminal: acting on a status we do not understand is worse than
        # waiting, and raw_status carries the endpoint's own word.
        status=_OPENAI_STATUS_MAP.get(raw.lower(), "running"),
        raw_status=raw,
        base_model=str(getattr(job, "model", "") or fallback_base_model),
        trained_model=(
            str(getattr(job, "fine_tuned_model", "") or "") or None
        ),
        trained_tokens=trained_tokens if isinstance(trained_tokens, int) else None,
        error=message,
    )
