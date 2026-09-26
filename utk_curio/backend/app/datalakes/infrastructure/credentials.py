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
is. Token-needing portal families are rare; there is one today.
"""

from __future__ import annotations

import os

from utk_curio.backend.app.datalakes.domain.manifest import LakeSourceManifest

#: manifest ``auth.secretId`` -> the ``User`` column that holds it.
SLOT_COLUMNS: dict[str, str] = {
    "socrata.app-token": "socrata_app_token",
}

#: manifest ``auth.secretId`` -> the deployment-wide fallback, read at call
#: time so a test can set one. A user's own token always wins; this is what
#: everyone else inherits, exactly as ``DEFAULT_LLM_API_KEY`` works.
SLOT_DEFAULTS: dict[str, str] = {
    "socrata.app-token": "CURIO_DEFAULT_SOCRATA_APP_TOKEN",
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

    Per-field inheritance, the same shape as the LLM provider config: a user
    who sets nothing inherits what the operator configured, and setting their
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


def credential_header(user, manifest: LakeSourceManifest) -> str | None:
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
    return f"{auth.header_name}:{token}"
