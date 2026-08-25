"""The per-user package-seed lock contract (memo dev/99 §7.1, §7.6, §7.8–§7.10).

What is pinned here, and why each pin exists:

* ONE contract. The seeder and every reader go through
  ``packages.locks.package_seed_lock`` — the file name and namespace live in
  exactly one module, so a writer and a reader can never disagree about
  which lock they share (AC-1/AC-2).
* Release on exception, same-user blocking, cross-user independence — all
  with events, never sleeps (AC-11).
* The Windows fallback (no ``fcntl``) still takes a cross-process lock and
  retries through msvcrt's contention timeout (§7.9).
* ONE acquisition per logical snapshot for the composed readers the audit
  migrated (§7.6): the resolver's two store reads, the catalog probe, the
  build-deps review, the per-user lockfile.
* A structural audit (§7.8): every raw ``list_user_packageages(...)`` call in
  the application is inside a function that is known to own the lock or to be
  an explicitly unlocked core. A new caller has to add itself here — which is
  the point: it makes "did you think about the swap window?" a review question
  the test asks for you.
"""
from __future__ import annotations

import ast
import threading
from pathlib import Path

import pytest

from utk_curio.backend.app.common import file_locks
from utk_curio.backend.app.packages import locks
from utk_curio.backend.app.packages import seed as packages_seed
from utk_curio.backend.app.packages import services as packages_services
from utk_curio.backend.app.packages.locks import package_seed_lock
from utk_curio.backend.app.packages.storage import user_packageages_dir

from utk_curio.backend.tests.test_packages.test_available_templates import (  # noqa: F401
    _template,
    _write_package,
    alice_project,
)


# ---------------------------------------------------------------------------
# §7.1 — one contract
# ---------------------------------------------------------------------------

def test_seeder_and_readers_share_the_one_lock_helper():
    """Same object, not merely same-looking: the seeder imports the reader's
    helper. The private ``_SEED_LOCK_*`` constants dev/93 had in seed.py are
    gone, so there is nothing left to drift."""
    assert packages_seed.package_seed_lock is locks.package_seed_lock
    assert packages_services.package_seed_lock is locks.package_seed_lock
    assert not hasattr(packages_seed, "_SEED_LOCK_FILENAME")
    assert not hasattr(packages_seed, "_SEED_LOCK_NAMESPACE")


def test_lock_file_path_namespace_and_key_are_the_seeders(tmp_curio, monkeypatch):
    seen: list[tuple[Path, str, str]] = []
    real = file_locks.exclusive_lock

    def _spy(lock_path, *, namespace, key):
        seen.append((Path(lock_path), namespace, key))
        return real(lock_path, namespace=namespace, key=key)

    monkeypatch.setattr(locks, "exclusive_lock", _spy)
    with package_seed_lock("guest"):
        pass
    assert seen == [
        (user_packageages_dir("guest") / ".seed.lock", "package-seed", "guest")
    ]
    # An absent store is created so the lock file has a home — an empty store
    # still yields an empty listing, so no reader's logical result changes.
    assert user_packageages_dir("guest").is_dir()


def test_lock_is_released_when_the_body_raises(tmp_curio):
    with pytest.raises(RuntimeError):
        with package_seed_lock("guest"):
            raise RuntimeError("snapshot code failed")
    thread_lock = file_locks.keyed_thread_lock("package-seed", "guest")
    assert not thread_lock.locked(), "the in-process layer must be released"
    # And the interprocess layer: re-acquisition on this thread must not block.
    acquired = threading.Event()

    def _reacquire():
        with package_seed_lock("guest"):
            acquired.set()

    t = threading.Thread(target=_reacquire)
    t.start()
    t.join(timeout=5)
    assert acquired.is_set(), "the interprocess layer was not released"


# ---------------------------------------------------------------------------
# §7.10 — same-user blocking, cross-user independence, no timing assertions
# ---------------------------------------------------------------------------

def _hold(user_key: str, entered: threading.Event, release: threading.Event):
    with package_seed_lock(user_key):
        entered.set()
        release.wait(timeout=10)


