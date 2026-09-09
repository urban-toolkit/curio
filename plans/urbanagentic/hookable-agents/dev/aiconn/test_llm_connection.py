#!/usr/bin/env python3
"""Gradio harness for the UIC sage200 OpenAI-compatible LLM endpoint.

Defaults match the provider notes in this folder's screenshots:
  - base URL: https://sage200.evl.uic.edu
  - models: llama4-nim, gemma4

Set AICONN_API_KEY in the environment or paste the key in the UI.
"""

from __future__ import annotations

import os
import traceback
from typing import Any

import gradio as gr
from openai import APIConnectionError, APIStatusError, AuthenticationError, OpenAI

DEFAULT_BASE_URL = "https://sage200.evl.uic.edu"
DEFAULT_MODELS = ["llama4-nim", "gemma4"]
DEFAULT_SYSTEM_PROMPT = "You are a helpful assistant."
TEST_PROMPT = "Reply with exactly connection ok"

# Cyrillic letters that look like Latin ones when copied from chat/screenshots.
_CYRILLIC_HOMOGLYPHS = str.maketrans(
    {
        "\u0430": "a",
        "\u0435": "e",
        "\u043e": "o",
        "\u0440": "p",
        "\u0441": "c",
        "\u0443": "y",
        "\u0445": "x",
        "\u0456": "i",
        "\u0410": "A",
        "\u0412": "B",
        "\u0415": "E",
        "\u041a": "K",
        "\u041c": "M",
        "\u041d": "H",
        "\u041e": "O",
        "\u0420": "P",
        "\u0421": "C",
        "\u0422": "T",
        "\u0425": "X",
        "\u0406": "I",
    }
)


def normalize_base_url(base_url: str) -> str:
    url = (base_url or DEFAULT_BASE_URL).strip().rstrip("/")
    if not url.endswith("/v1"):
        url = f"{url}/v1"
    return url


def normalize_api_key(api_key: str) -> tuple[str, list[str]]:
    raw = (api_key or os.environ.get("AICONN_API_KEY") or "no-key").strip()
    normalized = raw.translate(_CYRILLIC_HOMOGLYPHS)
    notes: list[str] = []

    if normalized != raw:
        notes.append(
            "Replaced look-alike Cyrillic characters in the API key with Latin ASCII "
            "(common when copying from Discord or screenshots)."
        )

    try:
        normalized.encode("ascii")
    except UnicodeEncodeError as exc:
        bad_char = raw[exc.start : exc.start + 1]
        notes.append(
            "API key still contains non-ASCII characters "
            f"(for example {bad_char!r} at position {exc.start}). "
            "Re-type the key manually instead of pasting."
        )

    return normalized, notes


def build_client(api_key: str, base_url: str) -> tuple[OpenAI, list[str]]:
    clean_key, notes = normalize_api_key(api_key)
    client = OpenAI(
        api_key=clean_key,
        base_url=normalize_base_url(base_url),
    )
    return client, notes


def mask_api_key(api_key: str) -> str:
    if len(api_key) <= 10:
        return "***"
    return f"{api_key[:7]}...{api_key[-5:]}"


def format_error(exc: Exception, api_key: str = "") -> str:
    if isinstance(exc, UnicodeEncodeError):
        return (
            "UnicodeEncodeError while sending the request. "
            "The API key likely contains a non-ASCII character "
            "(often Cyrillic 'х' instead of Latin 'x'). "
            "Re-type the key manually or paste from plain text."
        )
    if isinstance(exc, (AuthenticationError, APIStatusError)):
        status = getattr(exc, "status_code", 401)
        body = getattr(exc, "body", None) or {}
        error = body.get("error", {}) if isinstance(body, dict) else {}
        error_type = error.get("type", "")
        error_message = error.get("message", str(exc))

        if status == 401 or error_type == "token_not_found_in_db":
            masked = mask_api_key(api_key) if api_key else "unknown"
            return (
                "HTTP 401: API key rejected by the LiteLLM proxy.\n\n"
                f"Key sent (masked): {masked}\n\n"
                "The server is reachable, but this token is not registered in "
                "LiteLLM. Common causes:\n"
                "- Wrong key (original screenshot key had typos; Discord corrected it to "
                "sk-QJx3nVlwdKbbbwYI_1dxJg — note Vl and YI)\n"
                "- Key expired or revoked\n"
                "- Key not yet provisioned for your account\n\n"
                "Ask the sage200 admin (Andres Quesada) for a fresh key if this one still fails.\n\n"
                f"Server message: {error_message}"
            )

        detail = f"\nResponse body: {body}" if body else ""
        return f"HTTP {status}: {error_message}{detail}"
    if isinstance(exc, APIConnectionError):
        return f"Connection failed: {exc}"
    return f"{type(exc).__name__}: {exc}"


