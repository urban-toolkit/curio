"""Startup warnings for settings that changed meaning between releases.

Each entry here is a variable an operator plausibly still has set, whose effect
this release removed or moved. None of them break a boot, which is the problem:
without a warning the deployment starts cleanly and a feature quietly stops
working, or starts costing money it did not before.

Keep this list short and delete entries once the release they cover is far
enough back that nobody is upgrading across it.
"""

from __future__ import annotations

import logging
import os

log = logging.getLogger(__name__)


def _warn_legacy_env(name: str, message: str) -> bool:
    if not os.environ.get(name):
        return False
    log.warning("%s is set but no longer read. %s", name, message)
    return True


def check_upgrade_notices() -> list[str]:
    """Log a warning per stale setting. Returns the names warned about."""
    warned: list[str] = []

    # The Street Vision token became an account setting with a deployment
    # fallback under a new name. An operator upgrading with the old variable
    # exported sees gated model downloads start failing with a 401 and nothing
    # pointing at the rename.
    if _warn_legacy_env(
        "HUGGINGFACE_TOKEN",
        "Set CURIO_DEFAULT_HUGGINGFACE_TOKEN for the deployment-wide fallback, "
        "or let each user save their own token in AI Settings, which wins over it.",
    ):
        warned.append("HUGGINGFACE_TOKEN")

    # The Street Vision caches moved under each user's directory, because the
    # overlay route is unauthenticated and a shared cache let anyone who could
    # guess an image id read another user's imagery. There is no migration: the
    # old tree cannot be partitioned between accounts after the fact.
    for name in ("STREETVISION_CACHE_DIR", "STREETVISION_MODEL_CACHE_DIR"):
        if _warn_legacy_env(
            name,
            "Street Vision caches are now per user under "
            ".curio/users/<user>/streetvision/ and this override is ignored. "
            "The previous cache is not migrated: panoramas will be re-fetched "
            "against your Google Maps quota and model weights re-downloaded per "
            "user. The old directory is safe to delete.",
        ):
            warned.append(name)

    # A deployment that set only a guest key used to inherit a built-in guest
    # model. Curio now ships no model name at all, so that deployment resolves
    # nothing and guests fail at run time rather than at boot.
    from utk_curio.backend.config import (
        GUEST_LLM_API_KEY,
        GUEST_LLM_MODEL,
    )

    if GUEST_LLM_API_KEY and not GUEST_LLM_MODEL:
        log.warning(
            "GUEST_LLM_API_KEY is set but no guest model resolves. Curio no "
            "longer ships a default model name, so guest AI will fail at run "
            "time. Set GUEST_LLM_MODEL, or --llm-model for the deployment "
            "default guests inherit."
        )
        warned.append("GUEST_LLM_MODEL")

    return warned
