"""The account's LLM configurations: named endpoints and models, and the default.

One owner-only file per account, ``.curio/users/<key>/llm-configs.json``
(``common.owner_only_file``: 0600 in a 0700 directory, atomic writes under the
two-layer lock)::

    {"version": 1,
     "configs": {"<id>": {label, endpoint, apiType, baseUrl, apiKey, model,
                          createdAt, updatedAt}},
     "default": "<id>" | "<pick>" | null,
     "agents": {"<agentId>": "<id>" | "<pick>" | "deployment"}}

A configuration is the user's own endpoint (``endpoint`` is always ``own``):
its type, URL, key and model. This Curio's own endpoints (the operator's
endpoint file) take no configuration: one of their models is chosen as a
*pick*, ``curio:`` followed by the JSON pair ``["<endpoint name>", "<model>"]``
(:func:`pick_choice`), which holds any name, spaces, colons and slashes
included. A pick names no URL and no key: those are read from the endpoint
file when a run resolves it, and a pick the file no longer offers is refused
(:func:`pick_refusal`).

A ``null`` default means Curio's default, the endpoint file's first model,
when the operator named a file (``provider_config``).

``agents`` is the choice for an agent, keyed by the id before ``@`` so one
choice covers every version and project; ``"deployment"`` chooses Curio's
default. An agent with no entry follows the rules in
``provider_config.resolve_llm``. Nothing about the choice goes into a project,
so a shared project never carries one.

A configuration stored with ``endpoint`` ``deployment`` (an earlier Curio's
"This Curio install") is dropped when the file is read, with the default and
the agent choices that named it, so the account answers on its other choices.

Only :meth:`LlmConfigStore.record` returns a key, for ``provider_config`` to
build a run's config. Every other method returns refs without it.
"""

from __future__ import annotations

import json
import logging
import secrets
import time
from pathlib import Path
from urllib.parse import urlsplit

from utk_curio.backend.app.common import owner_only_file
from utk_curio.backend.app.common.user_storage import user_key_segment, users_base

log = logging.getLogger(__name__)

STORE_FILENAME = "llm-configs.json"
STORE_VERSION = 1
_LOCK_NAMESPACE = "llm-configs"

MAX_CONFIGS_PER_USER = 32
MAX_LABEL_CHARS = 80
MAX_MODEL_CHARS = 200
MAX_URL_CHARS = 500
MAX_KEY_CHARS = 4096

ENDPOINT_OWN = "own"
#: What an earlier Curio stored for a configuration on this Curio's endpoint.
#: Such a configuration is dropped on read, and a new one is refused.
ENDPOINT_DEPLOYMENT = "deployment"
#: The choice of Curio's default for an agent.
CHOICE_DEPLOYMENT = "deployment"
#: What starts a pick of one of this Curio's models.
PICK_PREFIX = "curio:"
#: The one sentence a configuration on this Curio's own endpoint is refused with.
DEPLOYMENT_REFUSAL = (
    "Curio's own models take no configuration: pick one on the Agent configuration tab."
)

#: The provider types a configuration may name. ``testing`` (the scripted
#: provider) is accepted only while it is enabled.
API_TYPES = ("openai_compatible", "anthropic", "gemini")
TESTING_API_TYPE = "testing"
#: Types whose SDK needs a key, by the name a refusal gives them.
_KEY_REQUIRED = {"anthropic": "an Anthropic", "gemini": "a Gemini"}
#: Types whose endpoint is the SDK's own: they take no base URL.
_NO_BASE_URL = ("anthropic", "gemini")

_CREATE_FIELDS = frozenset({"label", "endpoint", "apiType", "baseUrl", "apiKey", "model"})
_UPDATE_FIELDS = _CREATE_FIELDS | {"clearApiKey"}


