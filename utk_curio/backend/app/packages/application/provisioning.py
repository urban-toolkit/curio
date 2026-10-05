"""Dependency provisioning for an installed package: pip-install what the manifest declares, route it host/overlay by the runtime's single rule, and report whether it imports.

Application layer of the packages package (memo dev/143, B2): cut from ``services.py``
by responsibility; every function keeps its name and body. Sibling modules are reached
module-qualified (``packages_<module>.name``) so a test that patches the owner is seen by
every caller, and import order between siblings cannot matter.
"""

from __future__ import annotations

import logging
import sys
from dataclasses import (
    dataclass,
    field,
)

from flask import g, has_request_context

from utk_curio.backend.app.users.capabilities import package_install_refusal
from utk_curio.backend.app.packages.infrastructure import (
    backend_runtime as packages_backend_runtime,
    pip_runner as packages_pip_runner,
)
from utk_curio.backend.app.packages.infrastructure.pip_runner import (
    PipInstallError,
    PipSpecError,
)
from utk_curio.backend.app.packages.application import store_reads as packages_store_reads
from utk_curio.backend.app.packages.domain.errors import PackageServiceError

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class InstallOutcome:
    """What an install actually accomplished — every field a separate question.

    ``copied``        — were the package's files copied into the user store.
    ``installed``     — HOST distribution names pip installed or changed (the
                        dev/92 restart signal; overlay writes never split-brain
                        a running worker, so they stay out of it).
    ``import_errors`` — ``{distribution: reason}`` for a declared library that
                        pip counts as satisfied and that cannot in fact be
                        imported.

    The last one exists because pip exiting 0 is not the library working. A
    wheel whose native extension cannot load records a perfectly good version,
    so ``_is_satisfied`` says yes, pip reports "already satisfied" and changes
    nothing, and every layer above reads that as success — until a node runs
    and raises. Answering it HERE, at the one seam every install path funnels
    through, is what stops the next route from having to remember to ask.
    """

    copied: bool = False
    installed: list[str] = field(default_factory=list)
    import_errors: dict[str, str] = field(default_factory=dict)


def _import_failures_or_silence(deps, overlay_dir=None) -> dict[str, str]:
    """The import probe with its own failure demoted to silence.

    A probe is a diagnostic. The install it reports on already happened, so
    letting the diagnostic's own crash fail the request would be the tail
    wagging the dog — and would turn an environment without subprocesses into
    an environment without installs.
    """
    if not deps:
        return {}
    try:
        if overlay_dir is not None:
            return packages_pip_runner.import_failures_in(deps, str(overlay_dir))
        return packages_pip_runner.import_failures(deps)
    except Exception:  # noqa: BLE001 — a probe failure must not fail the install
        log.warning("import probe failed for %s", sorted(deps), exc_info=True)
        return {}


def _declared_import_failures(
    user_key: str, dir_name: str, manifest=None,
) -> dict[str, str]:
    """``{distribution: reason}`` for *dir_name*'s declared python deps that
    cannot be imported — asked in whichever environment they were installed to.

    Routed by the SAME rule that decided where they went
    (:func:`backend_runtime.dep_destinations`), because the two answers have to
    agree: probing the host for an overlay-only dep would report every one of
    them "not installed", which is a fabricated failure, and probing only the
    host for a backend-bearing package would vouch for libraries nobody checked.

    An overlay that was never built is REPORTED, not probed: reaching that
    branch means the manifest declares these deps and routes them to an overlay,
    so a missing directory is precisely the state in which the package's
    handlers cannot import them. Probing it would report the same thing less
    clearly; staying quiet would be a clean bill of health nobody earned.

    Empty when nothing is declared: the probe costs a subprocess and ~19s of
    cold imports for the twelve builtin data-ops libraries, so it is never run
    speculatively. Repeat HOST probes within a process are memoised per
    ``(distribution, version)`` by :mod:`.pip_runner`; the OVERLAY probe is not
    — ``build_overlay`` wipes and rebuilds, so a repair can land without a
    version moving and a memo would answer from before it. A backend-bearing
    package therefore re-pays the subprocess on every call that reaches here.
    """
    if manifest is None:
        manifest = packages_store_reads._read_manifest(user_key, dir_name)
    if manifest is None:
        return {}
    deps = dict(manifest.python_deps or {})
    if not deps:
        return {}

    destination, _reason = packages_backend_runtime.dep_destinations(manifest)
    failures: dict[str, str] = {}
    if destination in ("overlay", "both"):
        overlay = packages_backend_runtime.overlay_dir_for(user_key, dir_name)
        if overlay.is_dir():
            failures.update(_import_failures_or_silence(deps, overlay_dir=overlay))
        else:
            # An overlay that was never built is a REPORTABLE failure, not a
            # silence. Reaching here means the manifest routes these deps to an
            # overlay and declares them, so a missing directory is exactly the
            # state where the package's handlers cannot import what they need -
            # the thing this seam exists to name. It happens: an offline
            # sideload builds the overlay, pip fails, and ``build_overlay``
            # rmtree's the half-build on the way out.
            #
            # Saying nothing here was the earlier choice, on the grounds that a
            # directory nothing wrote to has nothing to answer for. That is the
            # wrong way round: it is a clean bill of health nobody earned, on
            # the one shape where the libraries are hardest to reach.
            failures.update({
                name: f"{name} is not installed (this package's dependency "
                      f"overlay has not been built)"
                for name in sorted(deps)
            })
    if destination in ("host", "both"):
        # Host last, deliberately: for a "both" package a broken host copy is
        # the one the user can repair with a plain pip, so it is the reason
        # worth surfacing when both environments are broken.
        failures.update(_import_failures_or_silence(deps))
    return failures


