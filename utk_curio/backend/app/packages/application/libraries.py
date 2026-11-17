"""Per-user "Installed libraries" list.

The `/api/libraries` surface backs the "Installed libraries" menu (formerly
"Python packages"). Two distinct populations live here:

- **Standalone**: libraries the user added directly through the modal -
  things like ``numpy`` or ``scikit-learn==1.4.0`` that aren't tied to any
  installed node package. Persisted globally per user (one file per user),
  so the same set is available across every project. Stored as a JSON
  file at ``.curio/users/<user_key>/installed-libraries.json`` with shape::

      { "version": 1, "python": ["numpy", ...], "js": [...] }

- **Package-derived**: libraries declared by an installed node package's
  ``manifest.dependencies.{python,js}``. These are *read-only* from the
  modal's perspective - they get installed automatically by the catalog
  flow (see ``pip_runner.py``) and removed by ``prune_unreferenced_packages``.
  We surface them in the list so the user knows what's on their machine
  and why.

A corrupt or missing file is treated as an empty list (matches the
defaults/seed-state convention - startup is never blockable by a bad JSON).
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from utk_curio.backend.app.packages.infrastructure.locks import package_seed_lock
from utk_curio.backend.app.packages.repositories.store import (
    _user_key_segment,
    _users_base,
    list_user_packages,
)
from utk_curio.backend.app.packages.domain.manifest import ManifestError
from utk_curio.backend.app.packages.infrastructure import (
    backend_runtime as packages_backend_runtime,
    pip_runner as packages_pip_runner,
)
from utk_curio.backend.app.packages.infrastructure.target_locks import target_lock
from utk_curio.backend.app.packages.application import provisioning as packages_provisioning
from utk_curio.backend.app.packages.infrastructure.pip_runner import PipInstallError
from utk_curio.backend.app.packages.repositories.manifests import load_package_manifest

log = logging.getLogger(__name__)

_FILENAME = "installed-libraries.json"
_SCHEMA_VERSION = 1
_KINDS = ("python", "js")


@dataclass(frozen=True)
class LibraryEntry:
    name: str
    spec: str  # PEP 440 / npm-ish spec, or "" for "latest"
    kind: str  # "python" or "js"
    source: str  # "standalone" or "<packageId>@<major>"
    # Whether the library is actually present in the interpreter at the
    # declared spec. ``None`` for ``js`` (no runtime check). A package can
    # *declare* a dep that was never installed (or was later pip-uninstalled),
    # so the modal must distinguish "declared" from "actually installed".
    installed: bool | None = None


@dataclass(frozen=True)
class LibraryList:
    standalone: dict[str, list[str]] = field(default_factory=dict)
    """``{"python": [...], "js": [...]}`` - bare spec strings as written
    by the user (``"numpy"``, ``"scikit-learn==1.4.0"``)."""
    from_packages: list[LibraryEntry] = field(default_factory=list)
    """Flat list with attribution; one entry per (package, library)."""


def _path(user_key: str) -> Path:
    return _users_base() / _user_key_segment(user_key) / _FILENAME


def _load_raw(user_key: str) -> dict:
    p = _path(user_key)
    if not p.is_file():
        return {"python": [], "js": []}
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        log.warning("Corrupt %s for %s - treating as empty", _FILENAME, user_key)
        return {"python": [], "js": []}
    if not isinstance(raw, dict):
        return {"python": [], "js": []}
    return {
        kind: [s for s in (raw.get(kind) or []) if isinstance(s, str) and s.strip()]
        for kind in _KINDS
    }


def _save_raw(user_key: str, data: dict) -> None:
    p = _path(user_key)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": _SCHEMA_VERSION,
        **{kind: sorted(set(data.get(kind) or [])) for kind in _KINDS},
    }
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    os.replace(tmp, p)


def list_standalone(user_key: str) -> dict[str, list[str]]:
    """Return the user's standalone library list, kind-keyed."""
    return _load_raw(user_key)


