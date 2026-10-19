"""The keys the Discovery Catalog sends to its sources, and where they go.

A source manifest declares the key it sends in its ``auth`` block: the secret
id it names the key by, and how API Settings shows it (``label``, ``helpUrl``,
``placeholder``, ``note``). Sources that send one key name the same id, and
API Settings lists one row per id, so a key a new source needs is its
manifest and nothing else. A key is a per-person entitlement - a Socrata app
token is issued to an individual and raises *their* rate limit - so an
account's keys live in its own owner-only file (``users/source_keys.py``),
keyed by that id, and are reported to any client as booleans, never as values.

A key goes only to a source whose manifest names its id, and only to that
source's own origin (``CredentialedTransport``). A source whose manifest sets
``auth.operatorDefault`` also takes the operator's key, from the variable
:func:`default_variable` derives from the id, when the account saved none.
That variable is never one of Curio's own settings
(``manifest.is_own_setting``): a manifest whose id would read one fails to
load, and :func:`deployment_key` refuses one again here.
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Any, Iterable

from utk_curio.backend.app.discovery.domain.manifest import (
    AuthSpec,
    DiscoverySourceManifest,
    default_variable,
    is_own_setting,
)
from utk_curio.backend.app.users import source_keys

logger = logging.getLogger(__name__)

__all__ = [
    "credential_header", "declared_keys", "default_variable", "deployment_key",
    "has_key", "key_for", "key_rows", "own_key",
]


def own_key(user, secret_id: str | None) -> str | None:
    """Only what this account saved. Never the deployment's.

    Never a guest's under ``--deploy`` either: every visitor is that one
    account, and a key it holds was saved by the one local user before the
    same ``.curio`` was started with ``--deploy`` (a hosted guest cannot save
    one). It stays in the file and is used again without ``--deploy``.
    """
    if not secret_id or user is None:
        return None
    return source_keys.value_for(user, secret_id)


def deployment_key(auth: AuthSpec) -> str | None:
    """The operator's key for a source whose manifest allows one. Never one of
    Curio's own settings, which share the variables' prefix.

    Read at call time rather than import: a deployment may set it after the
    module loads, and tests certainly do.
    """
    if not auth.secret_id or not auth.operator_default:
        return None
    variable = default_variable(auth.secret_id)
    if is_own_setting(variable):
        return None
    return os.environ.get(variable) or None


def key_for(user, auth: AuthSpec) -> str | None:
    """The key that will actually be sent: the account's own, else the
    deployment's.

    Per-field inheritance: a user who sets nothing inherits what the operator
    configured, and setting their own overrides it. An operator running Curio
    for a class can raise the rate limit for everyone with one environment
    variable.
    """
    return own_key(user, auth.secret_id) or deployment_key(auth)


def has_key(user, auth: AuthSpec) -> bool:
    """Whether a key will be SENT - which is what a card reporting "Token
    set" means, and what decides whether a required-token source is usable.

    Distinct from ``has_source_keys`` on the user payload, which answers the
    different question the settings screen asks: did *you* save one.
    """
    return key_for(user, auth) is not None


def credential_header(user, manifest: DiscoverySourceManifest) -> str | None:
    """``"<Header-Name>:<token>"`` for *manifest*, ``"?<param>=<token>"`` for a
    ``query`` key, or None.

    The transport is the only caller, and the only code that turns this into a
    request header or a query parameter. Providers are handed the name and the
    secret id; they never see the key, so no URL a provider builds, and no
    audit record, refusal or job record made from one, holds a key.
    """
    auth = manifest.auth
    if not auth.uses_token:
        return None
    if auth.scheme == "query":
        if not auth.param_name:
            return None
        token = key_for(user, auth)
        # ``?name=value``: the transport adds it to the URL it sends and to
        # nothing it returns or records.
        return f"?{auth.param_name}={token}" if token else None
    if not auth.header_name:
        return None
    token = key_for(user, auth)
    if not token:
        return None
    return f"{auth.header_name}:{auth.value_prefix or ''}{token}"


def _declaration(auth: AuthSpec) -> tuple:
    return (auth.label, auth.help_url, auth.placeholder, auth.note, auth.operator_default)


#: Disagreements already logged, by secret id and source folder, so a listing
#: that runs on every request says so once.
_reported: set[tuple[str, str]] = set()
_reported_lock = threading.Lock()


def _by_secret_id(manifests: Iterable[DiscoverySourceManifest]) -> dict[str, list[DiscoverySourceManifest]]:
    """The sources that send each key, in listing order (shipped sources
    first). The first one's declaration is the key's; a source that declares
    it otherwise is logged once."""
    groups: dict[str, list[DiscoverySourceManifest]] = {}
    for manifest in manifests:
        if manifest.auth.secret_id:
            groups.setdefault(manifest.auth.secret_id, []).append(manifest)
    for secret_id, group in groups.items():
        first = group[0]
        for other in group[1:]:
            if _declaration(other.auth) == _declaration(first.auth):
                continue
            key = (secret_id, other.dir_name)
            with _reported_lock:
                if key in _reported:
                    continue
                _reported.add(key)
            logger.warning(
                "Discovery Catalog source %s declares the key %s otherwise than %s; "
                "API Settings shows %s's declaration",
                other.dir_name, secret_id, first.dir_name, first.dir_name,
            )
    return groups


def declared_keys(manifests: Iterable[DiscoverySourceManifest]) -> dict[str, str]:
    """Every key a source sends, by secret id, with what API Settings calls it."""
    return {
        secret_id: group[0].auth.label or secret_id
        for secret_id, group in _by_secret_id(manifests).items()
    }


def key_rows(user, manifests: Iterable[DiscoverySourceManifest]) -> list[dict[str, Any]]:
    """What API Settings lists: one row per key a source declares, the
    sources that send it, and booleans only, in the order of their labels.

    ``present`` says whether THIS account saved one; ``inherited`` whether the
    deployment supplies one everybody gets. Neither carries a value.
    """
    saved = set(source_keys.saved_for(user))
    rows = []
    for secret_id, group in _by_secret_id(manifests).items():
        auth = group[0].auth
        rows.append({
            "slot": secret_id,
            "label": auth.label or secret_id,
            "helpUrl": auth.help_url,
            "placeholder": auth.placeholder,
            "note": auth.note,
            "present": secret_id in saved,
            "inherited": any(deployment_key(m.auth) for m in group),
            "sources": sorted(
                ({"name": m.name, "dirName": m.dir_name} for m in group),
                key=lambda row: row["name"].lower(),
            ),
        })
    rows.sort(key=lambda row: (row["label"].lower(), row["slot"]))
    return rows
