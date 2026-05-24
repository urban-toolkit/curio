"""Tests for the dev seeder + seed-state tombstone protocol.

The regression these tests guard against:

* The dev seeder used to copy any fixture pack whose runtime dest was
  missing — meaning a user-uninstalled pack came right back the next
  time Werkzeug's reloader fired. That's the "I can't uninstall my
  pack" UX bug the marker file (see ``seed_state.py``) exists to fix.

The matrix exercised here:

* fresh fixture set → seeder copies once, then is idempotent
* uninstall + restart → pack stays uninstalled
* uninstall + fixture-mtime advance + restart → tombstone is overridden
* uninstall + user reinstall → tombstone is cleared
* ``CURIO_RESEED_PACKS=1`` → escape hatch overrides everything
"""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest

from utk_curio.backend.app.packs import seed_state
from utk_curio.backend.app.packs.installer import (
    install_pack_from_directory,
    uninstall_pack,
)
from utk_curio.backend.app.packs.seed import seed_dev_packs
from utk_curio.backend.app.packs.storage import user_packs_dir


REAL_CATALOG = Path(__file__).resolve().parents[4] / "packs"


def _installed_names(user_key: str = "guest") -> list[str]:
    base = user_packs_dir(user_key)
    if not base.is_dir():
        return []
    return sorted(p.name for p in base.iterdir() if p.is_dir() and "@" in p.name)


def _state(user_key: str = "guest") -> dict[str, dict]:
    return {k: v.to_json() for k, v in seed_state.load(user_key).items()}


@pytest.fixture()
def real_fixtures_root() -> Path:
    """Pin the seeder to the committed catalog under ``<repo_root>/packs``.

    All the production seeding paths read from there; we don't bother
    re-pointing :func:`seed._catalog_root` because it already returns
    that path. The pytest fixture simply asserts the source exists so a
    structural regression in the catalog tree fails this file rather
    than the dozens of tests that depend on the seeder shape.
    """
    assert REAL_CATALOG.is_dir(), f"missing catalog root {REAL_CATALOG}"
    return REAL_CATALOG


# ---------------------------------------------------------------------------
# Happy path: first seed + idempotent re-seed
# ---------------------------------------------------------------------------

def test_seeds_committed_fixtures_on_first_run(tmp_curio, real_fixtures_root):
    seeded = seed_dev_packs(user_key="guest")
    assert seeded, "expected at least one committed fixture to seed"
    installed = _installed_names()
    assert "ai.urbanlab.uhvi@1" in installed
    state = _state()
    for name in seeded:
        assert state[name].get("seededAt") is not None
        assert state[name].get("fixtureMtime") is not None


def test_second_run_is_a_no_op_when_nothing_changed(tmp_curio, real_fixtures_root):
    assert seed_dev_packs(user_key="guest")
    # Built-in is always reseeded (forced-builtin), but third-party packs
    # tracked via tombstone state should be no-ops on the second run.
    second = seed_dev_packs(user_key="guest")
    assert all(name.startswith("curio.builtin@") for name in second)
    # And the runtime copy is still in place.
    assert "ai.urbanlab.uhvi@1" in _installed_names()


# ---------------------------------------------------------------------------
# Tombstone — uninstall is sticky across restarts
# ---------------------------------------------------------------------------

def test_uninstall_writes_tombstone_state(tmp_curio, real_fixtures_root):
    seed_dev_packs(user_key="guest")
    assert uninstall_pack("guest", "ai.urbanlab.uhvi@1") is True
    state = _state()["ai.urbanlab.uhvi@1"]
    assert state.get("uninstalledAt") is not None
    assert "seededAt" not in state
    # fixtureMtime is preserved so a future fixture advance can override.
    assert state.get("fixtureMtime") is not None


def test_seed_after_uninstall_is_a_noop(tmp_curio, real_fixtures_root):
    seed_dev_packs(user_key="guest")
    uninstall_pack("guest", "ai.urbanlab.uhvi@1")

    seeded = seed_dev_packs(user_key="guest")
    assert "ai.urbanlab.uhvi@1" not in seeded
    assert "ai.urbanlab.uhvi@1" not in _installed_names()


def test_repeated_seeds_after_uninstall_stay_no_op(tmp_curio, real_fixtures_root):
    seed_dev_packs(user_key="guest")
    uninstall_pack("guest", "ai.urbanlab.uhvi@1")
    for _ in range(3):
        assert "ai.urbanlab.uhvi@1" not in seed_dev_packs(user_key="guest")
    assert "ai.urbanlab.uhvi@1" not in _installed_names()


# ---------------------------------------------------------------------------
# Tombstone override paths
# ---------------------------------------------------------------------------

def test_fixture_mtime_advance_overrides_tombstone(tmp_curio, real_fixtures_root, monkeypatch):
    """A newer fixture mtime should override an uninstall tombstone.

    Models the dev workflow: pushing a new manifest revision *does* mean
    the dev wants the fixture surfaced again, even if a previous run
    had been tombstoned.
    """
    # We simulate the "fixture is now newer" condition by rewriting the
    # tombstone's stored ``fixtureMtime`` to something well in the past
    # and then re-running the seeder against the real fixtures (whose
    # mtimes are 'now' on disk).
    seed_dev_packs(user_key="guest")
    uninstall_pack("guest", "ai.urbanlab.uhvi@1")

    records = seed_state.load("guest")
    rec = records["ai.urbanlab.uhvi@1"]
    records["ai.urbanlab.uhvi@1"] = seed_state.PackSeedRecord(
        seeded_at=None,
        uninstalled_at=rec.uninstalled_at,
        fixture_mtime=1.0,  # epoch+1s: the committed fixture is definitely newer
    )
    seed_state.save("guest", records)

    seeded = seed_dev_packs(user_key="guest")
    assert "ai.urbanlab.uhvi@1" in seeded
    assert "ai.urbanlab.uhvi@1" in _installed_names()


