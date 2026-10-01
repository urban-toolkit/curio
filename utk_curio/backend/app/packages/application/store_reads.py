"""The locked reads of the per-user package store (memo dev/99): presence, installed majors, the one store walk, the typed manifest of an installed package.

Application layer of the packages package (memo dev/143, B2): cut from ``services.py``
by responsibility; every function keeps its name and body. Sibling modules are reached
module-qualified (``packages_<module>.name``) so a test that patches the owner is seen by
every caller, and import order between siblings cannot matter.
"""

from __future__ import annotations

from utk_curio.backend.app.packages.domain.manifest import ManifestError
from utk_curio.backend.app.packages.domain.package_id import (
    PACKAGE_DIR_RE,
    PackageIdError,
)
from utk_curio.backend.app.packages.repositories.manifests import load_package_manifest
from utk_curio.backend.app.packages.repositories.store import (
    list_user_packages,
    package_dir,
    user_packages_dir,
)
from utk_curio.backend.app.packages.infrastructure.locks import package_seed_lock


def _is_installed_in_user_store(user_key: str, dir_name: str) -> bool:
    """Presence probe, taken under the per-user seed lock (memo dev/99).

    This answer decides whether an install COPIES: a false "not installed"
    for the seeded builtin — the swap window — would send
    :func:`_ensure_user_store_install` to re-copy it from the catalog against
    the seeder's own replacement.
    """
    try:
        with package_seed_lock(user_key):
            return (package_dir(user_key, dir_name) / "manifest.json").is_file()
    except Exception:  # noqa: BLE001 — invalid dir_name etc.
        return False


def _installed_majors_by_pkg(user_key: str) -> dict[str, list[int]]:
    """Map ``<packageId>`` → sorted majors currently installed in user store.

    Feeds the spec-packages backfill so unversioned node types in legacy
    specs resolve to a concrete dirName when possible.

    Names-only snapshot under the per-user seed lock (memo dev/99): a
    backfill that missed the builtin's major during the swap window would
    resolve a legacy spec's node types to nothing.
    """
    base = user_packages_dir(user_key)
    if not base.is_dir():
        return {}
    out: dict[str, list[int]] = {}
    with package_seed_lock(user_key):
        names = [
            entry.name for entry in base.iterdir()
            if entry.is_dir() and PACKAGE_DIR_RE.match(entry.name)
        ]
    for name in names:
        pkg_id, _, major = name.rpartition("@")
        try:
            out.setdefault(pkg_id, []).append(int(major))
        except ValueError:
            continue
    for k in out:
        out[k].sort()
    return out


def _store_index(user_key: str) -> dict[str, object]:
    """ONE walk of the user's package store: ``dirName -> manifest``, or the
    exception that stopped it being read (memo dev/99 R2).

    Every template/catalog listing in this module used to walk the store and
    load manifests for itself, so composing three of them for one agent payload
    meant three traversals of the same directories. This is that walk, done
    once and shared.

    Unreadable packages are recorded rather than dropped, because what an
    unreadable package MEANS differs per caller: the availability report logs
    it and reports it as skipped (dev/93 D2), while the not-enlisted listing
    and the catalog overview simply pass over it. Each caller therefore
    applies its own scope filter first and then decides — the reason this
    returns the exception instead of silently omitting the entry.
    """
    out: dict[str, object] = {}
    for path in list_user_packages(user_key):
        try:
            out[path.name] = load_package_manifest(path)
        except (ManifestError, OSError) as exc:
            out[path.name] = exc
    return out


def _locked_store_index(user_key: str) -> dict[str, object]:
    """:func:`_store_index` taken under the per-user seed lock (memo dev/99).

    The lock covers exactly the walk and nothing else. What comes back is
    already detached — parsed manifest objects in memory, not live paths — so
    every caller's transform, filtering and sorting runs unlocked. That keeps
    the critical section to bounded local I/O, which is what lets readers share
    a writer's lock without becoming a latency problem.
    """
    with package_seed_lock(user_key):
        return _store_index(user_key)


def _read_manifest(user_key: str, dir_name: str):
    """The installed package's typed manifest, or ``None`` if unreadable.

    ``None`` rather than a raise: every caller here is reporting on an install
    that already happened, and a manifest that will not parse is a separate
    complaint from the one being made.
    """
    try:
        return load_package_manifest(package_dir(user_key, dir_name))
    except (ManifestError, OSError, PackageIdError):
        return None
