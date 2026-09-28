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

from utk_curio.backend.app.packages.storage import (
    _user_key_segment,
    _users_base,
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


# ---------------------------------------------------------------------------
# Fine-tuning capability, and models Curio caused to exist (memo dev/122)
# ---------------------------------------------------------------------------
#
# Two additions, in two files, for one reason each.
#
# The capability probe is recorded here because it is the same KIND of fact as
# a model listing — something an endpoint said about itself — and it earns the
# same treatment: recorded on every successful ask, replayed with the date it
# was true when a fresh ask is impossible, and never presented as the present
# tense.
#
# A TRAINED model is a different kind of fact: not a recording of what an
# endpoint reported, but a model this install caused to exist. It therefore
# lives in a sibling file rather than inside the suggestions this module's
# docstring promises are "only ever a recording of what an endpoint said about
# itself". Mixing them would blur the doctrine that makes the replay
# trustworthy.

_CAPABILITY_FILENAME = "fine-tuning-capability.json"
_TRAINED_FILENAME = "trained-models.json"

#: A recording older than this is still shown, still labelled with its date —
#: this only decides when the panel offers to re-ask.
CAPABILITY_STALE_AFTER_HOURS = 24


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


def remember_capability(
    user_key: str, api_type: str, base_url: str, capability: dict
) -> None:
    """Record what an endpoint said about fine-tuning. Never raises."""
    if not isinstance(capability, dict):
        return
    entries = _load_sidecar(user_key, _CAPABILITY_FILENAME, "providers")
    entries[provider_key(api_type, base_url)] = {
        "supported": bool(capability.get("supported")),
        "reason": str(capability.get("reason") or ""),
        "baseModels": [
            str(m) for m in (capability.get("baseModels") or []) if str(m).strip()
        ][:_MAX_REMEMBERED],
        "surface": str(capability.get("surface") or ""),
        "seenAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    _write_sidecar(user_key, _CAPABILITY_FILENAME, "providers", entries)


def remembered_capability(
    user_key: str, api_type: str, base_url: str = ""
) -> tuple[dict | None, str | None]:
    """``(capability, seen_at_iso)`` for this endpoint, or ``(None, None)``."""
    entry = _load_sidecar(user_key, _CAPABILITY_FILENAME, "providers").get(
        provider_key(api_type, base_url)
    )
    if not isinstance(entry, dict):
        return None, None
    seen_at = entry.get("seenAt")
    return (
        {
            "supported": bool(entry.get("supported")),
            "reason": str(entry.get("reason") or ""),
            "baseModels": list(entry.get("baseModels") or []),
            "surface": str(entry.get("surface") or ""),
        },
        seen_at if isinstance(seen_at, str) else None,
    )


def remember_trained_model(
    user_key: str,
    api_type: str,
    base_url: str,
    *,
    model: str,
    job_id: str,
    dataset_sha256: str,
    base_model: str = "",
) -> None:
    """Record a model this install trained. Never raises.

    Labelled with its provenance and its date for the same reason a replayed
    listing is: an id shown without what produced it and when is a recording
    presented as the present tense.
    """
    if not (model or "").strip():
        return
    entries = _load_sidecar(user_key, _TRAINED_FILENAME, "providers")
    key = provider_key(api_type, base_url)
    rows = [
        row for row in (entries.get(key) or [])
        if isinstance(row, dict) and row.get("model") != model
    ]
    rows.append({
        "model": str(model),
        "origin": "trained-in-curio",
        "jobId": str(job_id),
        "baseModel": str(base_model or ""),
        "datasetSha256": str(dataset_sha256 or ""),
        "trainedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    })
    entries[key] = rows[-_MAX_REMEMBERED:]
    _write_sidecar(user_key, _TRAINED_FILENAME, "providers", entries)


def trained_models(user_key: str, api_type: str, base_url: str = "") -> list:
    """Every model this install trained against this endpoint, newest last.

    A suggestion like any other: nothing rejects a model for being absent from
    here, and the Model field stays free text.
    """
    rows = _load_sidecar(user_key, _TRAINED_FILENAME, "providers").get(
        provider_key(api_type, base_url)
    )
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict) and row.get("model")]