def test_curio_reseed_packs_env_overrides_tombstone(tmp_curio, real_fixtures_root, monkeypatch):
    seed_dev_packs(user_key="guest")
    uninstall_pack("guest", "ai.urbanlab.uhvi@1")
    assert "ai.urbanlab.uhvi@1" not in _installed_names()

    monkeypatch.setenv("CURIO_RESEED_PACKS", "1")
    seeded = seed_dev_packs(user_key="guest")
    assert "ai.urbanlab.uhvi@1" in seeded
    assert "ai.urbanlab.uhvi@1" in _installed_names()


def test_reinstall_clears_tombstone(tmp_curio, real_fixtures_root):
    """A deliberate reinstall must wipe the tombstone — otherwise the
    seeder would still treat the pack as 'user-uninstalled' on the next
    restart and skip a future fixture refresh."""
    seed_dev_packs(user_key="guest")
    uninstall_pack("guest", "ai.urbanlab.uhvi@1")
    assert _state()["ai.urbanlab.uhvi@1"].get("uninstalledAt") is not None

    src = real_fixtures_root / "ai.urbanlab.uhvi@1"
    install_pack_from_directory("guest", src)
    assert "ai.urbanlab.uhvi@1" not in _state(), "reinstall should clear the marker"
    assert "ai.urbanlab.uhvi@1" in _installed_names()


# ---------------------------------------------------------------------------
# Untracked pre-existing runtime copies (upgrade from a build that
# predates the seed-state file) should be left alone, not re-seeded.
# ---------------------------------------------------------------------------

def test_untracked_existing_copy_is_adopted_into_state(tmp_curio, real_fixtures_root):
    """A runtime pack with no seed-state record (because the user is
    upgrading from an older build) must not be force-refreshed on the
    next startup, but the seeder *does* adopt it into the state file so
    a subsequent uninstall lands on a meaningful tombstone."""
    src = real_fixtures_root / "ai.urbanlab.uhvi@1"
    dest = user_packs_dir("guest") / src.name
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dest)
    assert seed_state.load("guest") == {}

    seed_dev_packs(user_key="guest")
    state = _state()
    assert state["ai.urbanlab.uhvi@1"].get("seededAt") is not None, (
        "seeder should have adopted the untracked runtime copy into state"
    )
    assert dest.is_dir(), "untracked runtime copy must not be force-refreshed"

    # Now uninstall and confirm the tombstone is sticky across restarts.
    uninstall_pack("guest", "ai.urbanlab.uhvi@1")
    seed_dev_packs(user_key="guest")
    assert "ai.urbanlab.uhvi@1" not in _installed_names()


def test_uninstall_without_prior_state_is_still_sticky(tmp_curio, real_fixtures_root):
    """Worst-case upgrade path: user has a runtime copy *and* uninstalls
    on the same backend cycle that introduced the tombstone protocol
    (so the seeder never had a chance to adopt the copy). The
    tombstone's fixture_mtime is ``None`` but the seeder still respects
    the uninstall — the user's intent wins over silent re-seeding."""
    src = real_fixtures_root / "ai.urbanlab.uhvi@1"
    dest = user_packs_dir("guest") / src.name
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dest)

    uninstall_pack("guest", "ai.urbanlab.uhvi@1")
    rec = _state()["ai.urbanlab.uhvi@1"]
    assert rec.get("uninstalledAt") is not None
    assert "fixtureMtime" not in rec, (
        "no prior seeded record means we cannot anchor the tombstone"
    )

    seed_dev_packs(user_key="guest")
    assert "ai.urbanlab.uhvi@1" not in _installed_names()


# ---------------------------------------------------------------------------
# Marker file robustness
# ---------------------------------------------------------------------------

def test_corrupt_state_file_does_not_block_startup(tmp_curio, real_fixtures_root):
    seed_dev_packs(user_key="guest")
    state_path = user_packs_dir("guest") / seed_state.STATE_FILENAME
    state_path.write_text("{not valid json", encoding="utf-8")

    # ``load`` swallows the parse error and returns an empty dict so a
    # corrupt marker can never block startup.
    assert seed_state.load("guest") == {}
    # The seeder runs cleanly against a corrupt state file — the
    # important property is that startup does not raise.
    seed_dev_packs(user_key="guest")

    # Forcing a re-seed (uninstall + CURIO_RESEED_PACKS) restores a
    # well-formed marker on disk, proving the corrupt file is recoverable
    # without manual intervention.
    uninstall_pack("guest", "ai.urbanlab.uhvi@1")
    os.environ["CURIO_RESEED_PACKS"] = "1"
    try:
        seed_dev_packs(user_key="guest")
    finally:
        os.environ.pop("CURIO_RESEED_PACKS", None)
    assert json.loads(state_path.read_text(encoding="utf-8"))["version"] == 1