def test_same_user_waits_and_different_user_does_not(tmp_curio):
    entered, release = threading.Event(), threading.Event()
    holder = threading.Thread(target=_hold, args=("guest", entered, release))
    holder.start()
    assert entered.wait(timeout=5)

    # A different user's reader must get through while guest's lock is held.
    other_done = threading.Event()

    def _other():
        with package_seed_lock("7"):
            other_done.set()

    other = threading.Thread(target=_other)
    other.start()
    other.join(timeout=5)
    assert other_done.is_set(), "user 7 must not wait on guest's lock"

    # The same user's reader must NOT get through until the holder releases.
    same_done = threading.Event()

    def _same():
        with package_seed_lock("guest"):
            same_done.set()

    same = threading.Thread(target=_same)
    same.start()
    same.join(timeout=0.3)
    assert not same_done.is_set(), "same-user reader ran INSIDE the writer's hold"

    release.set()
    same.join(timeout=5)
    holder.join(timeout=5)
    assert same_done.is_set()


def test_lock_is_documented_non_reentrant():
    """Not a feature — a constraint every composite in services.py is shaped
    by (``exclusive_lock`` sits on a plain ``threading.Lock``). Exercising the
    deadlock itself would leave a thread holding the lock for every later test,
    so the pin is on the primitive and the documentation, not a live nest."""
    assert "NOT reentrant" in (package_seed_lock.__doc__ or "") + (locks.__doc__ or "")
    assert type(file_locks.keyed_thread_lock("package-seed", "guest")) is type(threading.Lock())


# ---------------------------------------------------------------------------
# §7.9 — the Windows path, through mocks (same shape as test_projects)
# ---------------------------------------------------------------------------

class _FakeMsvcrt:
    LK_LOCK = 1
    LK_NBLCK = 2
    LK_UNLCK = 0

    def __init__(self, fail_times: int = 0):
        self.calls: list[tuple[int, int]] = []
        self.lock_attempts = 0
        self._fail_remaining = fail_times

    def locking(self, fd, mode, nbytes):
        if mode == self.LK_LOCK:
            self.lock_attempts += 1
            if self._fail_remaining > 0:
                self._fail_remaining -= 1
                raise OSError("Resource deadlock avoided")
        self.calls.append((mode, nbytes))


def test_windows_fallback_takes_and_releases_a_cross_process_lock(tmp_curio, monkeypatch):
    fake = _FakeMsvcrt(fail_times=2)
    monkeypatch.setattr(file_locks, "fcntl", None)
    monkeypatch.setattr(file_locks, "msvcrt", fake)
    with package_seed_lock("guest"):
        pass
    assert fake.lock_attempts == 3, "must retry through msvcrt's contention timeout"
    assert (fake.LK_LOCK, 1) in fake.calls and (fake.LK_UNLCK, 1) in fake.calls
    assert all(mode != fake.LK_NBLCK for mode, _ in fake.calls)


# ---------------------------------------------------------------------------
# §7.6 — one acquisition per composed snapshot
# ---------------------------------------------------------------------------

def _count_acquisitions(monkeypatch, module) -> dict:
    """Count entries into the seed lock as seen from *module*'s import."""
    counter = {"n": 0}
    real = locks.package_seed_lock
    from contextlib import contextmanager

    @contextmanager
    def _counting(user_key):
        counter["n"] += 1
        with real(user_key):
            yield

    monkeypatch.setattr(module, "package_seed_lock", _counting)
    return counter


def _two_packages(user_and_token, alice_project):
    from utk_curio.backend.app.projects import services as projects_services

    user, _ = user_and_token
    key = projects_services._user_dir_key(user)
    _write_package(key, "curio.builtin", 1, [_template("data-loading", "Load")])
    _write_package(key, "ai.test.other", 1, [_template("thing", "Thing")])
    return key, alice_project


def test_resolver_reads_the_store_twice_under_one_acquisition(
    user_and_token, alice_project, tmp_curio, monkeypatch
):
    from utk_curio.backend.app.packages import resolver

    key, _ = _two_packages(user_and_token, alice_project)
    counter = _count_acquisitions(monkeypatch, resolver)
    result = resolver.resolve_for_project(key, ["curio.builtin@1"])
    assert result.ok
    assert counter["n"] == 1, "pinned + transitive reads must share one snapshot"

    counter["n"] = 0
    lock = resolver.lockfile_for_user(key)
    assert len(lock["installedPackages"]) == 2
    assert counter["n"] == 1, "enumerate + resolve must share one snapshot"


