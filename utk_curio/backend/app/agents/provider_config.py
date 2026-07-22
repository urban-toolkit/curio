"""Provider-config resolution, owned by the ``agents/`` boundary.

The v1 step of ``ADR-AG-012`` (memo ``dev/22``): the *resolution* of a caller's
LLM provider — guest env config, per-user ``user.llm_*`` fields, and the aiconn
sage200 default seed (``DEC-039``, via ``config.DEFAULT_LLM_*``) — moves here
from ``app/api/routes.py``. Storage is unchanged; the ``ProviderProfile`` model
and encrypted secret store remain the flagged v2 remainder. Legacy ``/llm/*``
routes consume this resolver through a thin tuple shim (the bridge direction
``ADR-AG-012`` prescribes), so ``app/agents`` no longer imports from
``app/api``.
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
    """Resolve the caller's provider config (behavior-preserving move of the
    former ``app/api/routes.py::_resolve_llm_config``).

    A user who has configured their own provider keeps that exact config. An
    unconfigured user falls back to the default provider — seeded from the
    aiconn sage200 OpenAI-compatible endpoint via ``config.DEFAULT_LLM_*`` —
    rather than being turned away. Guests use the guest config and are refused
    when no guest key is deployed.
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
    if not user.llm_model:
        # Unconfigured → the default provider (aiconn), not an error.
        return ProviderConfig(
            api_key=DEFAULT_LLM_API_KEY,
            api_type=DEFAULT_LLM_API_TYPE,
            base_url=DEFAULT_LLM_BASE_URL,
            model=DEFAULT_LLM_MODEL,
        )
    return ProviderConfig(
        api_key=user.llm_api_key or "",
        api_type=user.llm_api_type or "openai_compatible",
        base_url=user.llm_base_url or "",
        model=user.llm_model,
    )
