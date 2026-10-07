"""Scripted agent turns: point a user at the scripted LLM and drive its queue."""

from .db_stubs import _get_json, _post_json, _request_json, api_json


# ── scripted agent turns ─────────────────────────────────────────────────────
#
# An agent turn is downstream of one LLM call. These helpers point the caller's
# own user at the scripted provider and drive its queue over HTTP, so a test can
# run a real turn - tools, ledger, content parser, session persistence - against
# the live backend with no key and no network. Contract:
# ``app/agents/testing_provider.py``.

#: The model name of the scripted configuration ``use_scripted_llm`` makes.
#: Never dispatched anywhere; a configuration needs a model.
SCRIPTED_MODEL = "scripted"
#: Its label, so a second call in one test finds it instead of adding another.
SCRIPTED_LABEL = "Scripted"


def use_scripted_llm(backend_url: str, token: str) -> dict:
    """Make a scripted LLM configuration this user's default, and return it.

    Goes through the real API Settings routes (``/api/agents/llm``) rather than a
    test-only shortcut, so the resolution path under test is the production one.
    """
    listing = api_json(f"{backend_url}/api/agents/llm", token)
    config = next(
        (c for c in listing["configs"] if c["label"] == SCRIPTED_LABEL), None
    ) or api_json(
        f"{backend_url}/api/agents/llm/configs", token, method="POST",
        payload={"label": SCRIPTED_LABEL, "apiType": "testing", "model": SCRIPTED_MODEL},
    )["config"]
    assert config["apiType"] == "testing" and config["model"] == SCRIPTED_MODEL, config
    chosen = api_json(
        f"{backend_url}/api/agents/llm/default", token, method="PUT",
        payload={"configId": config["id"]},
    )
    assert chosen["default"] == config["id"], chosen
    return config


def script_agent_replies(
    backend_url: str, *replies: str | dict, reset: bool = True,
    by_intent: dict | None = None, native_tools: bool = False,
    structured_output: bool = False, node_ids: tuple = (),
) -> int:
    """Queue *replies* for the next agent turns, one per provider call.

    A multi-round run needs one entry per round: a reply carrying a
    ``toolRequest`` tail is answered by the runtime and the model is prompted
    again, so script the follow-up too. Returns how many are pending.

    A reply is its text, ``{"text", "toolCalls"}`` for native tool calls, or
    ``{"error", "status"}`` for an endpoint error. *native_tools* makes the
    scripted endpoint call tools natively, so runs are offered their tools
    instead of the fenced syntax (a reset puts it back on the fenced protocol).
    *structured_output* makes it take a reply schema, so a content generation
    run for an Autark node is held to the Autark document's schema: its reply
    is then scripted as the constrained JSON (``reply_schemas``).

    *by_intent* maps a substring of a delegated call's ``intent`` to its reply,
    for calls whose order the test cannot know (Solve's per-node content).

    *node_ids* are the uuids the next nodes an apply creates are given, in
    order, for a capture that shows the id: the applied turn prints it, and a
    random one wraps that line or not by its width.

    Resets by default. A reply left over from a previous test would be consumed
    by this one, and the failure would point anywhere but at the cause.
    """
    payload = {"replies": list(replies), "reset": reset, "byIntent": dict(by_intent or {})}
    if native_tools or structured_output:
        payload["chatCapabilities"] = {"tools": native_tools, "structuredOutput": structured_output}
    if node_ids:
        payload["nodeIds"] = list(node_ids)
    body =_post_json(f"{backend_url}/api/testing/agent-script", payload)
    return body["pending"]


def captured_agent_prompts(backend_url: str) -> list:
    """Every message list the scripted provider was handed, oldest first.

    Each entry is the OpenAI-style ``[{"role", "content"}, ...]`` the run
    composed. This is how a per-agent test proves *which* agent ran: the reply
    is scripted and therefore says nothing, but the system turn carries that
    agent's own preamble and instruction bytes.
    """
    return _get_json(f"{backend_url}/api/testing/agent-script")["captured"]


def captured_agent_calls(backend_url: str) -> list:
    """``{configId, model}`` of every scripted call since the last reset, oldest
    first: which LLM configuration answered each one, never its key."""
    return _get_json(f"{backend_url}/api/testing/agent-script")["calls"]


def captured_agent_offers(backend_url: str) -> list:
    """``{tools, toolChoice}`` of every scripted call since the last reset,
    oldest first: the native tools each call offered, none on the fenced
    protocol."""
    return _get_json(f"{backend_url}/api/testing/agent-script")["offered"]


def captured_system_prompt(backend_url: str, *, call: int = 0) -> str:
    """The system content of one captured call (the first, by default)."""
    captured = captured_agent_prompts(backend_url)
    assert captured, "the scripted provider was never called"
    assert call < len(captured), (
        f"asked for call {call} but only {len(captured)} were made"
    )
    return "\n".join(
        m.get("content") or ""
        for m in captured[call]
        if m.get("role") == "system"
    )


def reset_agent_script(backend_url: str) -> None:
    """Drop the scripted queue and the capture log."""
    _request_json(f"{backend_url}/api/testing/agent-script", method="DELETE")
