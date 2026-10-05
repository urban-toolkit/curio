"""What a provider was last seen to serve, so suggestions need no maintainer.

#241 asked whether Curio should discover models by querying the provider, ship a
fixed list, or do both. It does both - but the second half is **derived from the
API too**, not typed by hand.

The first version of this module held a literal table of model ids per provider.
That was wrong in a way that only shows up later: a hand-maintained list drifts
the moment a provider ships or retires a model, nobody notices because stale
suggestions still look plausible, and it can never cover a custom
OpenAI-compatible endpoint at all - there is no such thing as a model that
somebody's Ollama probably serves.

So instead: every successful live listing is remembered, per user, per provider.
When a later listing cannot happen - no key pasted yet, offline, a key without
the scope to list - the remembered set answers, labelled with when it was seen.
Nothing here is ever authored; it is only ever a recording of what an endpoint
said about itself.

Consequences worth knowing:

- **A brand-new account with no key has nothing to suggest**, and the panel says
  so rather than guessing. That is the honest state, and the Model field is free
  text regardless, so it costs nobody the ability to configure.
- **Custom endpoints now get suggestions**, which the hand-maintained version
  could not do. Fetch once against your Ollama and it is remembered like any
  other provider.
- **These are suggestions, never an allowlist.** Nothing in Curio rejects a model
  because it is missing from here. A live listing always wins, and a model typed
  by hand is always accepted.

Per-user, deliberately: what a listing returns depends on the entitlements of the
key that asked, so one account's result is not a fact about another's. Same
storage convention as ``packages/libraries.py``.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from utk_curio.backend.app.common.user_storage import (
    user_key_segment as _user_key_segment,
    users_base as _users_base,
)

log = logging.getLogger(__name__)

_FILENAME = "model-suggestions.json"
_SCHEMA_VERSION = 1

#: Guard against a pathological endpoint (a proxy fronting thousands of models)
#: turning the suggestion store into something worth paging.
_MAX_REMEMBERED = 200


def provider_key(api_type: str, base_url: str = "") -> str:
    """Stable identity for "the endpoint these models came from".

    A base URL is part of the identity, not decoration: ``openai_compatible``
    covers real OpenAI *and* every self-hosted server, and their listings have
    nothing to do with each other.
    """
    kind = (api_type or "").strip() or "openai_compatible"
    url = (base_url or "").strip().rstrip("/")
    return f"{kind}@{url}" if url else kind


def _path(user_key: str) -> Path:
    return _users_base() / _user_key_segment(user_key) / _FILENAME


def _load(user_key: str) -> dict:
    p = _path(user_key)
    if not p.is_file():
        return {}
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        # Same convention as the rest of the per-user stores: a corrupt file is
        # an empty one. Suggestions are a nicety; nothing may fail to load
        # because of them.
        log.warning("Corrupt %s for %s - treating as empty", _FILENAME, user_key)
        return {}
    providers = raw.get("providers") if isinstance(raw, dict) else None
    return providers if isinstance(providers, dict) else {}


def remember_models(
    user_key: str, api_type: str, base_url: str, models: list[str]
) -> None:
    """Record a successful live listing. Best-effort: never raises.

    Called on the success path of a user-facing fetch, so a store that cannot be
    written must not turn a working listing into an error.
    """
    clean = [m for m in dict.fromkeys(models) if isinstance(m, str) and m.strip()]
    if not clean:
        return
    try:
        providers = _load(user_key)
        providers[provider_key(api_type, base_url)] = {
            "models": clean[:_MAX_REMEMBERED],
            "seenAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        p = _path(user_key)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_text(
            json.dumps(
                {"version": _SCHEMA_VERSION, "providers": providers}, indent=2
            ),
            encoding="utf-8",
        )
        os.replace(tmp, p)
    except OSError as exc:
        log.warning("Could not record model suggestions for %s: %s", user_key, exc)


def remembered_models(
    user_key: str, api_type: str, base_url: str = ""
) -> tuple[list[str], str | None]:
    """``(models, seen_at_iso)`` for this endpoint, or ``([], None)``.

    The timestamp is returned so the panel can say *when* the list was true
    rather than presenting a recording as the present tense.
    """
    entry = _load(user_key).get(provider_key(api_type, base_url))
    if not isinstance(entry, dict):
        return [], None
    models = [
        m for m in (entry.get("models") or []) if isinstance(m, str) and m.strip()
    ]
    seen_at = entry.get("seenAt")
    return models, seen_at if isinstance(seen_at, str) else None


#: Per model, what a chat endpoint was found to do beyond text.
_CHAT_CAPABILITIES_FILENAME = "chat-capabilities.json"


def _sidecar_path(user_key: str, filename: str) -> Path:
    return _users_base() / _user_key_segment(user_key) / filename


def _load_sidecar(user_key: str, filename: str, section: str) -> dict:
    try:
        raw = json.loads(_sidecar_path(user_key, filename).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError):
        log.warning("Corrupt %s for %s - treating as empty", filename, user_key)
        return {}
    entries = raw.get(section)
    return entries if isinstance(entries, dict) else {}


def _write_sidecar(user_key: str, filename: str, section: str, entries: dict) -> None:
    try:
        p = _sidecar_path(user_key, filename)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_text(
            json.dumps({"version": _SCHEMA_VERSION, section: entries}, indent=2),
            encoding="utf-8",
        )
        os.replace(tmp, p)
    except OSError as exc:
        log.warning("Could not record %s for %s: %s", filename, user_key, exc)


def _chat_key(api_type: str, base_url: str, model: str) -> str:
    return f"{provider_key(api_type, base_url)}#{(model or '').strip()}"


def remember_chat_capabilities(
    user_key: str, api_type: str, base_url: str, model: str, capabilities: dict
) -> None:
    """Record what a trial found this endpoint's model can do beyond text
    (``chat_capabilities``). Never raises."""
    if not isinstance(capabilities, dict):
        return
    entries = _load_sidecar(user_key, _CHAT_CAPABILITIES_FILENAME, "endpoints")
    entries[_chat_key(api_type, base_url, model)] = {
        "tools": bool(capabilities.get("tools")),
        "structuredOutput": bool(capabilities.get("structuredOutput")),
        "reason": str(capabilities.get("reason") or ""),
        "seenAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    _write_sidecar(user_key, _CHAT_CAPABILITIES_FILENAME, "endpoints", entries)


def remembered_chat_capabilities(
    user_key: str, api_type: str, base_url: str, model: str
) -> dict | None:
    """``{tools, structuredOutput, reason, seenAt}`` for this endpoint and
    model, or None when it was never asked."""
    entry = _load_sidecar(user_key, _CHAT_CAPABILITIES_FILENAME, "endpoints").get(
        _chat_key(api_type, base_url, model)
    )
    return dict(entry) if isinstance(entry, dict) else None
