"""Tests for the dev seeder + seed-state tombstone protocol.

The regressions these tests guard against:

* The dev seeder used to copy any fixture package whose runtime dest was
  missing — meaning a user-uninstalled package came right back the next
  time Werkzeug's reloader fired. That's the "I can't uninstall my
  package" UX bug the marker file (see ``seed_state.py``) exists to fix.
* The seeder used to re-copy the built-in package on EVERY call by deleting
  the live directory and rebuilding it in place (memo dev/93 D1). Four
  request handlers call it, so passes overlap: readers caught the store
  mid-rebuild and silently lost every built-in template, and one observed
  store was left holding a single file. Seeding is now serialized per user,
  each package lands atomically, and only a broken built-in is re-copied.

The matrix exercised here:

* fresh fixture set → seeder copies once, then is idempotent
* uninstall + restart → package stays uninstalled
* uninstall + fixture-mtime advance + restart → tombstone is overridden
* uninstall + user reinstall → tombstone is cleared
* ``CURIO_RESEED_PACKAGES=1`` → escape hatch overrides everything
* healthy store → no writes at all
* truncated / unreadable built-in → self-healed on the next pass
* concurrent passes + concurrent readers → never a partial store
"""
from __future__ import annotations

import json
import shutil
import threading
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


# ---------------------------------------------------------------------------
# Example-dep packages (CURIO_SEED_EXAMPLES): seeded alongside builtin so
# their python deps persist via the launcher's user-store walk, but an
# explicit uninstall still sticks (unlike builtin's force path).
# ---------------------------------------------------------------------------

@pytest.fixture()
def seed_examples_flag():
    from utk_curio.backend.app.packages import seed as packages_seed
    original = packages_seed.CURIO_SEED_EXAMPLES
    packages_seed.CURIO_SEED_EXAMPLES = True
    yield
    packages_seed.CURIO_SEED_EXAMPLES = original


def test_example_dep_package_ids_derived_from_lockfiles():
    """The example-dep package set is derived from the bundled examples'
    ``dataflow.packages`` lockfiles — example 09 declares curio.weather, so
    curio.weather is provisioned."""
    from utk_curio.backend.app.packages.seed import example_dep_package_ids

    ids = example_dep_package_ids()
    assert "curio.weather" in ids
    assert "curio.builtin" not in ids  # always-installed, never an example dep


def test_install_on_demand_packages_are_excluded_even_when_declared():
    """A heavy package stays out of the boot install *explicitly*.

    It used to stay out by accident: nothing pip-installed curio.streetvision
    because no example declared it, and example 10 was left with an empty
    lockfile to keep it that way. That silence is what broke #233 - with
    nothing declaring the dependency, and the example's node types written
    unversioned, the backend's backfill had no way to name the package the
    dataflow needed, so its nodes rendered "Loading node…" forever.

    Example 10 now declares it, and the exclusion is stated here instead. This
    asserts the declaration exists AND that it still does not reach the
    launcher's pip walk - the whole point of separating the two.
    """
    import json
    from pathlib import Path

    from utk_curio.backend.app.packages.seed import (
        INSTALL_ON_DEMAND_PACKAGE_IDS,
        example_dep_package_ids,
    )

    repo_root = Path(__file__).resolve().parents[4]
    example = repo_root / "docs" / "examples" / "10-street-vision-cv-analysis.json"
    declared = json.loads(example.read_text(encoding="utf-8"))["dataflow"]["packages"]
    assert "curio.streetvision@1" in declared, (
        "example 10 must declare the package its nodes need, or nothing can "
        "resolve them (#233)"
    )

    assert "curio.streetvision" in INSTALL_ON_DEMAND_PACKAGE_IDS
    assert "curio.streetvision" not in example_dep_package_ids(), (
        "declaring a heavy package must not put it in the boot install - that "
        "is a ~3 GB torch download on every --with-examples start"
    )


def test_examples_flag_seeds_weather(tmp_curio, real_fixtures_root, seed_examples_flag):
    seed_dev_packageages(user_key="guest")
    installed = _installed_names()
    assert "curio.weather@1" in installed
    assert any(name.startswith("curio.builtin@") for name in installed)
    # Still an allowlist, not a full-catalog walk.
    assert "ai.urbanlab.uhvi@1" not in installed


