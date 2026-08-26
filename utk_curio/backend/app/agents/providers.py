"""Provider-neutral chat-completion port.

This is the one place raw LLM-provider SDKs are used, so LLM/provider behavior
stays out of the route/flow/node modules (the ``agents/`` ownership boundary in
the plan's module-encapsulation memo). Callers resolve a :class:`ProviderConfig`
(e.g. from the user's LLM settings or the aiconn default) and hand it to
:func:`run_chat_completion`; they never import ``openai`` / ``anthropic`` /
``google.generativeai`` directly.

The dispatch below was extracted verbatim from ``app/api/routes.py::_call_llm``
(behavior-preserving) and is the seam a future LangChain adapter would sit behind.

User-facing overview: ``docs/AGENT-CATALOG.md``.
"""

from __future__ import annotations

from dataclasses import dataclass


class ProviderError(RuntimeError):
    """Raised for provider-dispatch problems surfaced to the caller."""


@dataclass(frozen=True)
class ProviderConfig:
    """Resolved, provider-neutral connection config for one chat completion.

    ``api_type`` selects the backend: ``"anthropic"``, ``"gemini"``, or
    ``"openai_compatible"`` (the default, used by OpenAI, the aiconn sage200
    endpoint, Ollama, vLLM, etc.). ``base_url`` applies only to the
    openai-compatible backend; the others ignore it.
    """

    api_key: str
    api_type: str
    base_url: str
    model: str


def _capture_usage(usage_out: dict | None, input_tokens, output_tokens) -> None:
    """Record Actual token usage into the caller's sink (memo dev/37).

    Best-effort: only populated when the provider reports both counts; the sink
    stays empty otherwise. Never estimated (memo dev/11's labeling rule)."""
    if usage_out is None:
        return
    if isinstance(input_tokens, int) and isinstance(output_tokens, int):
        usage_out["inputTokens"] = input_tokens
        usage_out["outputTokens"] = output_tokens


def run_chat_completion(
    config: ProviderConfig,
    messages: list,
    max_output_tokens: int | None = None,
    usage_out: dict | None = None,
) -> str:
    """Dispatch an LLM chat completion to the configured provider.

    ``messages`` is the OpenAI-style ``[{"role", "content"}, ...]`` list. Returns
    the assistant reply text. ``max_output_tokens`` is the effective resource
    policy (memo dev/24); when unset the anthropic backend keeps its former
    4096 and the others use provider defaults.
    """
    api_type = config.api_type
    if api_type == "testing":
        # Scripted, deterministic, no network. Guarded on CURIO_TESTING inside
        # run_scripted_completion, so this branch cannot be reached on a real
        # deployment even if a config names it. See agents/testing_provider.py.
        from utk_curio.backend.app.agents.testing_provider import (
            run_scripted_completion,
        )

        return run_scripted_completion(messages, usage_out=usage_out)
    if api_type == "anthropic":
        import anthropic
        system_parts = [m["content"] for m in messages if m["role"] == "system"]
        chat_messages = [m for m in messages if m["role"] != "system"]
        client = anthropic.Anthropic(api_key=config.api_key)
        resp = client.messages.create(
            model=config.model,
            system="\n".join(system_parts) if system_parts else anthropic.NOT_GIVEN,
            messages=chat_messages,
            max_tokens=max_output_tokens or 4096,
        )
        usage = getattr(resp, "usage", None)
        _capture_usage(
            usage_out, getattr(usage, "input_tokens", None), getattr(usage, "output_tokens", None)
        )
        return resp.content[0].text
    elif api_type == "gemini":
        import google.generativeai as genai
        genai.configure(api_key=config.api_key)
        system_parts = [m["content"] for m in messages if m["role"] == "system"]
        chat_messages = [m for m in messages if m["role"] != "system"]
        history = []
        for m in chat_messages[:-1]:
            role = "user" if m["role"] == "user" else "model"
            history.append({"role": role, "parts": [m["content"]]})
        last_user_msg = chat_messages[-1]["content"] if chat_messages else ""
        system_instruction = "\n".join(system_parts) if system_parts else None
        gen_model = genai.GenerativeModel(config.model, system_instruction=system_instruction)
        chat = gen_model.start_chat(history=history)
        send_kwargs = {}
        if max_output_tokens:
            send_kwargs["generation_config"] = {"max_output_tokens": max_output_tokens}
        response = chat.send_message(last_user_msg, **send_kwargs)
        meta = getattr(response, "usage_metadata", None)
        _capture_usage(
            usage_out,
            getattr(meta, "prompt_token_count", None),
            getattr(meta, "candidates_token_count", None),
        )
        return response.text
    else:  # openai_compatible (default)
        from openai import OpenAI
        kwargs = {"api_key": config.api_key or "no-key"}
        if config.base_url:
            kwargs["base_url"] = config.base_url
        client = OpenAI(**kwargs)
        create_kwargs = {"model": config.model, "messages": messages}
        if max_output_tokens:
            create_kwargs["max_tokens"] = max_output_tokens
        completion = client.chat.completions.create(**create_kwargs)
        usage = getattr(completion, "usage", None)
        _capture_usage(
            usage_out, getattr(usage, "prompt_tokens", None), getattr(usage, "completion_tokens", None)
        )
        return completion.choices[0].message.content