def add_library(user_key: str, kind: str, spec: str) -> dict[str, list[str]]:
    """Add *spec* to the user's standalone list under *kind*; idempotent."""
    if kind not in _KINDS:
        raise ValueError(f"unknown kind {kind!r}; expected one of {_KINDS}")
    spec = (spec or "").strip()
    if not spec:
        raise ValueError("library spec must be non-empty")
    current = _load_raw(user_key)
    if spec not in current[kind]:
        current[kind].append(spec)
        _save_raw(user_key, current)
    return current


def remove_library(user_key: str, kind: str, spec: str) -> dict[str, list[str]]:
    """Drop *spec* from the user's standalone list; idempotent."""
    if kind not in _KINDS:
        raise ValueError(f"unknown kind {kind!r}; expected one of {_KINDS}")
    spec = (spec or "").strip()
    current = _load_raw(user_key)
    if spec in current[kind]:
        current[kind].remove(spec)
        _save_raw(user_key, current)
    return current


def _canonical(name: str) -> str:
    """PEP 503 normalisation: ``Scikit_Learn`` and ``scikit-learn`` are one."""
    return re.sub(r"[-_.]+", "-", name).lower()


def listed_by_others(user_key: str, kind: str, name: str, name_of) -> bool:
    """True if any user other than *user_key* lists *name* under *kind*.

    Every user's list is bookkeeping over ONE interpreter, so dropping an entry
    from yours must not uninstall what someone else asked for (#309).
    *name_of* maps a stored spec (``"scikit-learn==1.4.0"``) to its name.
    """
    base = _users_base()
    if not base.is_dir():
        return False
    wanted = _canonical(name)
    for entry in base.iterdir():
        if entry.name == user_key or not (entry / _FILENAME).is_file():
            continue
        try:
            other = _user_key_segment(entry.name)
        except ValueError:
            continue
        if any(_canonical(name_of(s)) == wanted for s in _load_raw(other)[kind]):
            return True
    return False


def package_derived(user_key: str) -> list[LibraryEntry]:
    """Read every installed package's manifest and collect their
    declared python + js deps. One entry per ``(package, lib)`` pair -
    no de-dup across packages so the user sees which package brought
    each library in.
    """
    # Snapshot the declarations under the seed lock (memo dev/99); the
    # presence probes below are importlib-metadata work, not store reads, and
    # run after release so the hold stays bounded to local manifest I/O.
    declared: list[tuple[str, dict[str, str], dict[str, str]]] = []
    with package_seed_lock(user_key, shared=True):
        for package_path in list_user_packages(user_key):
            try:
                m = load_package_manifest(package_path)
            except ManifestError:
                continue
            declared.append(
                (package_path.name, dict(m.python_deps or {}), dict(m.js_deps or {}))
            )

    out: list[LibraryEntry] = []
    for source, python_deps, js_deps in declared:
        for name, spec in python_deps.items():
            # A package can declare a dep that isn't actually present (never
            # installed, or pip-uninstalled later) - surface real state.
            out.append(LibraryEntry(
                name=name, spec=spec, kind="python", source=source,
                installed=packages_pip_runner.is_satisfied(name, spec),
            ))
        for name, spec in js_deps.items():
            out.append(LibraryEntry(name=name, spec=spec, kind="js", source=source))
    return out


def aggregate(user_key: str) -> LibraryList:
    """One-shot read of everything the modal needs to render."""
    return LibraryList(
        standalone=_load_raw(user_key),
        from_packages=package_derived(user_key),
    )


def split_lib_spec(spec: str) -> tuple[str, str]:
    """Split ``"name<spec>"`` into ``(name, "<spec>")``. The version part
    may be empty for bare names. Recognises PEP 440 comparators + the
    npm-ish ``@version`` separator (kept verbatim so the user's exact
    string round-trips through storage)."""
    s = spec.strip()
    for sep_start, _ in [(i, c) for i, c in enumerate(s) if c in "=<>~!"]:
        return s[:sep_start], s[sep_start:]
    if "@" in s and not s.startswith("@"):
        i = s.index("@")
        return s[:i], s[i + 1:]
    return s, ""


