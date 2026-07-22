"""Provider-neutral chat-completion port.

This is the one place raw LLM-provider SDKs are used, so LLM/provider behavior
stays out of the route/flow/node modules (the ``agents/`` ownership boundary in
the plan's module-encapsulation memo). Callers resolve a :class:`ProviderConfig`
(e.g. from the user's LLM settings or the aiconn default) and hand it to
:func:`run_chat_completion`; they never import ``openai`` / ``anthropic`` /
``google.generativeai`` directly.

The dispatch below was extracted verbatim from ``app/api/routes.py::_call_llm``
(behavior-preserving) and is the seam a future LangChain adapter would sit behind.

User-facing overview: ``docs/AGENTS.md``.
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


def run_chat_completion(config: ProviderConfig, messages: list) -> str:
    """Dispatch an LLM chat completion to the configured provider.

    ``messages`` is the OpenAI-style ``[{"role", "content"}, ...]`` list. Returns
    the assistant reply text.
    """
    api_type = config.api_type
    if api_type == "anthropic":
        import anthropic
        system_parts = [m["content"] for m in messages if m["role"] == "system"]
        chat_messages = [m for m in messages if m["role"] != "system"]
        client = anthropic.Anthropic(api_key=config.api_key)
        resp = client.messages.create(
            model=config.model,
            system="\n".join(system_parts) if system_parts else anthropic.NOT_GIVEN,
            messages=chat_messages,
            max_tokens=4096,
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
        response = chat.send_message(last_user_msg)
        return response.text
    else:  # openai_compatible (default)
        from openai import OpenAI
        kwargs = {"api_key": config.api_key or "no-key"}
        if config.base_url:
            kwargs["base_url"] = config.base_url
        client = OpenAI(**kwargs)
        completion = client.chat.completions.create(model=config.model, messages=messages)
        return completion.choices[0].message.content


def stream_chat_completion(config: ProviderConfig, messages: list):
    """Streaming twin of :func:`run_chat_completion`: yields reply-text deltas.

    Same provider dispatch and message handling; each yielded string is an
    incremental chunk of the assistant reply (memo ``dev/22``, SSE runtime).
    Callers that stop iterating close the underlying provider stream.
    """
    api_type = config.api_type
    if api_type == "anthropic":
        import anthropic
        system_parts = [m["content"] for m in messages if m["role"] == "system"]
        chat_messages = [m for m in messages if m["role"] != "system"]
        client = anthropic.Anthropic(api_key=config.api_key)
        with client.messages.stream(
            model=config.model,
            system="\n".join(system_parts) if system_parts else anthropic.NOT_GIVEN,
            messages=chat_messages,
            max_tokens=4096,
        ) as stream:
            for text in stream.text_stream:
                if text:
                    yield text
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
        for chunk in chat.send_message(last_user_msg, stream=True):
            text = getattr(chunk, "text", "")
            if text:
                yield text
    else:  # openai_compatible (default)
        from openai import OpenAI
        kwargs = {"api_key": config.api_key or "no-key"}
        if config.base_url:
            kwargs["base_url"] = config.base_url
        client = OpenAI(**kwargs)
        stream = client.chat.completions.create(
            model=config.model, messages=messages, stream=True
        )
        for chunk in stream:
            choices = getattr(chunk, "choices", None) or []
            delta = choices[0].delta if choices else None
            text = getattr(delta, "content", None) if delta is not None else None
            if text:
                yield text