class LlmConfigError(ValueError):
    """A request the store refuses, with the HTTP status it answers with."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def _testing_enabled() -> bool:
    # THE guard is ``testing_provider.enabled`` (tests patch it to admit the scripted provider);
    # read it, never a copy of it. Which is why this store lives in infrastructure beside it.
    from utk_curio.backend.app.agents.infrastructure import testing_provider

    return testing_provider.enabled()


def _one_line(value: object, field: str, max_chars: int, *, required: bool) -> str:
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise LlmConfigError(f"{field} must be a string")
    text = value.strip()
    if "\n" in text or "\r" in text:
        raise LlmConfigError(f"{field} must be one line")
    if len(text) > max_chars:
        raise LlmConfigError(f"{field} is longer than {max_chars} characters")
    if required and not text:
        raise LlmConfigError(f"{field} is required")
    return text


def _api_type(value: object) -> str:
    kind = _one_line(value, "apiType", 40, required=True)
    if kind in API_TYPES or (kind == TESTING_API_TYPE and _testing_enabled()):
        return kind
    raise LlmConfigError(f"apiType must be one of {', '.join(API_TYPES)}")


def _base_url(value: object, api_type: str) -> str:
    url = _one_line(value, "baseUrl", MAX_URL_CHARS, required=False)
    if api_type in _NO_BASE_URL:
        if url:
            raise LlmConfigError(f"a {api_type} configuration takes no base URL")
        return ""
    if not url:
        if api_type == "openai_compatible":
            raise LlmConfigError("an OpenAI-compatible configuration needs its base URL")
        return ""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise LlmConfigError("baseUrl must be an http(s) URL with a host")
    if parts.username or parts.password or "@" in parts.netloc:
        raise LlmConfigError("baseUrl must not carry a user name or password")
    if parts.query or parts.fragment:
        raise LlmConfigError("baseUrl must not carry a query or a fragment")
    return url.rstrip("/")


def _api_key(value: object) -> str:
    return _one_line(value, "apiKey", MAX_KEY_CHARS, required=False)


def _endpoint_identity(record: dict) -> tuple:
    """What a key belongs to: the provider type and the URL's scheme, host and port."""
    url = urlsplit(record.get("baseUrl") or "")
    return (record.get("apiType") or "", url.scheme, (url.hostname or "").lower(), url.port)


def _now() -> int:
    return int(time.time())


def pick_choice(endpoint_name: str, model: str) -> str:
    """The choice of *model* on this Curio's endpoint named *endpoint_name*.

    Canonical, so one pick is always the same text: the compact JSON that the
    page's ``JSON.stringify`` writes too, non-ASCII kept as it is."""
    return PICK_PREFIX + json.dumps([endpoint_name, model], separators=(",", ":"), ensure_ascii=False)


def is_pick(choice: object) -> bool:
    return isinstance(choice, str) and choice.startswith(PICK_PREFIX)


def parse_pick(choice: object) -> tuple[str, str] | None:
    """``(endpoint name, model)`` of a pick, or None when *choice* is not one
    or is malformed."""
    if not is_pick(choice):
        return None
    try:
        pair = json.loads(choice[len(PICK_PREFIX):])
    except ValueError:
        return None
    if (
        isinstance(pair, list) and len(pair) == 2
        and all(isinstance(part, str) and part for part in pair)
    ):
        return pair[0], pair[1]
    return None


def pick_refusal(choice: str, endpoints) -> str | None:
    """Why the pick *choice* does not run on this Curio, or None when one of
    *endpoints* (``llm_endpoint.Endpoint``) still offers it. The one sentence
    a save and a run give, naming every endpoint and model on offer."""
    from utk_curio.common.llm_endpoint import offered_models

    endpoints = tuple(endpoints)
    parsed = parse_pick(choice)
    if not endpoints:
        return "This Curio offers no models of its own."
    offer = offered_models(endpoints)
    if parsed is None:
        return f"{choice!r} is not one of Curio's models; it offers {offer}."
    endpoint_name, model = parsed
    endpoint = next((e for e in endpoints if e.name == endpoint_name), None)
    if endpoint is None:
        return f"Curio has no endpoint {endpoint_name!r}; it offers {offer}."
    if model not in endpoint.models:
        return f"{endpoint_name!r} offers no model {model!r}; Curio offers {offer}."
    return None


