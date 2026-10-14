"""The dashboard agent: a chat on a dataflow's dashboard that sets its widgets and runs it.

The dashboard page sends what it shows: each widget of a pinned tile (a
*control*: its id, node, scenario, name, type, options and value), the
scenarios' names, and whether this viewer may run the dataflow. One model turn
answers with a reply, the changes it makes ``[{id, value}]``, whether to run,
and whether it needs the user to say more first. Every change is checked here
against the control it names (``check_widget_value``); the page applies what
passes as a widget change and runs as its Run button does.

Nothing is saved: the transcript lives in the page, as a dashboard run does.
The LLM is the requester's own (:func:`resolve_config`): their default
configuration, else the Deployment default, else the first configuration they
added, so adding one is enough. A visitor on someone else's dashboard answers
with their own, and with none is refused with the remedy that opens API Settings.
"""

from __future__ import annotations

import json
import re

from utk_curio.backend.app.agents.application import reply_schemas
from utk_curio.backend.app.agents.infrastructure import chat_capabilities
from utk_curio.backend.app.agents.infrastructure import llm_configs
from utk_curio.backend.app.agents.infrastructure import provider_config
from utk_curio.backend.app.agents.infrastructure import providers as agents_providers
from utk_curio.backend.app.agents.infrastructure.providers import ChatTurn
from utk_curio.backend.app.agents.infrastructure.providers import ProviderConfig
from utk_curio.backend.app.agents.infrastructure.providers import ReplySchemaRefused
from utk_curio.backend.app.agents.repositories import ledger
from utk_curio.backend.app.execution.code_references import WIDGET_KINDS, check_widget_value

MAX_MESSAGE_CHARS = 4000
MAX_HISTORY = 20
MAX_CONTROLS = 200
MAX_SCENARIOS = 50
MAX_OUTPUT_TOKENS = 2048

SYSTEM_PROMPT = """\
You are the agent of a Curio dashboard. The dashboard shows the outputs of a \
dataflow and the widgets (controls) that set its parameters. The user asks you, in \
plain language, to change one or more control values, to run the dataflow \
(rerun the simulation), or both. You can also answer questions about the controls.

The controls are listed below as JSON. Each has an "id" (use it verbatim), the \
node it belongs to, the scenario it belongs to (null when it is in none), its \
name and label, its type, its options (choices, min, max, step, units) and its \
current value.

Rules:
- Change only the controls the user asks for. Several at once is fine.
- A value must fit its control: a number within min and max for "number" and \
"slider"; one of the choices for "choice"; a list of choices for "checkbox-group" \
and "multi-select"; true or false for "checkbox"; "YYYY-MM-DDTHH:MM:SS" for \
"datetime"; {"lat": .., "lon": ..} for "location"; [low, high] for "range"; a \
list for "number-list" and "text-list"; a string for "text".
- Controls with the same name or label can appear in several scenarios. When the \
user does not say which scenario they mean and more than one has the control, do \
not change anything: set "needsClarification" to true and ask which scenario \
(name them). Do the same when a request is ambiguous in any other way. When the \
user says "all scenarios" or "every scenario", change each copy.
- Set "run" to true only when the user asks to run, rerun or simulate. When \
running is not allowed for this viewer (canRun is false), set "run" to false and \
say so.
- "reply" is one or two short sentences to the user saying what you changed \
(with the old and new values) or asking your question.

Answer with one JSON object and nothing else:
{"reply": "...", "changes": [{"id": "<control id>", "valueJson": "<the new value as JSON>"}], \
"run": false, "needsClarification": false}
"valueJson" is the value written as JSON text: 3 is "3", "summer" is "\\"summer\\"", \
true is "true", [1, 2] is "[1, 2]".
"""