def stream_chat_completion(
    config: ProviderConfig,
    messages: list,
    max_output_tokens: int | None = None,
    usage_out: dict | None = None,
):
    """Streaming twin of :func:`run_chat_completion`: yields reply-text deltas.

    Same provider dispatch and message handling; each yielded string is an
    incremental chunk of the assistant reply (memo ``dev/22``, SSE runtime).
    Callers that stop iterating close the underlying provider stream.
    """
    api_type = config.api_type
    if api_type == "testing":
        # The scripted reply, delivered as a single chunk. Splitting it would
        # only test the splitter: what the SSE runtime needs from a provider
        # is a deterministic sequence of deltas, and one is a sequence.
        from utk_curio.backend.app.agents.testing_provider import (
            run_scripted_completion,
        )

        yield run_scripted_completion(messages, usage_out=usage_out)
        return
    if api_type == "anthropic":
        import anthropic
        system_parts = [m["content"] for m in messages if m["role"] == "system"]
        chat_messages = [m for m in messages if m["role"] != "system"]
        client = anthropic.Anthropic(api_key=config.api_key)
        with client.messages.stream(
            model=config.model,
            system="\n".join(system_parts) if system_parts else anthropic.NOT_GIVEN,
            messages=chat_messages,
            max_tokens=max_output_tokens or 4096,
        ) as stream:
            for text in stream.text_stream:
                if text:
                    yield text
            try:
                usage = getattr(stream.get_final_message(), "usage", None)
                _capture_usage(
                    usage_out,
                    getattr(usage, "input_tokens", None),
                    getattr(usage, "output_tokens", None),
                )
            except Exception:
                pass  # usage is best-effort; the reply already streamed
    elif api_type == "gemini":
        import google.generativeai as genai
        genai.configure(api_key=config.api_key)
        system_parts = [m["content"] for m in messages if m["role"] == "system"]
        chat_messages = [m for m in messages if m["role"] != "system"]
        history = []
        for m in chat_messages[:-1]:
            role = "user" if m["role"] == "user" else "model"
            history.append({"role": role, "parts": [m["content"]]})
        last_user_msg = chat_messages[-1]["content"] if chat_messages else ""
        system_instruction = "\n".join(system_parts) if system_parts else None
        gen_model = genai.GenerativeModel(config.model, system_instruction=system_instruction)
        chat = gen_model.start_chat(history=history)
        send_kwargs = {}
        if max_output_tokens:
            send_kwargs["generation_config"] = {"max_output_tokens": max_output_tokens}
        last_chunk = None
        for chunk in chat.send_message(last_user_msg, stream=True, **send_kwargs):
            last_chunk = chunk
            text = getattr(chunk, "text", "")
            if text:
                yield text
        meta = getattr(last_chunk, "usage_metadata", None)
        _capture_usage(
            usage_out,
            getattr(meta, "prompt_token_count", None),
            getattr(meta, "candidates_token_count", None),
        )
    else:  # openai_compatible (default)
        from openai import OpenAI
        kwargs = {"api_key": config.api_key or "no-key"}
        if config.base_url:
            kwargs["base_url"] = config.base_url
        client = OpenAI(**kwargs)
        create_kwargs = {
            "model": config.model,
            "messages": messages,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if max_output_tokens:
            create_kwargs["max_tokens"] = max_output_tokens
        stream = client.chat.completions.create(**create_kwargs)
        for chunk in stream:
            usage = getattr(chunk, "usage", None)
            if usage is not None:
                _capture_usage(
                    usage_out,
                    getattr(usage, "prompt_tokens", None),
                    getattr(usage, "completion_tokens", None),
                )
            choices = getattr(chunk, "choices", None) or []
            delta = choices[0].delta if choices else None
            text = getattr(delta, "content", None) if delta is not None else None
            if text:
                yield text