def test_no_examples_flag_keeps_weather_out(tmp_curio, real_fixtures_root):
    seed_dev_packageages(user_key="guest")
    assert "curio.weather@1" not in _installed_names()


def _builtin_dir(user_key: str = "guest") -> Path:
    base = user_packageages_dir(user_key)
    matches = [p for p in base.iterdir() if p.name.startswith("curio.builtin@")]
    assert len(matches) == 1, f"expected exactly one built-in copy, got {matches}"
    return matches[0]


def _template_count(user_key: str = "guest") -> int:
    """Templates the backend would actually offer — the value that silently
    went to zero while the store was truncated."""
    from utk_curio.backend.app.packages.manifest import load_packageage_manifest

    return len(load_packageage_manifest(_builtin_dir(user_key)).templates)


# ---------------------------------------------------------------------------
# dev/93 D1: no per-request destruction, atomic swaps, self-heal
# ---------------------------------------------------------------------------

def test_healthy_builtin_is_not_recopied(tmp_curio, real_fixtures_root, monkeypatch):
    """The defect in one assertion: a second pass over a healthy store must
    not touch the filesystem. The built-in used to be force-re-seeded on
    every call — ``rmtree`` + ``copytree`` into the live directory — which is
    both pointless work on four request paths and the window that corrupted
    the store."""
    seed_dev_packageages(user_key="guest")
    assert _template_count() > 0

    from utk_curio.backend.app.packages import seed as packages_seed

    def _fail(*args, **kwargs):
        raise AssertionError("a healthy store must not be re-copied")

    monkeypatch.setattr(packages_seed.shutil, "copytree", _fail)
    monkeypatch.setattr(packages_seed.shutil, "rmtree", _fail)

    assert seed_dev_packageages(user_key="guest") == []


def test_truncated_builtin_self_heals(tmp_curio, real_fixtures_root):
    """The exact observed corruption: a built-in package directory holding
    only ``integrity.json``, its manifest gone, so ``available_templates``
    silently offered nothing. The next pass must restore it with no manual
    filesystem surgery."""
    seed_dev_packageages(user_key="guest")
    expected = _template_count()

    builtin = _builtin_dir()
    (builtin / "manifest.json").unlink()
    for stray in builtin.iterdir():
        if stray.name != "integrity.json":
            stray.unlink()
    assert [p.name for p in builtin.iterdir()] == ["integrity.json"]

    assert builtin.name in seed_dev_packageages(user_key="guest")
    assert (builtin / "manifest.json").is_file()
    assert _template_count() == expected


def test_builtin_missing_a_file_integrity_names_self_heals(
    tmp_curio, real_fixtures_root
):
    """A subtler truncation: the manifest still loads, but a file
    ``integrity.json`` names is gone. Health is defined by the manifest AND
    the integrity listing, so this is repaired too."""
    seed_dev_packageages(user_key="guest")
    builtin = _builtin_dir()
    listed = json.loads((builtin / "integrity.json").read_text(encoding="utf-8"))
    victim = next(name for name in listed["sha256"] if name != "manifest.json")
    (builtin / victim).unlink()

    assert builtin.name in seed_dev_packageages(user_key="guest")
    assert (builtin / victim).is_file()


def test_builtin_without_integrity_file_is_left_alone(
    tmp_curio, real_fixtures_root, monkeypatch
):
    """A package that ships no ``integrity.json`` must not be judged
    unhealthy — treating a missing listing as corruption would re-seed on
    every request, reinstating the very behaviour this change removes."""
    seed_dev_packageages(user_key="guest")
    (_builtin_dir() / "integrity.json").unlink()

    from utk_curio.backend.app.packages import seed as packages_seed

    def _fail(*args, **kwargs):
        raise AssertionError("a loadable package must not be re-copied")

    monkeypatch.setattr(packages_seed.shutil, "copytree", _fail)
    assert seed_dev_packageages(user_key="guest") == []


def test_builtin_reseeds_when_missing_despite_tombstone(
    tmp_curio, real_fixtures_root
):
    """Users cannot opt out of the default node kinds: a stray built-in
    tombstone (only reachable from an older build — ``uninstall`` refuses the
    built-in) must not leave a canvas with no node types."""
    seed_dev_packageages(user_key="guest")
    builtin_name = _builtin_dir().name
    shutil.rmtree(user_packageages_dir("guest") / builtin_name)
    seed_state.mark_uninstalled("guest", builtin_name)

    assert builtin_name in seed_dev_packageages(user_key="guest")
    assert _template_count() > 0