def _overlay_import_failures(user_key: str, dir_name: str, deps):
    """The overlay's verdict on *deps*, or ``None`` when there is no overlay.

    ``None`` and ``{}`` are different answers and the caller needs both: nothing
    built yet (so build it) versus built and working (so leave it alone). A
    rebuild costs a full ``pip install --target`` and wipes first, so a working
    overlay must not be rebuilt just because someone asked again.

    Returned rather than reduced to a bool because the caller needs this exact
    verdict anyway — asking twice means two subprocesses of cold imports for one
    install, and the overlay probe is deliberately unmemoised.

    A probe that cannot run answers ``{}``: the overlay is left alone, and the
    diagnostic's own failure does not turn into destructive action.
    """
    overlay = packages_backend_runtime.overlay_dir_for(user_key, dir_name)
    if not overlay.is_dir():
        return None
    return _import_failures_or_silence(deps, overlay_dir=overlay)


#: ``target_locks`` name for a user's node overlay. An install and a delete
#: both rewrite one tree, so they take the same lock rather than racing.
NODE_OVERLAY_LOCK = "_node-overlay"


def _provision_user_node_deps(
    user_key: str, py_deps: dict, failures: dict,
) -> list[str]:
    """Install *py_deps* into *user_key*'s node overlay; report what broke.

    Incremental, unlike the per-package handler overlay: that one is derived
    state rebuilt from one manifest, so wiping it is cheap and correct. This
    tree is the sum of everything a user has installed, and wiping it to add
    one library would re-run pip over their whole environment - and leave them
    with nothing at all if that run failed offline.

    So the probe decides the work: only names that cannot already be imported
    from the tree are handed to pip. That is also what keeps a re-install of an
    already-satisfied package from making pip rewrite a tree it is happy with.
    """
    overlay = packages_backend_runtime.user_node_overlay_dir(user_key)
    overlay.mkdir(parents=True, exist_ok=True)
    before = node_overlay_import_failures(user_key, py_deps)
    missing = {name: spec for name, spec in py_deps.items() if name in before}
    installed: list[str] = []
    if missing:
        report = packages_pip_runner.install_python_deps_to_target(missing, str(overlay))
        installed = sorted(report.installed)
    failures.update(node_overlay_import_failures(user_key, py_deps))
    return installed


def node_overlay_import_failures(user_key: str, deps) -> dict[str, str]:
    """The user's node overlay's verdict on *deps*.

    Probed with THIS process's interpreter, not ``sandbox_interpreter()``: the
    consumer of a node overlay is the sandbox, which the launcher starts with
    the interpreter the backend is running under. ``CURIO_BACKEND_SANDBOX_PYTHON``
    pins the handler-worker interpreter, and following it here would answer for
    one that never imports this tree.
    """
    if not deps:
        return {}
    overlay = packages_backend_runtime.user_node_overlay_dir(user_key)
    if not overlay.is_dir():
        return {name: "not installed" for name in deps}
    try:
        return packages_pip_runner.import_failures_in(deps, str(overlay), sys.executable)
    except Exception:  # noqa: BLE001 - a probe failure must not fail the install
        log.warning("node overlay probe failed for %s", sorted(deps), exc_info=True)
        return {}


def assert_may_install() -> None:
    """Refuse the caller if this instance must not install packages for them (#332).

    Called before anything lands in the store: by every use case that copies a
    package in (:func:`_ensure_user_store_install`, ``install_to_store``,
    ``install_from_catalog``, ``install_draft``, ``promote``) and by the upload
    route, and again by :func:`provision_declared_deps`. Not from
    :func:`provision_python_deps`: by then the files are installed, so a refusal
    there leaves the package behind for the next request to find (#451).

    The caller comes from the request context rather than a parameter, because
    the functions here take a ``user_key`` string and the predicate needs the
    account. Outside a request there is no user, which is the launcher
    installing manifests at boot, and ``package_install_refusal(None)`` passes
    that deliberately.
    """
    user = getattr(g, "user", None) if has_request_context() else None
    refusal = package_install_refusal(user)
    if refusal:
        raise PackageServiceError(refusal, 403)


