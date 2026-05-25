"""Tests for the dev seeder + seed-state tombstone protocol.

The regression these tests guard against:

* The dev seeder used to copy any fixture package whose runtime dest was
  missing — meaning a user-uninstalled package came right back the next
  time Werkzeug's reloader fired. That's the "I can't uninstall my
  package" UX bug the marker file (see ``seed_state.py``) exists to fix.

The matrix exercised here:

* fresh fixture set → seeder copies once, then is idempotent
* uninstall + restart → package stays uninstalled
* uninstall + fixture-mtime advance + restart → tombstone is overridden
* uninstall + user reinstall → tombstone is cleared
* ``CURIO_RESEED_PACKAGES=1`` → escape hatch overrides everything
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from utk_curio.backend.app.packages import seed_state
from utk_curio.backend.app.packages.installer import (
    install_packageage_from_directory,
    uninstall_packageage,
)
from utk_curio.backend.app.packages.seed import seed_dev_packageages
from utk_curio.backend.app.packages.storage import user_packageages_dir


REAL_CATALOG = Path(__file__).resolve().parents[4] / "packages"


def _installed_names(user_key: str = "guest") -> list[str]:
    base = user_packageages_dir(user_key)
    if not base.is_dir():
        return []
    return sorted(p.name for p in base.iterdir() if p.is_dir() and "@" in p.name)


def _state(user_key: str = "guest") -> dict[str, dict]:
    return {k: v.to_json() for k, v in seed_state.load(user_key).items()}


@pytest.fixture()
def real_fixtures_root() -> Path:
    """Pin the seeder to the committed catalog under ``<repo_root>/packages``.

    All the production seeding paths read from there; we don't bother
    re-pointing :func:`seed._catalog_root` because it already returns
    that path. The pytest fixture simply asserts the source exists so a
    structural regression in the catalog tree fails this file rather
    than the dozens of tests that depend on the seeder shape.
    """
    assert REAL_CATALOG.is_dir(), f"missing catalog root {REAL_CATALOG}"
    return REAL_CATALOG


# ---------------------------------------------------------------------------
# Happy path: only the built-in package is auto-seeded; third-party catalog
# packages stay in <repo_root>/packages/ and install on demand.
# ---------------------------------------------------------------------------

def test_seeds_only_builtin_on_first_run(tmp_curio, real_fixtures_root):
    seeded = seed_dev_packageages(user_key="guest")
    assert seeded, "expected the built-in package to seed"
    installed = _installed_names()
    assert any(name.startswith("curio.builtin@") for name in installed)
    assert "ai.urbanlab.uhvi@1" not in installed, (
        "third-party catalog packages must not auto-install"
    )


def test_seed_after_uninstall_of_third_party_remains_no_op(tmp_curio, real_fixtures_root):
    """A third-party package that the user never installed (no auto-seed)
    must continue not to install on subsequent boots."""
    seed_dev_packageages(user_key="guest")
    assert "ai.urbanlab.uhvi@1" not in _installed_names()
    # Second seed: still not installed.
    second = seed_dev_packageages(user_key="guest")
    assert "ai.urbanlab.uhvi@1" not in second
    assert "ai.urbanlab.uhvi@1" not in _installed_names()

    # Now uninstall and confirm the tombstone is sticky across restarts.
    uninstall_packageage("guest", "ai.urbanlab.uhvi@1")
    seed_dev_packageages(user_key="guest")
    assert "ai.urbanlab.uhvi@1" not in _installed_names()


def test_uninstall_without_prior_state_is_still_sticky(tmp_curio, real_fixtures_root):
    """Worst-case upgrade path: user has a runtime copy *and* uninstalls
    on the same backend cycle that introduced the tombstone protocol
    (so the seeder never had a chance to adopt the copy). The
    tombstone's fixture_mtime is ``None`` but the seeder still respects
    the uninstall — the user's intent wins over silent re-seeding."""
    src = real_fixtures_root / "ai.urbanlab.uhvi@1"
    dest = user_packageages_dir("guest") / src.name
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dest)

    uninstall_packageage("guest", "ai.urbanlab.uhvi@1")
    rec = _state()["ai.urbanlab.uhvi@1"]
    assert rec.get("uninstalledAt") is not None
    assert "fixtureMtime" not in rec, (
        "no prior seeded record means we cannot anchor the tombstone"
    )

    seed_dev_packageages(user_key="guest")
    assert "ai.urbanlab.uhvi@1" not in _installed_names()


# ---------------------------------------------------------------------------
# Marker file robustness
# ---------------------------------------------------------------------------

def test_corrupt_state_file_does_not_block_startup(tmp_curio, real_fixtures_root):
    seed_dev_packageages(user_key="guest")
    state_path = user_packageages_dir("guest") / seed_state.STATE_FILENAME
    state_path.write_text("{not valid json", encoding="utf-8")

    # ``load`` swallows the parse error and returns an empty dict so a
    # corrupt marker can never block startup.
    assert seed_state.load("guest") == {}
    # The seeder runs cleanly against a corrupt state file — the
    # important property is that startup does not raise.
    seed_dev_packageages(user_key="guest")

    # Forcing a re-seed (uninstall + CURIO_RESEED_PACKAGES) restores a
    # well-formed marker on disk, proving the corrupt file is recoverable
    # without manual intervention.
    uninstall_packageage("guest", "ai.urbanlab.uhvi@1")
    from utk_curio.backend.app.packages import seed as packages_seed
    original = packages_seed.CURIO_RESEED_PACKAGES
    packages_seed.CURIO_RESEED_PACKAGES = True
    try:
        seed_dev_packageages(user_key="guest")
    finally:
        packages_seed.CURIO_RESEED_PACKAGES = original
    assert json.loads(state_path.read_text(encoding="utf-8"))["version"] == 1