def _offered_pick(choice: str, endpoints) -> str:
    """*choice* written canonically, or the refusal of a pick not on offer."""
    refusal = pick_refusal(choice, endpoints)
    if refusal:
        raise LlmConfigError(refusal)
    return pick_choice(*parse_pick(choice))


def base_url_host(base_url: str, api_type: str = "") -> str:
    """What may be shown of an endpoint: its host and port, never a path or a key.

    A base URL can carry a key in its query string, so only the network
    location leaves the server. An endpoint with no base URL is named by its
    provider type."""
    text = (base_url or "").strip()
    if text:
        parsed = urlsplit(text if "//" in text else f"//{text}")
        if parsed.netloc:
            return parsed.netloc
    kind = (api_type or "").strip()
    return f"the default {kind} endpoint" if kind else ""


def public(config_id: str, record: dict) -> dict:
    """A configuration as every response carries it: the key reduced to ``hasApiKey``."""
    return {
        "id": config_id,
        "label": record.get("label") or "",
        "endpoint": record.get("endpoint") or ENDPOINT_OWN,
        "apiType": record.get("apiType") or "",
        "baseUrl": record.get("baseUrl") or "",
        "baseUrlHost": base_url_host(record.get("baseUrl") or "", record.get("apiType") or ""),
        "hasApiKey": bool(record.get("apiKey")),
        "model": record.get("model") or "",
        "createdAt": record.get("createdAt"),
        "updatedAt": record.get("updatedAt"),
    }