def test_failed_swap_keeps_the_previous_tree(tmp_curio, real_fixtures_root, monkeypatch):
    """A refresh that dies mid-swap must not become a deletion. The old tree
    is moved aside, so if the move-into-place fails it goes back."""
    seed_dev_packageages(user_key="guest")
    builtin = _builtin_dir()
    expected = _template_count()

    from utk_curio.backend.app.packages import seed as packages_seed

    real_replace = packages_seed.os.replace
    calls = {"n": 0}

    def _replace(src, dst):
        calls["n"] += 1
        if calls["n"] == 2:  # the move-into-place, after the move-aside
            raise OSError("simulated crash mid-swap")
        return real_replace(src, dst)

    monkeypatch.setattr(packages_seed.os, "replace", _replace)
    monkeypatch.setattr(packages_seed, "CURIO_RESEED_PACKAGES", True)
    assert seed_dev_packageages(user_key="guest") == []

    monkeypatch.undo()
    assert builtin.is_dir()
    assert _template_count() == expected, "the package must survive a failed refresh"


def test_seed_staging_leftovers_are_swept(tmp_curio, real_fixtures_root):
    """A staging tree from a killed swap is cleaned up by the next pass, and
    never mistaken for a package."""
    from utk_curio.backend.app.packages.seed import _SEED_STAGING_PREFIX
    from utk_curio.backend.app.packages.storage import list_user_packageages

    seed_dev_packageages(user_key="guest")
    orphan = user_packageages_dir("guest") / f"{_SEED_STAGING_PREFIX}dead"
    orphan.mkdir()
    (orphan / "half-copied.json").write_text("{}", encoding="utf-8")

    assert orphan not in list_user_packageages("guest")
    seed_dev_packageages(user_key="guest")
    assert not orphan.exists()


def _read_builtin_templates(user_key: str = "guest") -> int | None:
    """How many templates the backend would offer from the built-in package.

    ``None`` means the directory is momentarily absent — the gap between the
    swap's two renames, since POSIX cannot replace a non-empty directory in
    one. Anything else that goes wrong is raised: a package that is *present
    but unreadable* is the corruption this change exists to prevent.
    """
    from utk_curio.backend.app.packages.manifest import load_packageage_manifest

    base = user_packageages_dir(user_key)
    matches = [p for p in base.iterdir() if p.name.startswith("curio.builtin@")]
    if not matches:
        return None
    package = matches[0]
    try:
        inode_before = package.stat().st_ino
    except FileNotFoundError:
        return None
    try:
        return len(load_packageage_manifest(package).templates)
    except Exception:
        # Identity, not mere existence: by the time we look again a later
        # swap may have put a *different* tree at the same path, which would
        # make a lost race look like corruption. Only a directory that stayed
        # the same inode throughout and still could not be read is a real
        # broken store.
        try:
            if package.stat().st_ino != inode_before:
                return None
        except FileNotFoundError:
            return None
        raise


def test_concurrent_passes_never_expose_a_broken_store(
    tmp_curio, real_fixtures_root, monkeypatch
):
    """The test that would have caught the reported outage.

    Eight threads seed the same user while eight more read the built-in
    manifest the way ``available_templates`` does. The invariant: a reader
    never sees the package *present but unreadable or short of templates*.
    Under the old ``rmtree``-then-``copytree`` that failed immediately — the
    live tree was deleted and rebuilt file by file, so readers walked a
    half-populated package, and a copy that lost the race left one behind
    permanently.

    A reader may still find the directory briefly absent while the swap does
    its two renames; that state is transient by construction (the new tree is
    complete before either rename) and self-corrects within microseconds,
    where a truncated tree did not.

    ``CURIO_RESEED_PACKAGES`` keeps every pass doing real work, so the swap
    machinery runs under genuine contention instead of short-circuiting on
    the healthy-store check.
    """
    from utk_curio.backend.app.packages import seed as packages_seed

    seed_dev_packageages(user_key="guest")
    expected = _template_count()
    assert expected > 0
    monkeypatch.setattr(packages_seed, "CURIO_RESEED_PACKAGES", True)

    failures: list[str] = []
    reads = {"complete": 0, "absent": 0}
    stop = threading.Event()

    def seeder():
        try:
            for _ in range(4):
                seed_dev_packageages(user_key="guest")
        except Exception as exc:  # noqa: BLE001 — recorded, not raised, in a thread
            failures.append(f"seeder raised {exc!r}")
        finally:
            stop.set()

    def reader():
        while not stop.is_set():
            try:
                count = _read_builtin_templates()
            except Exception as exc:  # noqa: BLE001
                failures.append(f"reader saw a present-but-broken package: {exc!r}")
                continue
            if count is None:
                reads["absent"] += 1
            elif count != expected:
                failures.append(f"reader saw {count} templates, expected {expected}")
            else:
                reads["complete"] += 1

    threads = [threading.Thread(target=seeder) for _ in range(8)]
    threads += [threading.Thread(target=reader) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)

    assert not failures, failures[:5]
    assert reads["complete"] > 0, "the readers never observed a usable store"
    assert _read_builtin_templates() == expected


