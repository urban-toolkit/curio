"""Scripted agent turns: point a user at the scripted LLM and drive its queue."""

from .db_stubs import _get_json, _post_json, api_json


# ── scripted agent turns ─────────────────────────────────────────────────────
#
# An agent turn is downstream of one LLM call. These helpers point the caller's
# own user at the scripted provider and drive its queue over HTTP, so a test can
# run a real turn - tools, ledger, content parser, session persistence - against
# the live backend with no key and no network. Contract:
# ``app/agents/testing_provider.py``.
#
# The queue, the capture and the holds are each backend process's own, and a
# dataflow's turns run in the process that owns it, so every helper names the
# dataflow whose turns it scripts or reads (``dataflow``, which nginx routes
# the call by in a start of several processes). It is required: ``None`` is
# the home process's own calls, made for no dataflow.

#: The model name of the scripted configuration ``use_scripted_llm`` makes.
#: Never dispatched anywhere; a configuration needs a model.
SCRIPTED_MODEL = "scripted"
#: Its label, so a second call in one test finds it instead of adding another.
SCRIPTED_LABEL = "Scripted"


def use_scripted_llm(backend_url: str, token: str, *, model: str = SCRIPTED_MODEL,
                     label: str = SCRIPTED_LABEL) -> dict:
    """Make a scripted LLM configuration this user's default, and return it.

    Goes through the real API Settings routes (``/api/agents/llm``) rather than a
    test-only shortcut, so the resolution path under test is the production one.
    *model* and *label* name a configuration of the test's own, for a test that
    tells its calls apart from every other test's by their model (the monitor's
    LLM tokens).
    """
    listing = api_json(f"{backend_url}/api/agents/llm", token)
    config = next(
        (c for c in listing["configs"] if c["label"] == label), None
    ) or api_json(
        f"{backend_url}/api/agents/llm/configs", token, method="POST",
        payload={"label": label, "apiType": "testing", "model": model},
    )["config"]
    assert config["apiType"] == "testing" and config["model"] == model, config
    chosen = api_json(
        f"{backend_url}/api/agents/llm/default", token, method="PUT",
        payload={"configId": config["id"]},
    )
    assert chosen["default"] == config["id"], chosen
    return config


def script_agent_replies(
    backend_url: str, *replies: str | dict, dataflow: str | None, reset: bool = True,
    by_intent: dict | None = None, native_tools: bool = False,
    structured_output: bool = False, node_ids: tuple = (),
    attachment: str | None = None,
) -> int:
    """Queue *replies* for the next agent turns of *dataflow*, one per
    provider call.

    A multi-round run needs one entry per round: a reply carrying a
    ``toolRequest`` tail is answered by the runtime and the model is prompted
    again, so script the follow-up too. Returns how many are pending.

    A reply is its text, ``{"text", "toolCalls"}`` for native tool calls, or
    ``{"error", "status"}`` for an endpoint error. ``"hold": <name>`` in a
    reply object keeps the call that takes it waiting, as a slow model does,
    until ``release_agent_hold`` names it (``held_agent_calls`` says which
    holds calls wait on). *native_tools* makes the
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

    *attachment* gives the replies to that attachment's runs alone: two agents
    working at once each take their own, before the shared queue. Script the
    second agent with ``reset=False``, or the first one's replies go.

    Resets by default, the queue of the process that owns *dataflow*. A reply
    left over from a previous test would be consumed by this one, and the
    failure would point anywhere but at the cause.
    """
    payload = {"replies": list(replies), "reset": reset, "byIntent": dict(by_intent or {})}
    if native_tools or structured_output:
        payload["chatCapabilities"] = {"tools": native_tools, "structuredOutput": structured_output}
    if node_ids:
        payload["nodeIds"] = list(node_ids)
    if attachment:
        payload["attachmentId"] = attachment
    body = _post_json(f"{backend_url}/api/testing/agent-script", payload, dataflow=dataflow)
    return body["pending"]


def held_agent_calls(backend_url: str, *, dataflow: str | None) -> dict:
    """The holds scripted calls of *dataflow*'s turns wait on now, each with
    how many calls wait on it: a turn whose reply is held is at its model
    call. The read names ``held`` only while a call is held."""
    return _get_json(f"{backend_url}/api/testing/agent-script", dataflow=dataflow).get("held", {})


def release_agent_hold(backend_url: str, name: str, *, dataflow: str | None) -> dict:
    """Let the calls of *dataflow*'s turns held on *name* answer, and every
    later reply held on it, until the next reset. Returns the holds calls
    still wait on."""
    return _post_json(f"{backend_url}/api/testing/agent-script/release", {"hold": name},
                      dataflow=dataflow)["held"]


def captured_agent_prompts(backend_url: str, *, dataflow: str | None) -> list:
    """Every message list the scripted provider was handed for *dataflow*'s
    turns, oldest first.

    Each entry is the OpenAI-style ``[{"role", "content"}, ...]`` the run
    composed. This is how a per-agent test proves *which* agent ran: the reply
    is scripted and therefore says nothing, but the system turn carries that
    agent's own preamble and instruction bytes.
    """
    return _get_json(f"{backend_url}/api/testing/agent-script", dataflow=dataflow)["captured"]


def captured_agent_calls(backend_url: str, *, dataflow: str | None) -> list:
    """``{configId, model}`` of every scripted call of *dataflow*'s turns
    since the last reset, oldest first: which LLM configuration answered each
    one, never its key."""
    return _get_json(f"{backend_url}/api/testing/agent-script", dataflow=dataflow)["calls"]


def captured_agent_offers(backend_url: str, *, dataflow: str | None) -> list:
    """``{tools, toolChoice}`` of every scripted call of *dataflow*'s turns
    since the last reset, oldest first: the native tools each call offered,
    none on the fenced protocol."""
    return _get_json(f"{backend_url}/api/testing/agent-script", dataflow=dataflow)["offered"]


def captured_system_prompt(backend_url: str, *, dataflow: str | None, call: int = 0) -> str:
    """The system content of one captured call of *dataflow*'s turns (the
    first, by default)."""
    captured = captured_agent_prompts(backend_url, dataflow=dataflow)
    assert captured, "the scripted provider was never called"
    assert call < len(captured), (
        f"asked for call {call} but only {len(captured)} were made"
    )
    return "\n".join(
        m.get("content") or ""
        for m in captured[call]
        if m.get("role") == "system"
    )
