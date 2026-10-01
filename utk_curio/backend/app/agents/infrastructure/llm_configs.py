"""The account's LLM configurations: named endpoints and models, and the default.

One owner-only file per account, ``.curio/users/<key>/llm-configs.json``
(``common.owner_only_file``: 0600 in a 0700 directory, atomic writes under the
two-layer lock)::

    {"version": 1,
     "configs": {"<id>": {label, endpoint, apiType, baseUrl, apiKey, model,
                          origin, jobId?, sourceId?, createdAt, updatedAt}},
     "default": "<id>" | null,
     "agents": {"<agentId>": "<id>" | "deployment"}}

A configuration's ``endpoint`` is ``own`` (the user's type, URL and key) or
``deployment`` ("This Curio install": the user owns only the label and the
model; type, URL and key are read from the deployment when a run resolves it).
A ``null`` default means the deployment's own default, when the operator set
one (``provider_config``).

``agents`` is the configuration chosen for an agent, keyed by the id before
``@`` so one choice covers every version and project; ``"deployment"`` chooses
the Deployment default. An agent with no entry follows the rules in
``provider_config.resolve_llm``. Nothing about the choice goes into a project,
so a shared project never carries one.

Only :meth:`LlmConfigStore.record` returns a key, for ``provider_config`` to
build a run's config. Every other method returns refs without it.
"""

from __future__ import annotations

import json
import logging
import re
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
ENDPOINT_DEPLOYMENT = "deployment"
#: The choice of the Deployment default for an agent.
CHOICE_DEPLOYMENT = "deployment"
ORIGIN_USER = "user"
ORIGIN_TRAINED = "trained"

#: The provider types a configuration may name. ``testing`` (the scripted
#: provider) is accepted only while it is enabled.
API_TYPES = ("openai_compatible", "anthropic", "gemini")
TESTING_API_TYPE = "testing"
#: Types whose SDK needs a key, by the name a refusal gives them.
_KEY_REQUIRED = {"anthropic": "an Anthropic", "gemini": "a Gemini"}
#: Types whose endpoint is the SDK's own: they take no base URL.
_NO_BASE_URL = ("anthropic", "gemini")

CONFIG_ID_RE = re.compile(r"^llm-[0-9a-f]{12}$")
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


def base_url_host(base_url: str, api_type: str = "") -> str:
    """What may be shown of an endpoint: its host and port, never a path or a key."""
    from utk_curio.backend.app.agents.evaluation.training_host import host_of

    return host_of(base_url, api_type)