def run_completion(
    api_key: str,
    base_url: str,
    model: str,
    messages: list[dict[str, Any]],
    max_tokens: int = 256,
) -> tuple[str, str]:
    clean_key, key_notes = normalize_api_key(api_key)
    client, _ = build_client(api_key, base_url)
    endpoint = normalize_base_url(base_url)
    try:
        completion = client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
        )
        text = completion.choices[0].message.content or ""
        usage = completion.usage
        meta = (
            f"Connected to {endpoint}\n"
            f"Model: {model}\n"
            f"Finish reason: {completion.choices[0].finish_reason}\n"
        )
        if usage:
            meta += (
                f"Tokens - prompt: {usage.prompt_tokens}, "
                f"completion: {usage.completion_tokens}, "
                f"total: {usage.total_tokens}"
            )
        if key_notes:
            meta = "\n".join(key_notes) + "\n\n" + meta
        return text.strip(), meta
    except Exception as exc:
        detail = format_error(exc, clean_key)
        if key_notes:
            detail = "\n".join(key_notes) + "\n\n" + detail
        return "", detail


def test_connection(
    api_key: str,
    base_url: str,
    model: str,
    system_prompt: str,
) -> tuple[str, str]:
    messages = [
        {"role": "system", "content": system_prompt or DEFAULT_SYSTEM_PROMPT},
        {"role": "user", "content": TEST_PROMPT},
    ]
    reply, meta = run_completion(api_key, base_url, model, messages, max_tokens=32)
    if not reply:
        if "HTTP 401" in meta or "token_not_found_in_db" in meta:
            return "Server reachable, but API key rejected (401).", meta
        if "Connection failed" in meta:
            return "Could not reach server.", meta
        return "Connection test failed.", meta
    if "connection ok" in reply.lower():
        status = "Connection test passed."
    else:
        status = f"Connection succeeded, but the model replied unexpectedly:\n{reply}"
    return status, meta


def chat(
    message: str,
    history: list[tuple[str, str]],
    api_key: str,
    base_url: str,
    model: str,
    system_prompt: str,
) -> tuple[list[tuple[str, str]], str]:
    if not message.strip():
        return history, "Enter a message to send."

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt or DEFAULT_SYSTEM_PROMPT},
    ]
    for user_text, assistant_text in history:
        messages.append({"role": "user", "content": user_text})
        if assistant_text:
            messages.append({"role": "assistant", "content": assistant_text})
    messages.append({"role": "user", "content": message.strip()})

    reply, meta = run_completion(api_key, base_url, model, messages)
    if not reply:
        return history, meta

    updated_history = history + [(message.strip(), reply)]
    return updated_history, meta


def build_app() -> gr.Blocks:
    env_key = os.environ.get("AICONN_API_KEY", "")

    with gr.Blocks(title="UIC sage200 LLM connection test") as app:
        gr.Markdown(
            """
            # UIC sage200 LLM connection test

            OpenAI-compatible endpoint from the provider notes in this folder.
            Use the corrected API key from the Discord screenshot, or set `AICONN_API_KEY`.
            If you see a `UnicodeEncodeError`, re-type the key manually — pasted keys often
            contain Cyrillic look-alikes (for example `х` instead of `x`).
            """
        )

        with gr.Row():
            base_url = gr.Textbox(
                label="Base URL",
                value=DEFAULT_BASE_URL,
                placeholder="https://sage200.evl.uic.edu",
            )
            model = gr.Dropdown(
                label="Model",
                choices=DEFAULT_MODELS,
                value=DEFAULT_MODELS[0],
                allow_custom_value=True,
            )

        with gr.Row():
            api_key = gr.Textbox(
                label="API key",
                value=env_key,
                type="password",
                placeholder="sk-… (or set AICONN_API_KEY)",
            )
            system_prompt = gr.Textbox(
                label="System prompt",
                value=DEFAULT_SYSTEM_PROMPT,
            )

        status = gr.Textbox(label="Status", interactive=False)
        meta = gr.Textbox(label="Details", interactive=False, lines=6)

        test_btn = gr.Button("Test connection", variant="primary")

        chatbot = gr.Chatbot(label="Chat", height=360)
        user_message = gr.Textbox(label="Message", placeholder="Why is the sky blue?")
        send_btn = gr.Button("Send")

        test_btn.click(
            fn=test_connection,
            inputs=[api_key, base_url, model, system_prompt],
            outputs=[status, meta],
        )

        send_btn.click(
            fn=chat,
            inputs=[user_message, chatbot, api_key, base_url, model, system_prompt],
            outputs=[chatbot, meta],
        ).then(lambda: "", outputs=user_message)

        user_message.submit(
            fn=chat,
            inputs=[user_message, chatbot, api_key, base_url, model, system_prompt],
            outputs=[chatbot, meta],
        ).then(lambda: "", outputs=user_message)

        gr.Markdown(
            """
            **Notes**
            - `/v1` is appended automatically when missing from the base URL.
            - `gemma4` is the Google Gemma model on this server; `llama4-nim` is the default example model.
            """
        )

    return app


def main() -> None:
    app = build_app()
    app.launch()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        raise