def test_weather_uninstall_is_sticky_under_examples_flag(
    tmp_curio, real_fixtures_root, seed_examples_flag
):
    seed_dev_packageages(user_key="guest")
    assert "curio.weather@1" in _installed_names()

    uninstall_packageage("guest", "curio.weather@1")
    seed_dev_packageages(user_key="guest")
    assert "curio.weather@1" not in _installed_names(), (
        "an explicit uninstall must not be resurrected by example seeding"
    )

    # CURIO_RESEED_PACKAGES=1 stays the documented escape hatch.
    from utk_curio.backend.app.packages import seed as packages_seed
    original = packages_seed.CURIO_RESEED_PACKAGES
    packages_seed.CURIO_RESEED_PACKAGES = True
    try:
        seed_dev_packageages(user_key="guest")
    finally:
        packages_seed.CURIO_RESEED_PACKAGES = original
    assert "curio.weather@1" in _installed_names()


# ---------------------------------------------------------------------------
# dev/99: readers share the seeder's lock, so the two-renames interval stops
# being observable
# ---------------------------------------------------------------------------

def _production_template_ids(user_key: str) -> set[str]:
    """Read through a real production path — the same call an agent's roster,
    plan mint and node.create all sit on."""
    from utk_curio.backend.app.packages import services as packages_services

    return {
        t["id"] for t in packages_services.available_templates(user_key, "no-such-project")
    }


def _lockfile_dirs(user_key: str) -> set[str]:
    from utk_curio.backend.app.packages.resolver import lockfile_for_user

    return {e["dirName"] for e in lockfile_for_user(user_key)["installedPackages"]}


def _starter_ids(user_key: str) -> set[str]:
    from utk_curio.backend.app.packages.starters import generate_packageage_starters

    # The builtin ships no ``source`` files, so the roster is legitimately
    # empty; the count sentinel keeps the probe non-empty — the load-bearing
    # assertion for this reader is that it BLOCKS during the window.
    return {f"starters:{len(generate_packageage_starters(user_key))}"}


def _library_sources(user_key: str) -> set[str]:
    from utk_curio.backend.app.packages.libraries import package_derived

    # The builtin declares no libraries; enumeration is still the snapshot.
    from utk_curio.backend.app.packages.build_deps import installed_manifests

    return set(installed_manifests(user_key)) | {e.source for e in package_derived(user_key)}


def _installed_majors(user_key: str) -> dict:
    from utk_curio.backend.app.packages import services as packages_services

    return packages_services._installed_majors_by_pkg(user_key)


_PRODUCTION_READERS = {
    "available_templates": _production_template_ids,
    "resolver.lockfile_for_user": _lockfile_dirs,
    "starters": _starter_ids,
    "libraries+build_deps": _library_sources,
    "installed_majors": _installed_majors,
}