#: The reply's shape. Every key is required and every object closed, which both
#: OpenAI's strict mode and Anthropic's format take; the value of a change is a
#: JSON string because a widget's value has no one type.
REPLY_SCHEMA = {
    "type": "object",
    "properties": {
        "reply": {"type": "string"},
        "changes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"id": {"type": "string"}, "valueJson": {"type": "string"}},
                "required": ["id", "valueJson"],
                "additionalProperties": False,
            },
        },
        "run": {"type": "boolean"},
        "needsClarification": {"type": "boolean"},
    },
    "required": ["reply", "changes", "run", "needsClarification"],
    "additionalProperties": False,
}

_REPLY_SCHEMA_TYPES = ("anthropic", "openai_compatible", "testing")


class DashboardChatError(ValueError):
    """A request the dashboard agent cannot take: a 400."""


def _text(value, limit: int) -> str:
    return value[:limit] if isinstance(value, str) else ""


def _controls(raw) -> list[dict]:
    if not isinstance(raw, list):
        raise DashboardChatError("controls must be a list")
    if len(raw) > MAX_CONTROLS:
        raise DashboardChatError(f"a dashboard offers at most {MAX_CONTROLS} controls to the agent")
    out, seen = [], set()
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        control_id = entry.get("id")
        kind = entry.get("type")
        if not isinstance(control_id, str) or not control_id or control_id in seen or kind not in WIDGET_KINDS:
            continue
        seen.add(control_id)
        options = entry.get("options") if isinstance(entry.get("options"), dict) else {}
        scenario = entry.get("scenario")
        out.append({
            "id": control_id,
            "node": _text(entry.get("node"), 200),
            "scenario": scenario if isinstance(scenario, str) and scenario else None,
            "name": _text(entry.get("name"), 64),
            "label": _text(entry.get("label"), 200),
            "type": kind,
            "options": options,
            # A file widget's text can be long, and the model has no use for it.
            "value": None if kind == "file" else entry.get("value"),
        })
    return out


def _history(raw) -> list[dict]:
    if not isinstance(raw, list):
        return []
    turns = []
    for entry in raw[-MAX_HISTORY:]:
        if isinstance(entry, dict) and entry.get("role") in ("user", "assistant"):
            content = _text(entry.get("content"), MAX_MESSAGE_CHARS)
            if content:
                turns.append({"role": entry["role"], "content": content})
    return turns


def build_messages(message: str, history: list[dict], controls: list[dict],
                   scenarios: list[str], can_run: bool) -> list[dict]:
    """The system turn (instructions and the dashboard as it is), the earlier turns, the new message."""
    context = json.dumps(
        {"canRun": can_run, "scenarios": scenarios, "controls": controls},
        ensure_ascii=False, default=str,
    )
    system = f"{SYSTEM_PROMPT}\nThe dashboard now:\n{context}"
    return [{"role": "system", "content": system}, *history, {"role": "user", "content": message}]


def _object_in(text: str) -> dict | None:
    """The JSON object a reply holds: the whole text, a fenced block, or the outermost braces."""
    candidates = [text.strip()]
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fenced:
        candidates.append(fenced.group(1))
    start, end = text.find("{"), text.rfind("}")
    if 0 <= start < end:
        candidates.append(text[start:end + 1])
    for candidate in candidates:
        try:
            value = json.loads(candidate)
        except (ValueError, TypeError):
            continue
        if isinstance(value, dict):
            return value
    return None


def _value_of(change: dict):
    if "valueJson" in change:
        raw = change["valueJson"]
        if not isinstance(raw, str):
            return raw
        try:
            return json.loads(raw)
        except ValueError:
            # A bare text a model wrote without quoting it.
            return raw
    return change.get("value")