def test_agent_resolve_report_is_one_snapshot(
    user_and_token, alice_project, tmp_curio, monkeypatch
):
    key, _ = _two_packages(user_and_token, alice_project)
    counter = _count_acquisitions(monkeypatch, packages_services)
    report = packages_services.agent_resolve_report(key, ["ai.test.other@1"])
    assert [p["dirName"] for p in report["packages"]] == ["ai.test.other@1"]
    assert counter["n"] == 1, (
        "installed set, resolver reads and per-package manifests must be ONE hold"
    )


def test_build_deps_review_is_one_snapshot(
    user_and_token, alice_project, tmp_curio, monkeypatch
):
    from utk_curio.backend.app.packages import build_deps
    from utk_curio.backend.app.packages.build_models import parse_build_request

    key, _ = _two_packages(user_and_token, alice_project)
    counter = _count_acquisitions(monkeypatch, build_deps)
    request = parse_build_request({
        "mode": "create",
        "target": "ai.test.draft@1",
        "manifest": {"id": "ai.test.draft", "compatibility": {"major": 1},
                     "templates": [{"id": "draft-kind"}]},
        "files": {},
        "dependencies": {"packages": {"ai.test.other": "^1.0.0"}},
    })
    report = build_deps.resolve_dependencies(key, request, fetcher=None)
    assert [r["name"] for r in report.packages] == ["ai.test.other"]
    assert counter["n"] == 1, "python + package reviews must share one snapshot"


# ---------------------------------------------------------------------------
# §7.8 — structural audit: every raw store enumeration is accounted for
# ---------------------------------------------------------------------------

# Functions that may call ``list_user_packageages`` directly. Each is either
# the lock-owning reader itself (the call sits inside ``with
# package_seed_lock``) or an explicitly UNLOCKED core whose every caller holds
# the lock. Adding a name here is a deliberate act: say which of the two it is
# in the function's docstring.
_ACCOUNTED_ENUMERATORS = {
    "app/packages/services.py": {"_store_index"},           # unlocked core
    "app/packages/resolver.py": {"_load_manifests",         # unlocked core
                                 "lockfile_for_user"},      # lock owner
    "app/packages/routes.py": {"_ensure_user_seeded",       # lock owner
                               "list_installed_packageages",
                               "list_catalog_packageages",
                               "check_workflow_deps",
                               "_any_package_declares"},
    "app/packages/starters.py": {"_generate_unlocked"},     # unlocked core
    "app/packages/libraries.py": {"package_derived"},       # lock owner
    "app/packages/build_deps.py": {"installed_manifests"},  # lock owner
}


def _enumeration_sites() -> dict[str, set[str]]:
    app_root = Path(packages_services.__file__).resolve().parents[1]
    found: dict[str, set[str]] = {}
    for py in sorted(list((app_root / "packages").glob("*.py")) + list((app_root / "agents").glob("*.py"))):
        if py.name == "storage.py":
            continue  # the definition
        tree = ast.parse(py.read_text(encoding="utf-8"))
        rel = py.relative_to(app_root.parent).as_posix()

        class _V(ast.NodeVisitor):
            def __init__(self):
                self.stack: list[str] = []

            def visit_FunctionDef(self, node):
                self.stack.append(node.name)
                self.generic_visit(node)
                self.stack.pop()

            visit_AsyncFunctionDef = visit_FunctionDef

            def visit_Call(self, node):
                fn = node.func
                name = fn.id if isinstance(fn, ast.Name) else getattr(fn, "attr", None)
                if name == "list_user_packageages":
                    found.setdefault(rel, set()).add(self.stack[-1] if self.stack else "<module>")
                self.generic_visit(node)

        _V().visit(tree)
    return found


def test_every_raw_store_enumeration_is_a_known_lock_owner_or_unlocked_core():
    sites = _enumeration_sites()
    assert sites == _ACCOUNTED_ENUMERATORS, (
        "a raw list_user_packageages() call appeared (or moved) outside the "
        "accounted set — decide whether it owns the seed lock or is an unlocked "
        "core called only under it, then record it in _ACCOUNTED_ENUMERATORS"
    )


def test_agents_domain_never_enumerates_the_store_or_owns_the_lock():
    """ADR-AG-007: template knowledge stays in the packages domain. The agents
    module consumes composites; it neither walks the store nor takes the lock."""
    app_root = Path(packages_services.__file__).resolve().parents[1]
    for py in (app_root / "agents").glob("*.py"):
        text = py.read_text(encoding="utf-8")
        assert "list_user_packageages" not in text, py.name
        assert "package_seed_lock" not in text, py.name
