"""Curated model ids, the half of model discovery that does not need a network.

#241 asked whether Curio should discover models by querying the provider, ship
a fixed list, or do both. This module is the "both": a short, per-provider list
used when a live listing cannot happen or cannot answer.

**It is a fallback, not an allowlist.** Nothing here restricts what a user may
save. The Model field stays free text, a saved model that no longer appears
keeps working, and a live listing always wins over these entries. The lists
exist so that a user who has not pasted a key yet, is offline, or is on a
provider whose key lacks the scope to list still has something to pick from
instead of an error message and an empty box.

Kept deliberately short for the same reason: a long list would go stale faster
than anyone would notice, and the live path is what should be answering on a
configured account.

``custom`` has no list by construction. It means "some OpenAI-compatible
endpoint", and there is no such thing as a model that endpoint probably serves.
"""

from __future__ import annotations

#: Per ``api_type`` plus the UI's ``openai`` split of ``openai_compatible``.
#: Ordered most-likely-first rather than alphabetically: this is a suggestion
#: list, and the first entry is the one most users want.
CURATED_MODELS: dict[str, tuple[str, ...]] = {
    "openai": (
        "gpt-4o-mini",
        "gpt-4o",
    ),
    # Canonical ids, without a date suffix: Anthropic's current ids are complete
    # as written and a constructed ``-YYYYMMDD`` variant is not guaranteed to
    # resolve. The AI Settings placeholder still names the dated Haiku build
    # this deployment was set up with, which the live listing supersedes anyway.
    "anthropic": (
        "claude-sonnet-5",
        "claude-opus-5",
        "claude-haiku-4-5",
    ),
    "gemini": (
        "gemini-2.0-flash",
    ),
}


def curated_for(api_type: str, base_url: str = "") -> list[str]:
    """The curated ids for a provider, or ``[]`` when there are none.

    ``openai_compatible`` covers both real OpenAI and every self-hosted or
    third-party endpoint, and they are told apart the same way the AI Settings
    panel tells them apart: a base URL means "somewhere else", and somewhere
    else has no models we can guess at.
    """
    kind = (api_type or "").strip()
    if kind in ("openai_compatible", "openai", ""):
        return [] if (base_url or "").strip() else list(CURATED_MODELS["openai"])
    return list(CURATED_MODELS.get(kind, ()))