@pytest.mark.parametrize("reader_name", sorted(_PRODUCTION_READERS))
def test_reader_waits_out_the_swap_window_instead_of_seeing_nothing(
    tmp_curio, real_fixtures_root, monkeypatch, reader_name
):
    """The gap dev/93 left and dev/99 closes, pinned deterministically — for
    every production reader the §2 audit migrated, not only the template roster.

    `_swap_in_package` moves the old tree aside and then moves the staged tree
    in; POSIX cannot do that in one rename. Parked between those two renames,
    the package path does not exist. Before this change a production reader
    overlapping that instant saw a healthy package as missing — downstream, a
    false "not an available template for this project" refusal. Now it blocks
    on the seeder's lock and returns a complete snapshot.
    """
    from utk_curio.backend.app.packages import seed as packages_seed

    read = _PRODUCTION_READERS[reader_name]
    seed_dev_packageages(user_key="guest")
    expected = read("guest")
    assert expected, "fixture should give the reader something to see"

    builtin_name = _builtin_dir_name()
    moved_aside = threading.Event()
    release = threading.Event()
    real_replace = packages_seed.os.replace

    def _parking_replace(src, dst):
        result = real_replace(src, dst)
        # Park on the MOVE-ASIDE specifically (`<pkg>.displaced`), not on the
        # first os.replace to run: patching the module patches it globally, and
        # seed_state's atomic marker write gets there first.
        if str(dst).endswith(".displaced"):
            moved_aside.set()
            release.wait(timeout=10)
        return result

    monkeypatch.setattr(packages_seed.os, "replace", _parking_replace)
    monkeypatch.setattr(packages_seed, "CURIO_RESEED_PACKAGES", True)

    seeder = threading.Thread(target=seed_dev_packageages, kwargs={"user_key": "guest"})
    seeder.start()
    assert moved_aside.wait(timeout=10), "seeder never reached the swap window"

    # The package really is absent on disk right now — this is the window.
    assert not (user_packageages_dir("guest") / builtin_name).exists()

    result: dict = {}
    reader = threading.Thread(target=lambda: result.update(ids=read("guest")))
    reader.start()
    reader.join(timeout=0.5)
    assert reader.is_alive(), (
        "the reader returned DURING the swap window — it must wait for the lock"
    )

    release.set()
    reader.join(timeout=10)
    seeder.join(timeout=10)
    assert not reader.is_alive() and not seeder.is_alive()
    assert result["ids"] == expected, "the reader must see a complete snapshot"


def _builtin_dir_name() -> str:
    base = user_packageages_dir("guest")
    return next(p.name for p in base.iterdir() if p.name.startswith("curio.builtin@"))


def test_production_readers_never_see_an_absent_package_under_stress(
    tmp_curio, real_fixtures_root, monkeypatch
):
    """dev/99 §7.3: the same 8-seeder/8-reader forced-reseed stress as the
    dev/93 test, but through a PRODUCTION reader — and now requiring zero
    absent reads, not merely zero broken ones. The dev/93 test deliberately
    tolerated absence because nothing shared the lock; that tolerance is what
    this change removes."""
    from utk_curio.backend.app.packages import seed as packages_seed

    seed_dev_packageages(user_key="guest")
    expected = _production_template_ids("guest")
    monkeypatch.setattr(packages_seed, "CURIO_RESEED_PACKAGES", True)

    failures: list[str] = []
    reads = {"n": 0}
    stop = threading.Event()

    def seeder():
        try:
            for _ in range(4):
                seed_dev_packageages(user_key="guest")
        except Exception as exc:  # noqa: BLE001 — recorded, not raised, in a thread
            failures.append(f"seeder raised {exc!r}")
        finally:
            stop.set()

    def reader():
        while not stop.is_set():
            try:
                ids = _production_template_ids("guest")
            except Exception as exc:  # noqa: BLE001
                failures.append(f"reader raised {exc!r}")
                continue
            reads["n"] += 1
            if ids != expected:
                failures.append(f"reader saw {len(ids)} templates, expected {len(expected)}")

    threads = [threading.Thread(target=seeder) for _ in range(8)]
    threads += [threading.Thread(target=reader) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)

    assert not failures, failures[:5]
    assert reads["n"] > 0
    assert _production_template_ids("guest") == expected