def any_package_declares(user_key: str, lib_name: str, kind: str) -> bool:
    """True if any installed package's manifest declares *lib_name* under
    ``dependencies.<kind>``. Used to gate pip uninstall on standalone
    remove - if a package needs the lib, we keep it on disk."""
    with package_seed_lock(user_key, shared=True):  # memo dev/99: one consistent walk
        for package_path in list_user_packages(user_key):
            try:
                m = load_package_manifest(package_path)
            except ManifestError:
                continue
            deps = (m.python_deps if kind == "python" else m.js_deps) or {}
            if lib_name in deps:
                return True
    return False


def install_user_library(user_key: str, name: str, version: str):
    """Install one standalone library for *user_key*, wherever their nodes
    import from.

    The libraries dialog's half of the #332 split, and the same rule
    :func:`provisioning.provision_python_deps` follows: the calling user's own
    tree under isolation, the shared interpreter without it. Raises what pip
    raises - the route turns a bad requirement into a 400 and a failed install
    into a 502.
    """
    deps = {name: version}
    if not packages_backend_runtime.per_user_node_envs():
        return packages_pip_runner.install_python_deps(deps)
    overlay = packages_backend_runtime.user_node_overlay_dir(user_key)
    overlay.mkdir(parents=True, exist_ok=True)
    with target_lock(user_key, packages_provisioning.NODE_OVERLAY_LOCK):
        # In front of the image's libraries, which win where they meet the
        # version asked: only what the image lacks goes into the tree.
        return packages_pip_runner.install_python_deps_to_target(deps, str(overlay), in_front=True)


def uninstall_user_library(user_key: str, name: str):
    """Remove one standalone library from wherever *user_key*'s nodes import it.

    The mirror of :func:`install_user_library`, and it has to be: under
    isolation the library lives in that user's own overlay, so running
    ``pip uninstall`` against the shared interpreter would both fail to remove
    their copy and risk removing a host-level package something else needs.
    """
    return uninstall_user_libraries(user_key, [name])


def uninstall_user_libraries(user_key: str, names):
    """:func:`uninstall_user_library` for several libraries at once: one pip
    run, or one walk of the user's tree under its lock.

    A package's removal takes its libraries back through this
    (``prune.py``), so they leave from where their install put them, as the
    dialog's do.
    """
    names = list(names)
    if not packages_backend_runtime.per_user_node_envs():
        return packages_pip_runner.uninstall_python_deps(names)
    overlay = packages_backend_runtime.user_node_overlay_dir(user_key)
    if not overlay.is_dir():
        # Nothing was ever installed for this user; saying so beats raising.
        return packages_pip_runner.UninstallReport(removed=[], kept=names)
    with target_lock(user_key, packages_provisioning.NODE_OVERLAY_LOCK):
        return packages_pip_runner.uninstall_python_deps_from_target(names, str(overlay))


def names_to_take_back(user_key: str, names) -> list[str]:
    """The libraries among *names* that may leave where *user_key*'s nodes
    import them from, sorted: those nothing asks for any more, which Curio
    put there. A package's removal (``prune.py``) and the dialog's Remove
    both take back only these.

    Under fork isolation that is the account's own tree, which no other
    account imports from and only Curio's pip writes, so only the account's
    own packages and list count. A library the install found the image held
    at an accepted version, such as its torch, was never copied into it, and
    the shared interpreter is not touched.

    Without isolation it is the one interpreter Curio runs on and every
    account's nodes import from. A library leaves it only when this server's
    own pip installed it there (``pip_runner.installed_here``) and no
    account's packages or list asks for it: what the interpreter held before
    (requirements, the image's torch, the shipped catalog's libraries, the
    user's own, and one the dialog found already installed) stays, whoever
    declared or listed it."""
    isolated = packages_backend_runtime.per_user_node_envs()
    kept = not_asked_for([user_key] if isolated else accounts(), names)
    return kept if isolated else packages_pip_runner.installed_here(kept)