def public(config_id: str, record: dict) -> dict:
    """A configuration as every response carries it: the key reduced to ``hasApiKey``."""
    payload = {
        "id": config_id,
        "label": record.get("label") or "",
        "endpoint": record.get("endpoint") or ENDPOINT_OWN,
        "apiType": record.get("apiType") or "",
        "baseUrl": record.get("baseUrl") or "",
        "baseUrlHost": base_url_host(record.get("baseUrl") or "", record.get("apiType") or ""),
        "hasApiKey": bool(record.get("apiKey")),
        "model": record.get("model") or "",
        "origin": record.get("origin") or ORIGIN_USER,
        "createdAt": record.get("createdAt"),
        "updatedAt": record.get("updatedAt"),
    }
    for key in ("jobId", "sourceId"):
        if record.get(key):
            payload[key] = record[key]
    return payload


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
        return {
            "version": STORE_VERSION,
            "configs": {k: v for k, v in configs.items() if isinstance(v, dict)},
            "default": default if isinstance(default, str) else None,
            "agents": {
                k: v for k, v in (agents if isinstance(agents, dict) else {}).items()
                if isinstance(k, str) and isinstance(v, str)
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
        return self.read(user_key)["default"]

    def get(self, user_key: str, config_id: str) -> dict | None:
        record = self.read(user_key)["configs"].get(config_id)
        return public(config_id, record) if record is not None else None

    def record(self, user_key: str, config_id: str) -> dict | None:
        """The stored configuration WITH its key, or None. For resolution only."""
        record = self.read(user_key)["configs"].get(config_id)
        return dict(record) if record is not None else None

    def choices(self, user_key: str) -> dict:
        """``{agentId: configId | "deployment"}``, as stored."""
        return dict(self.read(user_key)["agents"])

    # -- writes -------------------------------------------------------------------

    @staticmethod
    def _check_fields(body: object, allowed: frozenset) -> dict:
        if not isinstance(body, dict):
            raise LlmConfigError("send a JSON object")
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

    def create(self, user_key: str, body: object, *, deployment_offered: bool,
               origin: str = ORIGIN_USER, extra: dict | None = None) -> dict:
        """Add a configuration and return its ref."""
        body = self._check_fields(body, _CREATE_FIELDS)
        endpoint = body.get("endpoint") or ENDPOINT_OWN
        if endpoint not in (ENDPOINT_OWN, ENDPOINT_DEPLOYMENT):
            raise LlmConfigError("endpoint must be 'own' or 'deployment'")
        label = _one_line(body.get("label"), "label", MAX_LABEL_CHARS, required=True)
        model = _one_line(body.get("model"), "model", MAX_MODEL_CHARS, required=True)
        if endpoint == ENDPOINT_DEPLOYMENT:
            if not deployment_offered:
                raise LlmConfigError("this Curio install offers no endpoint of its own")
            if any(body.get(k) for k in ("apiType", "baseUrl", "apiKey")):
                raise LlmConfigError("a This Curio install configuration takes only a label and a model")
            fields = {}
        else:
            fields = self._own_fields(
                api_type=_api_type(body.get("apiType")),
                base_url=body.get("baseUrl"), api_key=_api_key(body.get("apiKey")),
            )
        with self._locked(user_key):
            doc = self.read(user_key)
            if len(doc["configs"]) >= MAX_CONFIGS_PER_USER:
                raise LlmConfigError(f"an account holds at most {MAX_CONFIGS_PER_USER} configurations")
            self._check_label(doc["configs"], label)
            config_id = self._new_id(doc["configs"])
            now = _now()
            doc["configs"][config_id] = {
                "label": label, "endpoint": endpoint, "model": model, **fields,
                "origin": origin, **(extra or {}), "createdAt": now, "updatedAt": now,
            }
            self._write(user_key, doc)
            return public(config_id, doc["configs"][config_id])

    def update(self, user_key: str, config_id: str, body: object, *,
               deployment_offered: bool, locked_ids: frozenset = frozenset()) -> dict:
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
            endpoint = body.get("endpoint") or record.get("endpoint") or ENDPOINT_OWN
            if endpoint not in (ENDPOINT_OWN, ENDPOINT_DEPLOYMENT):
                raise LlmConfigError("endpoint must be 'own' or 'deployment'")
            new_key = _api_key(body.get("apiKey"))
            clear = body.get("clearApiKey") is True
            if endpoint == ENDPOINT_DEPLOYMENT:
                if not deployment_offered:
                    raise LlmConfigError("this Curio install offers no endpoint of its own")
                if any(body.get(k) for k in ("apiType", "baseUrl", "apiKey")):
                    raise LlmConfigError("a This Curio install configuration takes only a label and a model")
                for key in ("apiType", "baseUrl", "apiKey"):
                    record.pop(key, None)
            else:
                api_type = _api_type(body.get("apiType", record.get("apiType")))
                base_url = body.get("baseUrl", record.get("baseUrl"))
                api_key = new_key or ("" if clear else record.get("apiKey") or "")
                candidate = {**record, **self._own_fields(
                    api_type=api_type, base_url=base_url, api_key=api_key,
                )}
                moved = (
                    current.get("endpoint", ENDPOINT_OWN) != ENDPOINT_OWN
                    or _endpoint_identity(candidate) != _endpoint_identity(current)
                )
                if moved and current.get("apiKey") and not new_key and not clear:
                    raise LlmConfigError(
                        "enter the API key again: a key never follows its configuration "
                        "to a different endpoint"
                    )
                record = candidate
            record["endpoint"] = endpoint
            touches_endpoint = (
                record.get("endpoint") != current.get("endpoint")
                or _endpoint_identity(record) != _endpoint_identity(current)
                or record.get("apiKey") != current.get("apiKey")
            )
            if touches_endpoint and config_id in locked_ids:
                raise LlmConfigError(
                    "a training job is running on this configuration; its endpoint and key "
                    "cannot change until it ends", 409,
                )
            record["updatedAt"] = _now()
            doc["configs"][config_id] = record
            self._write(user_key, doc)
            return public(config_id, record)

    def delete(self, user_key: str, config_id: str, *, locked_ids: frozenset = frozenset()) -> dict:
        """Remove a configuration, in one write with what pointed at it: the
        agents chosen to run on it go back to their rules (``moved``), and a
        removed default resets to the deployment's. Returns ``{deleted, moved,
        default}``."""
        with self._locked(user_key):
            doc = self.read(user_key)
            if config_id not in doc["configs"]:
                raise LlmConfigError(f"no LLM configuration {config_id!r}", 404)
            if config_id in locked_ids:
                raise LlmConfigError(
                    "a training job is running on this configuration; it cannot be removed "
                    "until the job ends", 409,
                )
            del doc["configs"][config_id]
            if doc["default"] == config_id:
                doc["default"] = None
            moved = sorted(agent_id for agent_id, chosen in doc["agents"].items() if chosen == config_id)
            for agent_id in moved:
                del doc["agents"][agent_id]
            self._write(user_key, doc)
            return {"deleted": config_id, "moved": moved, "default": doc["default"]}

    def duplicate(self, user_key: str, config_id: str, *, label: str | None = None,
                  model: str | None = None, origin: str = ORIGIN_USER,
                  extra: dict | None = None) -> dict:
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
            record = {k: v for k, v in source.items() if k not in ("jobId", "sourceId")}
            if model is not None:
                record["model"] = _one_line(model, "model", MAX_MODEL_CHARS, required=True)
            new_id = self._new_id(doc["configs"])
            now = _now()
            record.update({"label": wanted, "origin": origin, **(extra or {}),
                           "createdAt": now, "updatedAt": now})
            doc["configs"][new_id] = record
            self._write(user_key, doc)
            return public(new_id, record)

    def set_default(self, user_key: str, config_id: str | None) -> str | None:
        """Make *config_id* the default, or ``None`` for the deployment's."""
        if config_id is not None and not isinstance(config_id, str):
            raise LlmConfigError("configId must be a configuration id or null")
        with self._locked(user_key):
            doc = self.read(user_key)
            if config_id is not None and config_id not in doc["configs"]:
                raise LlmConfigError(f"no LLM configuration {config_id!r}", 404)
            doc["default"] = config_id
            self._write(user_key, doc)
            return config_id

    def set_choices(self, user_key: str, body: object, *, choosable: frozenset,
                    deployment_default: bool) -> dict:
        """Apply a partial map of agent id to a configuration id,
        ``"deployment"`` or ``null`` (which clears the choice), and return the
        stored map. Nothing is written unless every entry is valid."""
        if not isinstance(body, dict) or not body:
            raise LlmConfigError('send {"<agentId>": "<configId>" | "deployment" | null}')
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
                    if not deployment_default:
                        raise LlmConfigError("this Curio has no Deployment default to choose")
                elif not isinstance(chosen, str) or chosen not in doc["configs"]:
                    raise LlmConfigError(f"no LLM configuration {chosen!r}", 404)
                agents[agent_id] = chosen
            doc["agents"] = agents
            self._write(user_key, doc)
            return dict(agents)

    def set_choice(self, user_key: str, agent_id: str, chosen: str | None) -> None:
        """Set or clear one agent's choice with no checks on the agent id. For
        the server's own writes (activating a trained model), never a request."""
        with self._locked(user_key):
            doc = self.read(user_key)
            if chosen is None:
                doc["agents"].pop(agent_id, None)
            elif chosen != CHOICE_DEPLOYMENT and chosen not in doc["configs"]:
                raise LlmConfigError(f"no LLM configuration {chosen!r}", 404)
            else:
                doc["agents"][agent_id] = chosen
            self._write(user_key, doc)

    def free_label(self, user_key: str, base: str) -> str:
        """*base*, or *base* with a number after it, whichever no configuration uses."""
        return self._free_label(self.read(user_key)["configs"], base)

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