def interpret(text: str, controls: list[dict], can_run: bool) -> dict:
    """The page's answer from the model's reply: the reply, the changes that
    fit their controls, those that do not and why, and whether to run."""
    document = _object_in(text or "")
    if document is None:
        return {"reply": (text or "").strip() or "I could not answer that. Try again.",
                "changes": [], "rejected": [], "run": False, "needsClarification": False}
    reply = document.get("reply") if isinstance(document.get("reply"), str) else ""
    clarify = document.get("needsClarification") is True
    by_id = {control["id"]: control for control in controls}
    changes, rejected = [], []
    raw_changes = document.get("changes") if isinstance(document.get("changes"), list) else []
    if not clarify:
        for change in raw_changes:
            if not isinstance(change, dict):
                continue
            control = by_id.get(change.get("id"))
            if control is None:
                rejected.append({"id": str(change.get("id")), "problem": "The dashboard has no such control."})
                continue
            value = _value_of(change)
            problem = check_widget_value({"type": control["type"], "options": control["options"]}, value)
            if problem:
                rejected.append({"id": control["id"], "problem": problem})
                continue
            changes = [c for c in changes if c["id"] != control["id"]]
            changes.append({"id": control["id"], "value": value})
    run = document.get("run") is True and not clarify and can_run
    return {
        "reply": reply.strip() or ("Done." if changes or run else "I did not change anything."),
        "changes": changes,
        "rejected": rejected,
        "run": run,
        "needsClarification": clarify,
    }


def _reply_schema(config: ProviderConfig, user_key: str) -> dict | None:
    """The reply schema this endpoint takes, or None (it takes none, or refused one before)."""
    if config.api_type not in _REPLY_SCHEMA_TYPES:
        return None
    if (config.api_type, config.base_url or "", config.model) in reply_schemas._refused:
        return None
    try:
        if not chat_capabilities.chat_capabilities(config, user_key).structured_output:
            return None
    except Exception:  # noqa: BLE001 - the question never fails a turn
        return None
    return {"name": "dashboard_reply", "schema": REPLY_SCHEMA}


def resolve_config(user_key: str, *, guest: bool) -> ProviderConfig:
    """The configuration a turn answers with: what ``resolve_llm`` answers with
    no agent, else the account's first configuration. The dashboard agent has
    no row in Agent configuration, so a configuration added but not made the
    default would otherwise leave it refused."""
    try:
        return provider_config.resolve_llm(user_key, guest=guest)
    except provider_config.ProviderConfigError:
        if provider_config.is_hosted_guest(user_key, guest=guest):
            raise
        try:
            configs = llm_configs.default_store().read(user_key)["configs"]
        except llm_configs.LlmConfigError:
            configs = {}
        if not configs:
            raise
        config_id, record = min(configs.items(), key=lambda item: (item[1].get("createdAt") or 0, item[0]))
        return provider_config.build_config(
            user_key, config_id, record, source=provider_config.SOURCE_DEFAULT, guest=guest,
        )


def respond(user_key: str, config: ProviderConfig, body: dict) -> dict:
    """One dashboard agent turn for *body* (``message``, ``history``,
    ``controls``, ``scenarios``, ``canRun``)."""
    if not isinstance(body, dict):
        raise DashboardChatError("expected a JSON object")
    message = body.get("message")
    if not isinstance(message, str) or not message.strip():
        raise DashboardChatError("message is required")
    if len(message) > MAX_MESSAGE_CHARS:
        raise DashboardChatError(f"a message is at most {MAX_MESSAGE_CHARS} characters")
    controls = _controls(body.get("controls", []))
    raw_scenarios = body.get("scenarios") if isinstance(body.get("scenarios"), list) else []
    scenarios = [s[:200] for s in raw_scenarios[:MAX_SCENARIOS] if isinstance(s, str) and s]
    can_run = body.get("canRun") is True
    messages = build_messages(message.strip(), _history(body.get("history")), controls, scenarios, can_run)

    usage: dict = {}
    schema = _reply_schema(config, user_key)
    try:
        turn = agents_providers.run_chat_turn(
            config, messages, max_output_tokens=MAX_OUTPUT_TOKENS, usage_out=usage, reply_schema=schema,
        )
    except ReplySchemaRefused:
        reply_schemas.note_refused(config)
        turn = agents_providers.run_chat_turn(
            config, messages, max_output_tokens=MAX_OUTPUT_TOKENS, usage_out=usage,
        )
    finally:
        ledger.record_housekeeping_usage(
            user_key, usage, note="dashboard-chat", llm_config_id=config.config_id
        )
    return interpret(ChatTurn.of(turn).text, controls, can_run)
