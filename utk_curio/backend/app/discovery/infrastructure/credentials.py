"""Per-user portal tokens, stored the way every other Curio credential is.

Same shape as ``User.huggingface_token``: a column on the user's own row,
written through ``PATCH /api/auth/me``, edited in the account settings modal,
and reported to any client as a boolean and never as a value. A portal token is
a per-person entitlement - a Socrata app token is issued to an individual and
raises *their* rate limit - so it belongs to the account, not the deployment.

**Slots are a server-owned allowlist, not free text.** A manifest names the
credential it wants (``auth.secretId``), but which credentials can exist is
decided here, by :data:`SLOT_COLUMNS`. That is the same posture
``agents/tools.py::REGISTRY`` takes with tool contracts, and it matters for the
same reason: a manifest is operator-authored configuration, and letting it
invent a credential slot would let it invent somewhere for a secret to go.

Adding a slot is a column plus a migration plus one line here - deliberately
the same cost as adding any other account credential, because that is what it
is. A slot may also name a column that already holds the account's token for
another feature, as ``huggingface.token`` does.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Iterable

from utk_curio.backend.app.discovery.domain.manifest import DiscoverySourceManifest


@dataclass(frozen=True)
class KeySlot:
    """One per-account key a source can send, and how API Settings shows it."""

    #: The ``User`` column that holds it, which is also the field
    #: ``PATCH /api/auth/me`` takes it under.
    column: str
    label: str
    help_url: str | None = None
    placeholder: str | None = None
    #: A sentence API Settings shows under the field.
    note: str | None = None
    #: The deployment-wide fallback, read at call time so a test can set one.
    #: A user's own key always wins; this is what everyone else inherits,
    #: exactly as ``DEFAULT_LLM_API_KEY`` works.
    default_env: str | None = None
    #: Other parts of Curio that read the same column, named for a person.
    also_used_by: tuple[str, ...] = ()


#: manifest ``auth.secretId`` -> the slot. API Settings draws one row per
#: entry, so a key a new source needs is a line here, a column and a migration.
SLOTS: dict[str, KeySlot] = {
    "socrata.app-token": KeySlot(
        column="socrata_app_token",
        label="Socrata app token",
        help_url="https://evergreen.data.socrata.com/signup",
        placeholder="Your app token",
        note="Socrata portals answer without one; a token raises the rate limit.",
        default_env="CURIO_DEFAULT_SOCRATA_APP_TOKEN",
    ),
    # The same column Street Vision reads for gated models: one Hugging Face
    # token per account, whichever part of Curio asks for it.
    "huggingface.token": KeySlot(
        column="huggingface_token",
        label="Hugging Face token",
        help_url="https://huggingface.co/settings/tokens",
        placeholder="hf_...",
        also_used_by=("Street Vision's gated models",),
    ),
}

#: manifest ``auth.secretId`` -> the ``User`` column that holds it.
SLOT_COLUMNS: dict[str, str] = {slot: spec.column for slot, spec in SLOTS.items()}

#: manifest ``auth.secretId`` -> the deployment-wide fallback's variable.
SLOT_DEFAULTS: dict[str, str] = {
    slot: spec.default_env for slot, spec in SLOTS.items() if spec.default_env
}

#: What a client is told about each slot, keyed the same way. Booleans only.
SLOT_FLAGS: dict[str, str] = {
    slot: f"has_{column}" for slot, column in SLOT_COLUMNS.items()
}


def known_slot(secret_id: str | None) -> bool:
    return bool(secret_id) and secret_id in SLOT_COLUMNS


def own_token(user, secret_id: str | None) -> str | None:
    """Only what this account saved. Never the deployment's."""
    column = SLOT_COLUMNS.get(secret_id or "")
    if column is None or user is None:
        return None
    return getattr(user, column, None) or None


def token_for_slot(user, secret_id: str | None) -> str | None:
    """The token that will actually be sent: the user's own, else the
    deployment's.

    Per-field inheritance: a user who sets nothing inherits what the operator configured, and setting their
    own overrides it. An operator running Curio for a class can raise the rate
    limit for everyone with one environment variable.
    """
    if secret_id not in SLOT_COLUMNS:
        return None
    own = own_token(user, secret_id)
    if own:
        return own
    env = SLOT_DEFAULTS.get(secret_id)
    # Read at call time rather than import: a deployment may set it after the
    # module loads, and tests certainly do.
    return (os.environ.get(env) or None) if env else None


def has_token(user, secret_id: str | None) -> bool:
    """Whether a token will be SENT - which is what a card reporting "Token
    set" means, and what decides whether a required-token source is usable.

    Distinct from ``has_socrata_app_token`` on the user payload, which answers
    the different question the settings screen asks: did *you* save one.
    """
    return token_for_slot(user, secret_id) is not None


def credential_header(user, manifest: DiscoverySourceManifest) -> str | None:
    """``"<Header-Name>:<token>"`` for *manifest*, or None.

    The transport is the only caller, and the only code that turns this into a
    request header. Providers are handed the header NAME and the slot; they
    never see what is in it.

    Header-only by construction: ``auth.scheme`` accepts nothing else, which is
    what keeps a secret out of every URL, audit record and error message.
    """
    auth = manifest.auth
    if not auth.uses_token or not auth.header_name:
        return None
    token = token_for_slot(user, auth.secret_id)
    if not token:
        return None
    return f"{auth.header_name}:{auth.value_prefix or ''}{token}"


def key_rows(user, manifests: Iterable[DiscoverySourceManifest]) -> list[dict[str, Any]]:
    """What API Settings lists: every slot, who sends it, and booleans only.

    ``present`` says whether THIS account saved one; ``inherited`` whether the
    deployment supplies one everybody gets. Neither carries a value.
    """
    manifests = list(manifests)
    rows = []
    for slot, spec in SLOTS.items():
        sources = sorted(
            ({"name": m.name, "dirName": m.dir_name} for m in manifests if m.auth.secret_id == slot),
            key=lambda row: row["name"].lower(),
        )
        rows.append({
            "slot": slot,
            "label": spec.label,
            "field": spec.column,
            "helpUrl": spec.help_url,
            "placeholder": spec.placeholder,
            "note": spec.note,
            "present": own_token(user, slot) is not None,
            "inherited": bool(spec.default_env and os.environ.get(spec.default_env)),
            "sources": sources,
            "alsoUsedBy": list(spec.also_used_by),
        })
    return rows