class LlmConfigStore:
    """File-backed store of one account's configurations. Only :meth:`record`
    returns a key."""

    def __init__(self, base: Path | None = None):
        self._base = base

    def _user_dir(self, user_key: str) -> Path:
        base = self._base if self._base is not None else users_base()
        return base / user_key_segment(user_key)

    def path(self, user_key: str) -> Path:
        return self._user_dir(user_key) / STORE_FILENAME

    def _locked(self, user_key: str):
        return owner_only_file.locked(
            self._user_dir(user_key), STORE_FILENAME, namespace=_LOCK_NAMESPACE, key=user_key
        )

    # -- file I/O ---------------------------------------------------------------

    def read(self, user_key: str) -> dict:
        """The document, or an empty one when the account has none. An
        unreadable file is an error, never an empty store: a run must not fall
        back to another configuration because this one could not be read."""
        path = self.path(user_key)
        if not path.is_file():
            return {"version": STORE_VERSION, "configs": {}, "default": None, "agents": {}}
        try:
            with open(path, "r", encoding="utf-8") as handle:
                doc = json.load(handle)
        except (OSError, ValueError) as exc:
            log.warning("llm-configs store for %s is unreadable (%s)", user_key, exc.__class__.__name__)
            raise LlmConfigError("the LLM configurations file is unreadable", 500)
        configs = doc.get("configs") if isinstance(doc, dict) else None
        if not isinstance(configs, dict):
            raise LlmConfigError("the LLM configurations file is malformed", 500)
        default = doc.get("default")
        agents = doc.get("agents")
        # A configuration on this Curio's own endpoint goes, with what named
        # it, so the account answers on its other choices.
        dropped = {
            k for k, v in configs.items()
            if isinstance(v, dict) and v.get("endpoint") == ENDPOINT_DEPLOYMENT
        }
        return {
            "version": STORE_VERSION,
            "configs": {k: v for k, v in configs.items() if isinstance(v, dict) and k not in dropped},
            "default": default if isinstance(default, str) and default not in dropped else None,
            "agents": {
                k: v for k, v in (agents if isinstance(agents, dict) else {}).items()
                if isinstance(k, str) and isinstance(v, str) and v not in dropped
            },
        }

    def _write(self, user_key: str, doc: dict) -> None:
        owner_only_file.write_json(self.path(user_key), doc)

    # -- reads --------------------------------------------------------------------

    def list(self, user_key: str) -> list[dict]:
        """Every configuration, oldest first, without keys."""
        configs = self.read(user_key)["configs"]
        ordered = sorted(configs.items(), key=lambda item: (item[1].get("createdAt") or 0, item[0]))
        return [public(config_id, record) for config_id, record in ordered]

    def default_id(self, user_key: str) -> str | None:
        """The default as stored: a configuration id, a pick, or None."""
        return self.read(user_key)["default"]

    def get(self, user_key: str, config_id: str) -> dict | None:
        record = self.read(user_key)["configs"].get(config_id)
        return public(config_id, record) if record is not None else None

    def record(self, user_key: str, config_id: str) -> dict | None:
        """The stored configuration WITH its key, or None. For resolution only."""
        record = self.read(user_key)["configs"].get(config_id)
        return dict(record) if record is not None else None

    def choices(self, user_key: str) -> dict:
        """``{agentId: configId | pick | "deployment"}``, as stored."""
        return dict(self.read(user_key)["agents"])

    # -- writes -------------------------------------------------------------------

    @staticmethod
    def _check_fields(body: object, allowed: frozenset) -> dict:
        if not isinstance(body, dict):
            raise LlmConfigError("send a JSON object")
        endpoint = body.get("endpoint")
        if endpoint == ENDPOINT_DEPLOYMENT:
            raise LlmConfigError(DEPLOYMENT_REFUSAL)
        if endpoint not in (None, "", ENDPOINT_OWN):
            raise LlmConfigError("endpoint must be 'own'")
        unknown = sorted(set(body) - allowed)
        if unknown:
            raise LlmConfigError(f"unknown field(s): {', '.join(unknown)}")
        return body

    @staticmethod
    def _check_label(configs: dict, label: str, *, except_id: str | None = None) -> None:
        folded = label.casefold()
        for config_id, record in configs.items():
            if config_id != except_id and (record.get("label") or "").casefold() == folded:
                raise LlmConfigError(f"a configuration is already labelled {label!r}")

    @staticmethod
    def _own_fields(*, api_type: str, base_url: object, api_key: str) -> dict:
        url = _base_url(base_url, api_type)
        if api_type in _KEY_REQUIRED and not api_key:
            raise LlmConfigError(f"{_KEY_REQUIRED[api_type]} configuration needs its API key")
        return {"apiType": api_type, "baseUrl": url, "apiKey": api_key}

    def create(self, user_key: str, body: object) -> dict:
        """Add a configuration of the user's own endpoint and return its ref.
        One on this Curio's own endpoint is refused: its models are picked,
        never configured (:data:`DEPLOYMENT_REFUSAL`)."""
        body = self._check_fields(body, _CREATE_FIELDS)
        label = _one_line(body.get("label"), "label", MAX_LABEL_CHARS, required=True)
        model = _one_line(body.get("model"), "model", MAX_MODEL_CHARS, required=True)
        fields = self._own_fields(
            api_type=_api_type(body.get("apiType")),
            base_url=body.get("baseUrl"), api_key=_api_key(body.get("apiKey")),
        )
        endpoint = ENDPOINT_OWN
        with self._locked(user_key):
            doc = self.read(user_key)
            if len(doc["configs"]) >= MAX_CONFIGS_PER_USER:
                raise LlmConfigError(f"an account holds at most {MAX_CONFIGS_PER_USER} configurations")
            self._check_label(doc["configs"], label)
            config_id = self._new_id(doc["configs"])
            now = _now()
            doc["configs"][config_id] = {
                "label": label, "endpoint": endpoint, "model": model, **fields,
                "createdAt": now, "updatedAt": now,
            }
            self._write(user_key, doc)
            return public(config_id, doc["configs"][config_id])

    def update(self, user_key: str, config_id: str, body: object) -> dict:
        """Change a configuration and return its ref. A blank key keeps the
        stored one; ``clearApiKey`` removes it. A key never follows its
        configuration to another endpoint: changing the type, or the URL's
        scheme, host or port, needs the key again."""
        body = self._check_fields(body, _UPDATE_FIELDS)
        with self._locked(user_key):
            doc = self.read(user_key)
            current = doc["configs"].get(config_id)
            if current is None:
                raise LlmConfigError(f"no LLM configuration {config_id!r}", 404)
            record = dict(current)
            if "label" in body:
                record["label"] = _one_line(body["label"], "label", MAX_LABEL_CHARS, required=True)
                self._check_label(doc["configs"], record["label"], except_id=config_id)
            if "model" in body:
                record["model"] = _one_line(body["model"], "model", MAX_MODEL_CHARS, required=True)
            new_key = _api_key(body.get("apiKey"))
            clear = body.get("clearApiKey") is True
            api_type = _api_type(body.get("apiType", record.get("apiType")))
            base_url = body.get("baseUrl", record.get("baseUrl"))
            api_key = new_key or ("" if clear else record.get("apiKey") or "")
            candidate = {**record, **self._own_fields(
                api_type=api_type, base_url=base_url, api_key=api_key,
            )}
            moved = _endpoint_identity(candidate) != _endpoint_identity(current)
            if moved and current.get("apiKey") and not new_key and not clear:
                raise LlmConfigError(
                    "enter the API key again: a key never follows its configuration "
                    "to a different endpoint"
                )
            record = candidate
            record["endpoint"] = ENDPOINT_OWN
            record["updatedAt"] = _now()
            doc["configs"][config_id] = record
            self._write(user_key, doc)
            return public(config_id, record)

    def delete(self, user_key: str, config_id: str) -> dict:
        """Remove a configuration, in one write with what pointed at it: the
        agents chosen to run on it go back to their rules (``moved``), and a
        removed default resets to Curio's default. Returns ``{deleted, moved,
        default}``."""
        with self._locked(user_key):
            doc = self.read(user_key)
            if config_id not in doc["configs"]:
                raise LlmConfigError(f"no LLM configuration {config_id!r}", 404)
            del doc["configs"][config_id]
            if doc["default"] == config_id:
                doc["default"] = None
            moved = sorted(agent_id for agent_id, chosen in doc["agents"].items() if chosen == config_id)
            for agent_id in moved:
                del doc["agents"][agent_id]
            self._write(user_key, doc)
            return {"deleted": config_id, "moved": moved, "default": doc["default"]}

    def duplicate(self, user_key: str, config_id: str, *, label: str | None = None,
                  model: str | None = None) -> dict:
        """Copy a configuration, its key included (the copy is made here, so
        the key never travels), under a new id and a free label."""
        with self._locked(user_key):
            doc = self.read(user_key)
            source = doc["configs"].get(config_id)
            if source is None:
                raise LlmConfigError(f"no LLM configuration {config_id!r}", 404)
            if len(doc["configs"]) >= MAX_CONFIGS_PER_USER:
                raise LlmConfigError(f"an account holds at most {MAX_CONFIGS_PER_USER} configurations")
            wanted = _one_line(label, "label", MAX_LABEL_CHARS, required=False) if label else ""
            if wanted:
                self._check_label(doc["configs"], wanted)
            else:
                wanted = self._free_label(doc["configs"], f"{source.get('label') or 'Configuration'} copy")
            record = dict(source)
            if model is not None:
                record["model"] = _one_line(model, "model", MAX_MODEL_CHARS, required=True)
            new_id = self._new_id(doc["configs"])
            now = _now()
            record.update({"label": wanted, "createdAt": now, "updatedAt": now})
            doc["configs"][new_id] = record
            self._write(user_key, doc)
            return public(new_id, record)

    def set_default(self, user_key: str, chosen: str | None, *, offered_endpoints: tuple = ()) -> str | None:
        """Make *chosen* the default: a configuration id, a pick of one of
        *offered_endpoints*' models (``llm_endpoint.Endpoint``), or ``None``
        (or ``"deployment"``) for Curio's default. Returns what is stored."""
        if chosen is not None and not isinstance(chosen, str):
            raise LlmConfigError("configId must be a configuration id, one of Curio's models or null")
        if chosen == CHOICE_DEPLOYMENT:
            chosen = None
        if is_pick(chosen):
            chosen = _offered_pick(chosen, offered_endpoints)
        with self._locked(user_key):
            doc = self.read(user_key)
            if chosen is not None and not is_pick(chosen) and chosen not in doc["configs"]:
                raise LlmConfigError(f"no LLM configuration {chosen!r}", 404)
            doc["default"] = chosen
            self._write(user_key, doc)
            return chosen

    def set_choices(self, user_key: str, body: object, *, choosable: frozenset,
                    offered_endpoints: tuple = ()) -> dict:
        """Apply a partial map of agent id to a configuration id, a pick of
        one of *offered_endpoints*' models, ``"deployment"`` (Curio's default)
        or ``null`` (which clears the choice), and return the stored map.
        Nothing is written unless every entry is valid."""
        if not isinstance(body, dict) or not body:
            raise LlmConfigError('send {"<agentId>": "<configId>" | "<pick>" | "deployment" | null}')
        with self._locked(user_key):
            doc = self.read(user_key)
            agents = dict(doc["agents"])
            for agent_id, chosen in body.items():
                if agent_id not in choosable:
                    raise LlmConfigError(f"{agent_id!r} is not an agent whose model you can choose")
                if chosen is None:
                    agents.pop(agent_id, None)
                    continue
                if chosen == CHOICE_DEPLOYMENT:
                    if not offered_endpoints:
                        raise LlmConfigError("This Curio offers no models of its own.")
                elif is_pick(chosen):
                    chosen = _offered_pick(chosen, offered_endpoints)
                elif not isinstance(chosen, str) or chosen not in doc["configs"]:
                    raise LlmConfigError(f"no LLM configuration {chosen!r}", 404)
                agents[agent_id] = chosen
            doc["agents"] = agents
            self._write(user_key, doc)
            return dict(agents)

    def set_choice(self, user_key: str, agent_id: str, chosen: str | None) -> None:
        """Set or clear one agent's choice with no checks on the agent id. For
        the server's own writes, never a request."""
        with self._locked(user_key):
            doc = self.read(user_key)
            if chosen is None:
                doc["agents"].pop(agent_id, None)
            elif chosen != CHOICE_DEPLOYMENT and not is_pick(chosen) and chosen not in doc["configs"]:
                raise LlmConfigError(f"no LLM configuration {chosen!r}", 404)
            else:
                doc["agents"][agent_id] = chosen
            self._write(user_key, doc)

    @staticmethod
    def _new_id(configs: dict) -> str:
        while True:
            candidate = f"llm-{secrets.token_hex(6)}"
            if candidate not in configs:
                return candidate

    @staticmethod
    def _free_label(configs: dict, base: str) -> str:
        taken = {(r.get("label") or "").casefold() for r in configs.values()}
        base = base[:MAX_LABEL_CHARS]
        if base.casefold() not in taken:
            return base
        n = 2
        while True:
            suffix = f" {n}"
            candidate = base[: MAX_LABEL_CHARS - len(suffix)] + suffix
            if candidate.casefold() not in taken:
                return candidate
            n += 1


_default_store: LlmConfigStore | None = None


def default_store() -> LlmConfigStore:
    global _default_store
    if _default_store is None:
        _default_store = LlmConfigStore()
    return _default_store
