"""Startup warnings for settings that changed meaning between releases.

Each entry here is a variable or folder an operator plausibly still has, whose effect
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

    # The Street Vision token is an account setting only. An operator upgrading
    # with either deployment-wide variable exported sees gated model downloads
    # start failing with a 401 and nothing pointing at the change.
    for name in ("HUGGINGFACE_TOKEN", "CURIO_DEFAULT_HUGGINGFACE_TOKEN"):
        if _warn_legacy_env(
            name,
            "Each user saves their own HuggingFace token in API Settings.",
        ):
            warned.append(name)

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

    # The Data Lake Catalog became the Discovery Catalog. Its root setting and
    # its folder for an operator's own sources are not read, and nothing moves
    # them, so a source left there leaves the catalog without a word.
    rename = "and rename lake. to source. in each source's folder name and manifest id."
    if _warn_legacy_env("CURIO_DATALAKE_ROOT", f"Pass --discovery-root to curio.py start instead, {rename}"):
        warned.append("CURIO_DATALAKE_ROOT")
    from utk_curio.backend.app.common.user_storage import curio_root

    try:
        old_sources = curio_root() / "datalakes"
        if old_sources.is_dir():
            log.warning("%s is no longer read. Move its sources to %s, %s",
                        old_sources, curio_root() / "discovery", rename)
            warned.append(".curio/datalakes")
    except OSError:  # a notice never stops a boot
        pass

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
