"""Provider-config resolution, owned by the ``agents/`` boundary.

The v1 step of ``ADR-AG-012`` (memo ``dev/22``): the *resolution* of a caller's
LLM provider — guest env config, per-user ``user.llm_*`` fields, and the
deployment default (via ``config.DEFAULT_LLM_*``) — moves here from
``app/api/routes.py``. Storage is unchanged; the ``ProviderProfile`` model and
encrypted secret store remain the flagged v2 remainder.

**Resolution is per field.** Each field the user left blank inherits the
deployment default. It used to switch wholesale on ``user.llm_model``: setting a
model discarded the deployment's API key, base URL and provider type in one go,
so a user who filled in only the model box started sending unauthenticated
requests to nothing in particular. Both the AI Settings copy ("Leave a field
blank to use it") and the Agent Catalog guide promised per-field inheritance the
code did not implement, and the failure was silent.

The one qualification: API key, base URL and model are inherited only while the
user is on the same provider the deployment configured. They describe a specific
endpoint, and lending an Anthropic user the deployment's OpenAI-compatible key
and URL would be a different kind of wrong.
"""

from __future__ import annotations

from utk_curio.backend.config import (
    DEFAULT_LLM_API_KEY,
    DEFAULT_LLM_API_TYPE,
    DEFAULT_LLM_BASE_URL,
    DEFAULT_LLM_MODEL,
    GUEST_LLM_API_KEY,
    GUEST_LLM_API_TYPE,
    GUEST_LLM_BASE_URL,
    GUEST_LLM_MODEL,
)
from utk_curio.backend.app.agents.providers import ProviderConfig


class ProviderConfigError(ValueError):
    """No provider is available for this caller (surfaced as a 400)."""


def resolve_provider_config(user) -> ProviderConfig:
    """Resolve the caller's provider config, field by field.

    Each field the user set wins; each field they left blank inherits the
    deployment default. Guests use the guest config and are refused when no
    guest key is deployed.

    A model is the one field with no usable fallback: Curio ships no built-in
    endpoint (see ``config.DEFAULT_LLM_*``), so when neither the user nor the
    operator named one, refuse here and let the caller point the user at AI
    Settings rather than dispatching a half-formed config into a provider SDK.
    """
    if user.is_guest:
        if not GUEST_LLM_API_KEY:
            raise ProviderConfigError("LLM is not available for guest users at this time.")
        return ProviderConfig(
            api_key=GUEST_LLM_API_KEY,
            api_type=GUEST_LLM_API_TYPE,
            base_url=GUEST_LLM_BASE_URL,
            model=GUEST_LLM_MODEL,
        )

    api_type = (user.llm_api_type or "").strip() or DEFAULT_LLM_API_TYPE
    api_key = (user.llm_api_key or "").strip()
    base_url = (user.llm_base_url or "").strip()
    model = (user.llm_model or "").strip()

    # Credentials and endpoint belong to a *provider*, so they are inherited
    # only when the user is on the same provider the deployment configured.
    # Handing an Anthropic user the deployment's OpenAI-compatible base URL and
    # key would be worse than handing them nothing.
    same_provider = api_type == DEFAULT_LLM_API_TYPE
    if same_provider:
        api_key = api_key or DEFAULT_LLM_API_KEY
        base_url = base_url or DEFAULT_LLM_BASE_URL
        model = model or DEFAULT_LLM_MODEL

    if not model:
        raise ProviderConfigError(
            "No AI provider is configured. Set one up in AI Settings, or ask "
            "your Curio operator to configure a default provider."
        )
    return ProviderConfig(
        api_key=api_key, api_type=api_type, base_url=base_url, model=model
    )