def give_way_to_the_image(user_key: str) -> list[str]:
    """Take out of *user_key*'s own node libraries each copy of a library the
    account's packages declare that hides the image's copy where the image's
    meets every range they declare it at, and that the tree's other libraries
    need at no other version: an earlier start or add put it there, and in
    front of the image's it gave the account another torch than the image's
    CUDA one. A library the account's own list names stays, as the account's
    own choice, and every one stays when a package of the account's cannot be
    read. Its own requirements stay in the tree, as ``pip uninstall`` leaves
    them. The names taken out, sorted.

    A lock owner (memo dev/99): the account's store is walked under its seed
    lock, as :func:`not_asked_for` walks it, and the lock covers the walk
    alone, never the removal after it."""
    if not packages_backend_runtime.per_user_node_envs():
        return []
    overlay = packages_backend_runtime.user_node_overlay_dir(user_key)
    if not overlay.is_dir():
        return []
    declared: dict[str, list[str]] = {}
    with package_seed_lock(user_key, shared=True):  # memo dev/99: one consistent walk
        for package_path in list_user_packages(user_key):
            try:
                manifest = load_package_manifest(package_path)
            except (ManifestError, OSError):
                return []
            for name, spec in (manifest.python_deps or {}).items():
                # By PEP 503 name: two packages may spell one library apart.
                declared.setdefault(_canonical(name), []).append(spec)
    if not declared:
        return []
    own = [split_lib_spec(spec)[0] for spec in _load_raw(user_key)["python"]]
    with target_lock(user_key, packages_provisioning.NODE_OVERLAY_LOCK):
        with packages_pip_runner.holding_tree(overlay):
            names = packages_pip_runner.copies_this_interpreter_meets(declared, str(overlay), keep=own)
            if names:
                packages_pip_runner.uninstall_python_deps_from_target(names, str(overlay))
    if names:
        log.info("Took %s out of account %s's node libraries: the image's copies meet every range", names, user_key)
    return names


def give_way_after_a_removal(user_key: str) -> list[str]:
    """:func:`give_way_to_the_image` after a removal: of a package, from its
    last dataflow (``prune.py``) or from the account (``store_install``), or
    of a library in Installed libraries (:func:`remove_standalone_library`).
    A library another package of the account's still asks for stays, and its
    copy in the account's tree, which the removed package or list entry put
    there, goes where the image's copy meets every range left, as the next
    start would take it. The removal is done already, so a failure is logged
    and the next start gives way instead. The names taken out, sorted."""
    try:
        return give_way_to_the_image(user_key)
    except (PipInstallError, OSError) as exc:
        log.warning("Account %s's node libraries could not give way to the image after a removal: %s",
                    user_key, exc)
        return []


def accounts() -> list[str]:
    """The key of each account with a folder of its own under the users' base."""
    base = _users_base()
    if not base.is_dir():
        return []
    keys: list[str] = []
    for entry in sorted(base.iterdir()):
        if not entry.is_dir():
            continue
        try:
            keys.append(_user_key_segment(entry.name))
        except ValueError:
            continue  # a folder no account is keyed by
    return keys