def provision_python_deps(user_key: str, dir_name: str, manifest) -> InstallOutcome:
    """pip-install *manifest*'s declared python deps, then check they IMPORT.

    The ONE dependency step. Routing is
    :func:`backend_runtime.dep_destinations`'s single rule — overlay for
    backend-bearing packages, host when warm-sandbox python templates coexist —
    and the probe follows the deps to wherever they landed.

    Raises :class:`~.pip_runner.PipInstallError` /
    :class:`~.backend_runtime.BackendRuntimeError` on a real pip failure; the
    caller decides whether that rolls anything back. A library that installed
    and cannot be imported is NOT a failure here: the package installed fine,
    the environment is broken, and the repair (a matching GDAL, a conda-forge
    build) is the user's. Report, do not undo.
    """
    py_deps = dict(manifest.python_deps or {})
    if not py_deps:
        return InstallOutcome()

    destination, _reason = packages_backend_runtime.dep_destinations(manifest)
    host_installed: list[str] = []
    failures: dict[str, str] = {}
    if destination in ("overlay", "both"):
        # Build only when there is something to build. ``build_overlay`` is
        # wipe-and-rebuild by design — right for a first build or a repair, and
        # wrong as the answer to "someone asked again". It is asked again a
        # lot: ``/workflow-deps/check`` decides what a dataflow needs from HOST
        # metadata, so an overlay-only package reads as missing on every open,
        # and rebuilding there deletes a working overlay and re-runs pip over
        # the network. Offline that is not merely slow: the wipe happens first,
        # so a failed rebuild leaves the package with no overlay at all.
        verdict = _overlay_import_failures(user_key, dir_name, py_deps)
        if verdict is None or verdict:
            packages_backend_runtime.build_overlay(user_key, dir_name, py_deps)
            verdict = _overlay_import_failures(user_key, dir_name, py_deps) or {}
        failures.update(verdict)
    if destination in ("host", "both"):
        # "host" names the environment NODE code runs in, and #332 moved where
        # that is. Under fork isolation a node runs in a forked child that
        # can be given its own sys.path, so the deps go to the calling user's
        # own tree and stop being importable by everybody. Without isolation
        # there is one warm worker with one sys.modules and nothing to scope
        # into, so this stays the shared interpreter exactly as before.
        if packages_backend_runtime.per_user_node_envs():
            host_installed = _provision_user_node_deps(user_key, py_deps, failures)
        else:
            pip_report = packages_pip_runner.install_python_deps(py_deps)
            host_installed = sorted(pip_report.installed)
            # Host last, deliberately: for a "both" package a broken host copy
            # is the one the user can repair with a plain pip, so it is the
            # reason worth surfacing when both environments are broken.
            failures.update(_import_failures_or_silence(py_deps))
    # Deliberately NOT _declared_import_failures: it would route and probe all
    # over again, and the overlay half is unmemoised, so a healthy overlay paid
    # two full cold-import subprocesses for one install.
    return InstallOutcome(installed=host_installed, import_errors=failures)


def provision_declared_deps(user_key: str, dir_name: str, manifest) -> dict:
    """Install a just-installed package's declared python deps and report, for
    the paths where the package FILES land first and cannot be taken back.

    A sideloaded ``.curio.zip``, the wizard's "Save and install" and "Reload
    from catalog" all wrote the package before anything looked at its
    dependencies — and until this existed, nothing ever did. The sharpest case
    is the wizard: :func:`factory._apply_detected_dependencies` DERIVES
    ``dependencies.python`` from the node's source, so a node body containing
    ``import rasterio`` produced a rasterio declaration that no pip run
    installed and no probe questioned, and the package reported clean until it
    ran.

    A pip failure here is reported, not raised. The files are installed either
    way, so a 502 would describe neither outcome, and discarding a package the
    user just authored or uploaded to punish an unreachable index is a worse
    answer than saying which library did not arrive.

    Returns the additive response fields — ``importErrors`` always,
    ``dependencyError`` when pip itself failed, ``restartRecommended`` when pip
    changed a shared library under the running server.
    """
    assert_may_install()

    try:
        outcome = provision_python_deps(user_key, dir_name, manifest)
    # PipSpecError is NOT a PipInstallError, and a manifest is not a form field:
    # a declaration pip's grammar rejects (``">= 1.26"``, a private module the
    # factory derived from a node body) used to escape as a 500 AFTER the
    # package files were written. The files are installed either way on these
    # paths, so the honest answer is the same one a failed pip gets - name the
    # declaration that could not be satisfied and let the 201 stand.
    except (PipInstallError, PipSpecError,
            packages_backend_runtime.BackendRuntimeError) as exc:
        log.warning("dependency install failed for %s: %s", dir_name, exc)
        return {
            "dependencyError": str(exc),
            # Still worth probing: pip can fail on one dep having installed the
            # rest, and naming the ones that are actually unusable is more use
            # than pip's tail alone.
            "importErrors": _declared_import_failures(user_key, dir_name, manifest),
        }
    fields: dict = {"importErrors": outcome.import_errors}
    if outcome.installed:
        fields["restartRecommended"] = {"libs": outcome.installed}
    return fields