def test_fixture_catalog_reads_happen_before_the_lock_is_taken(
    tmp_curio, real_fixtures_root, monkeypatch
):
    """dev/99 R1.3: the writer's critical section is store work only. The
    fixture rglob (`_max_mtime`), the builtin lookup and the docs/examples scan
    (`example_dep_package_ids`) are catalog reads — every reader now waits on
    this lock, so they must not be inside it. Asserted by recording whether the
    per-user thread lock is held when each catalog read runs."""
    from utk_curio.backend.app.common import file_locks
    from utk_curio.backend.app.packages import seed as packages_seed

    thread_lock = file_locks.keyed_thread_lock("package-seed", "guest")
    held_during: dict[str, bool] = {}

    def _spy(name, real):
        def _wrapped(*a, **k):
            held_during[name] = held_during.get(name, False) or thread_lock.locked()
            return real(*a, **k)
        return _wrapped

    monkeypatch.setattr(packages_seed, "_max_mtime", _spy("_max_mtime", packages_seed._max_mtime))
    monkeypatch.setattr(
        packages_seed, "_latest_builtin_dir",
        _spy("_latest_builtin_dir", packages_seed._latest_builtin_dir),
    )
    monkeypatch.setattr(
        packages_seed, "example_dep_package_ids",
        _spy("example_dep_package_ids", packages_seed.example_dep_package_ids),
    )
    monkeypatch.setattr(packages_seed, "CURIO_SEED_EXAMPLES", True)

    assert seed_dev_packageages(user_key="guest"), "the pass should seed something"
    assert set(held_during) == {"_max_mtime", "_latest_builtin_dir", "example_dep_package_ids"}
    assert not any(held_during.values()), (
        f"catalog reads ran INSIDE the seed lock: "
        f"{[k for k, v in held_during.items() if v]}"
    )


# ---------------------------------------------------------------------------
# An upgrade reaches a package the user already installed (#194).
#
# A fix can ship inside a package at an unchanged version — the catalog under
# <repo_root>/packages moves, the coordinate does not. Installing is copy-once,
# so before this the user kept whatever they first copied, indefinitely. These
# two tests pin the rule and its limit: a stale copy refreshes, a copy the user
# deliberately removed does not come back.
# ---------------------------------------------------------------------------

def _probe_file(user_key: str, dir_name: str, rel: str = "manifest.json") -> Path:
    return user_packageages_dir(user_key) / dir_name / rel


def test_a_stale_installed_package_is_refreshed_from_the_catalog(
    tmp_curio, real_fixtures_root,
):
    """The #194 delivery bug, at the unit layer."""
    dir_name = "ai.urbanlab.uhvi@1"
    install_packageage_from_directory("guest", real_fixtures_root / dir_name)
    assert dir_name in _installed_names()

    probe = _probe_file("guest", dir_name)
    catalog_bytes = (real_fixtures_root / dir_name / "manifest.json").read_bytes()
    assert probe.read_bytes() == catalog_bytes, "install did not copy faithfully"

    # Diverge the store copy the way an UPGRADE diverges it, which means leaving
    # it internally consistent: an older copy's files and its own
    # ``integrity.json`` agree with each other, they are simply an older pair
    # than the catalog's. Editing the file alone would leave the store's map
    # still quoting the original hash — a damaged copy, not an out-of-date one,
    # and the refresh is right to decline that. Getting this wrong made an
    # earlier version of this test pass for the wrong reason.
    from utk_curio.backend.app.packages.installer import refresh_packageage_integrity

    probe.write_bytes(catalog_bytes + b"\n")
    refresh_packageage_integrity(probe.parent)
    seed_state.clear("guest", dir_name)
    assert probe.read_bytes() != catalog_bytes

    seed_dev_packageages(user_key="guest")

    assert probe.read_bytes() == catalog_bytes, (
        "a stale installed package was not refreshed, so a fix shipped inside "
        "a package at an unchanged version never reaches an existing install"
    )


def test_an_uninstalled_package_is_not_resurrected_by_the_refresh(
    tmp_curio, real_fixtures_root,
):
    """The limit that matters: refreshing must not undo an uninstall.

    The refresh only ever looks at packages the store already holds, so a
    tombstoned one is not a candidate — but that is the property worth pinning,
    because the obvious implementation (widen the seed plan to the whole
    catalog) would resurrect it.
    """
    dir_name = "ai.urbanlab.uhvi@1"
    install_packageage_from_directory("guest", real_fixtures_root / dir_name)
    uninstall_packageage("guest", dir_name)
    assert dir_name not in _installed_names()

    seed_dev_packageages(user_key="guest")

    assert dir_name not in _installed_names(), (
        "the refresh brought back a package the user uninstalled"
    )