def not_asked_for(user_keys, names) -> list[str]:
    """The names among *names* that none of the accounts *user_keys* asks
    for, sorted: no package in their stores declares one, and none is on
    their own lists (this dialog's). Empty when a package of theirs cannot be
    read, since it may declare any of them.

    A lock owner (memo dev/99): each account's store is walked under that
    account's seed lock, one account at a time. A package replaced in place is
    missing from the store between the installer's rmtree and its move, which
    run under the same lock, and a walk inside that window would give up a
    library the package declares. The lock covers the walk alone, never the
    uninstall a caller runs after it (``locks.package_seed_lock`` is a leaf).
    """
    asked: set[str] = set()
    for user_key in user_keys:
        with package_seed_lock(user_key, shared=True):  # memo dev/99: one consistent walk
            for package_path in list_user_packages(user_key):
                try:
                    m = load_package_manifest(package_path)
                except (ManifestError, OSError):
                    return []
                asked.update(_canonical(lib) for lib in (m.python_deps or {}))
        asked.update(
            _canonical(split_lib_spec(spec)[0]) for spec in _load_raw(user_key)["python"]
        )
    return sorted({name for name in names if _canonical(name) not in asked})


def user_library_import_failure(user_key: str, name: str):
    """Why *name* cannot be imported by *user_key*'s nodes, or None.

    pip exiting 0 does not mean the library works, and asking the wrong
    environment is its own way of being wrong: under isolation the host
    interpreter has never heard of a library that installed perfectly well into
    the user's tree, and reporting that as a broken install would be a
    fabricated failure.
    """
    if packages_backend_runtime.per_user_node_envs():
        return packages_provisioning.node_overlay_import_failures(user_key, [name]).get(name)
    return packages_pip_runner.import_failures([name]).get(name)


def add_standalone_library(user_key: str, kind: str, spec: str) -> dict:
    """Append a standalone library to the user's list and pip-install it.

    ``spec`` is a pip-install argv entry (``numpy``, ``scikit-learn==1.4.0``);
    the pip_runner re-canonicalizes the version. ``PipSpecError`` /
    ``PipInstallError`` propagate for the route to answer. pip exiting 0 does
    not mean the library works, and "skipped" means only that the metadata was
    already satisfied - a wheel whose native extension cannot load reports a
    good version, so pip declines to do anything and this used to answer
    "Already installed" for a library that raises ImportError the moment a node
    touches it. ``importError`` says so instead.
    """
    name, version = split_lib_spec(spec)
    report = install_user_library(user_key, name, version)
    add_library(user_key, kind, spec)
    import_error = user_library_import_failure(user_key, name)
    return {
        "standalone": list_standalone(user_key),
        # ``skipped`` is non-empty when pip found the requirement already
        # satisfied - the frontend reads this to show "Already installed"
        # instead of "Installed" so the user knows nothing was downloaded.
        "installed": list(report.installed),
        "skipped": list(report.skipped),
        # Present only when the library cannot actually be imported. The
        # frontend must treat this as a failure however the two lists read.
        "importError": import_error,
    }


def remove_standalone_library(user_key: str, kind: str, spec: str) -> dict:
    """Drop a standalone library and pip-uninstall it, as a package's removal
    takes its libraries back (:func:`names_to_take_back`): only when nothing
    else still asks for it, a package or a list, and only what Curio put
    there. Under per-user node environments only the account's own packages
    and list count: another user's list describes another user's tree, so
    asking it would refuse to remove a library from yours because someone
    else installed it in theirs. Without them, one interpreter serves every
    account, so every account's packages and lists count (#309), and a
    library this server's pip did not install, such as one the dialog found
    already installed, stays. A library a package still asks for stays, and
    under per-user node environments its copy in the account's tree goes
    where the image's meets every range left (:func:`give_way_after_a_removal`)."""
    name, _ = split_lib_spec(spec)
    # A malformed name escaped the pip error below and read as a 500 before
    # #309; the route maps PipSpecError to a 400.
    packages_pip_runner.validate_python_requirement(name)
    # Off the list first: the list is one of what asks for the library.
    remove_library(user_key, kind, spec)
    if name in names_to_take_back(user_key, [name]):
        try:
            uninstall_user_library(user_key, name)
        except PipInstallError as exc:
            log.warning("library remove: pip uninstall %s failed: %s", name, exc)
    give_way_after_a_removal(user_key)
    return {"standalone": list_standalone(user_key)}
