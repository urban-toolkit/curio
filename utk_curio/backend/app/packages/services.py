"""Per-project package install / uninstall orchestration.

These services own the three-layer write protocol described in
[docs/NODE-CATALOG.md]:

  1. Shared catalog (read-only here)         — ``<repo_root>/packages/``
  2. Per-user package store (implementations) — ``.curio/users/<u>/packages/``
  3. Per-user defaults (auto-seed list)       — ``.curio/users/<u>/default-packages.json``
  4. Per-project lockfile (source of truth)   — ``spec.trill.json``

Every public function in this module touches at least #4 (the lockfile).
Install paths also touch #2 (and #3 when called via "add to defaults").
Uninstall paths touch #4, then run :func:`prune_unreferenced_packages`
which may touch #2 and #3.

The catalog source (#1) is read-only via :func:`catalog_root`; writes
land there only through ``factory/publish-catalog`` in
[routes.py](routes.py), which is gated by
``CURIO_ALLOW_FACTORY_CATALOG_PUBLISH``.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from utk_curio.backend.app.packages import defaults as defaults_io
from utk_curio.backend.app.packages.locks import package_seed_lock
from utk_curio.backend.app.packages.installer import (
    InstallerError,
    install_packageage_from_directory,
    uninstall_packageage,
)
from utk_curio.backend.app.packages.seed import BUILTIN_PACKAGE_ID
from utk_curio.backend.app.packages.spec_packages import (
    project_packages,
    referencing_nodes,
    set_project_packages,
)
from utk_curio.backend.app.packages.storage import (
    PACKAGE_DIR_RE,
    PackageIdError,
    list_user_packageages,
    package_dir,
    user_packageages_dir,
)
from utk_curio.backend.app.projects import repositories as projects_repo
from utk_curio.backend.app.projects import storage as projects_storage

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

def catalog_root() -> Path:
    """Return ``<repo_root>/packages/`` — the source of catalog installs.

    Duplicates the helpers in [routes.py](routes.py) and [seed.py](seed.py)
    so this module doesn't depend on Flask's request-scoped imports. A
    future cleanup can centralise these three copies in one place.
    """
    # services.py -> packages/ -> app/ -> backend/ -> utk_curio/ -> repo_root/packages/
    return Path(__file__).resolve().parents[4] / "packages"


class PackageServiceError(Exception):
    """Raised for caller-facing package-service errors (bad input, not-found)."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


# ---------------------------------------------------------------------------
# User-store helpers
# ---------------------------------------------------------------------------

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
    base = user_packageages_dir(user_key)
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
    from utk_curio.backend.app.packages import pip_runner

    if not deps:
        return {}
    try:
        if overlay_dir is not None:
            return pip_runner.import_failures_in(deps, str(overlay_dir))
        return pip_runner.import_failures(deps)
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

    An overlay that was never built is not probed. The question here is "does
    what we installed work"; a directory nothing wrote to has nothing to answer
    for, and the install paths that used to skip building it are fixed rather
    than reported on.

    Empty when nothing is declared: the probe costs a subprocess and ~19s of
    cold imports for the twelve builtin data-ops libraries, so it is never run
    speculatively. Repeat calls within a process are memoised per
    ``(distribution, version)`` by :mod:`.pip_runner`.
    """
    from utk_curio.backend.app.packages import backend_runtime

    if manifest is None:
        manifest = _read_manifest(user_key, dir_name)
    if manifest is None:
        return {}
    deps = dict(manifest.python_deps or {})
    if not deps:
        return {}

    destination, _reason = backend_runtime.dep_destinations(manifest)
    failures: dict[str, str] = {}
    if destination in ("overlay", "both"):
        overlay = backend_runtime.overlay_dir_for(user_key, dir_name)
        if overlay.is_dir():
            failures.update(_import_failures_or_silence(deps, overlay_dir=overlay))
    if destination in ("host", "both"):
        # Host last, deliberately: for a "both" package a broken host copy is
        # the one the user can repair with a plain pip, so it is the reason
        # worth surfacing when both environments are broken.
        failures.update(_import_failures_or_silence(deps))
    return failures


def _overlay_needs_building(user_key: str, dir_name: str, deps) -> bool:
    """Is *dir_name*'s overlay absent, or present and not working?

    The question a rebuild should be conditioned on. An overlay that exists and
    whose every declared dep imports inside it is finished work: rebuilding it
    costs a full ``pip install --target`` and, because the build wipes first,
    risks losing it to an index that is not reachable right now.

    A probe that cannot run answers "no" — the overlay is left alone. That is
    the same posture the rest of the seam takes: a diagnostic's own failure
    must not turn into destructive action.
    """
    from utk_curio.backend.app.packages import backend_runtime

    overlay = backend_runtime.overlay_dir_for(user_key, dir_name)
    if not overlay.is_dir():
        return True
    return bool(_import_failures_or_silence(deps, overlay_dir=overlay))


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
    from utk_curio.backend.app.packages import backend_runtime
    from utk_curio.backend.app.packages.pip_runner import install_python_deps

    py_deps = dict(manifest.python_deps or {})
    if not py_deps:
        return InstallOutcome()

    destination, _reason = backend_runtime.dep_destinations(manifest)
    host_installed: list[str] = []
    if destination in ("overlay", "both"):
        # Only when there is something to build. ``build_overlay`` is
        # wipe-and-rebuild by design — right for a first build or a repair, and
        # wrong as the answer to "someone asked again". It is asked again a
        # lot: ``/workflow-deps/check`` decides what a dataflow needs from HOST
        # metadata, so an overlay-only package reads as missing on every open,
        # and rebuilding there deletes a working overlay and re-runs pip over
        # the network. Offline that is not merely slow: the wipe happens first,
        # so a failed rebuild leaves the package with no overlay at all.
        if _overlay_needs_building(user_key, dir_name, py_deps):
            backend_runtime.build_overlay(user_key, dir_name, py_deps)
    if destination in ("host", "both"):
        pip_report = install_python_deps(py_deps)
        host_installed = sorted(pip_report.installed)
    return InstallOutcome(
        installed=host_installed,
        import_errors=_declared_import_failures(user_key, dir_name, manifest),
    )


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
    from utk_curio.backend.app.packages import backend_runtime
    from utk_curio.backend.app.packages.pip_runner import PipInstallError, PipSpecError

    try:
        outcome = provision_python_deps(user_key, dir_name, manifest)
    # PipSpecError is NOT a PipInstallError, and a manifest is not a form field:
    # a declaration pip's grammar rejects (``">= 1.26"``, a private module the
    # factory derived from a node body) used to escape as a 500 AFTER the
    # package files were written. The files are installed either way on these
    # paths, so the honest answer is the same one a failed pip gets - name the
    # declaration that could not be satisfied and let the 201 stand.
    except (PipInstallError, PipSpecError,
            backend_runtime.BackendRuntimeError) as exc:
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


def _ensure_user_store_install(user_key: str, dir_name: str) -> InstallOutcome:
    """Copy *dir_name* from the shared catalog when it is missing, install the
    python deps its manifest declares, and report whether they import.

    The pip step runs synchronously inside the request — heavy installs like
    ``torch`` can take many minutes (see :mod:`.pip_runner`). The Install button
    stays in its busy state for the whole duration. If pip fails the catalog
    copy is rolled back so a retry can re-attempt cleanly.

    Already-installed is answered, not skipped: the caller's real question is
    "can the user use this package now", and a package that has sat in the store
    for a week can have had its library broken under it since. Costs one memo
    lookup after the first probe in the process.
    """
    if _is_installed_in_user_store(user_key, dir_name):
        return InstallOutcome(
            copied=False,
            import_errors=_declared_import_failures(user_key, dir_name),
        )
    src = catalog_root() / dir_name
    if not src.is_dir():
        raise PackageServiceError(
            f"catalog has no package {dir_name}", 404,
        )
    try:
        result = install_packageage_from_directory(user_key, src, replace=False)
    except InstallerError as exc:
        raise PackageServiceError(str(exc)) from exc

    # memo dev/91: the catalog path is an install authority too — pin (or
    # clear) the backend entry digest so promote-less installs stay
    # verifiable and a reinstall never trips a stale pin.
    from utk_curio.backend.app.packages import backend_runtime
    from utk_curio.backend.app.packages.pip_runner import PipInstallError

    backend_runtime.record_entry_pin(user_key, dir_name)

    try:
        outcome = provision_python_deps(user_key, dir_name, result.manifest)
    except (PipInstallError, backend_runtime.BackendRuntimeError) as exc:
        # Roll the just-installed files back so the user-store doesn't show a
        # package that's unusable. Best-effort: log + continue on cleanup
        # failure (the original error is the one we surface).
        #
        # Reserved for pip actually failing. A library that installed and
        # cannot be imported never reaches here — undoing the install over an
        # environment problem the user has to fix anyway would only take away
        # the package that named the problem.
        try:
            import shutil
            from utk_curio.backend.app.packages.storage import package_dir
            shutil.rmtree(package_dir(user_key, dir_name), ignore_errors=True)
            backend_runtime.remove_backend_residue(user_key, dir_name)
        except Exception:  # noqa: BLE001
            log.warning("Failed to roll back %s after dep failure", dir_name, exc_info=True)
        raise PackageServiceError(
            f"package files installed but its dependencies failed: {exc}",
        ) from exc
    return InstallOutcome(
        copied=True,
        installed=outcome.installed,
        import_errors=outcome.import_errors,
    )


def ensure_user_packages_initialized(user_key: str) -> None:
    """Idempotently seed the per-user package store with ``curio.builtin``.

    The startup seeder in ``app/__init__.py`` only runs for the shared
    ``guest`` user, so the first time a real authenticated user touches the
    package system, their store is empty and the palette would be missing
    even the built-in nodes. Call this at the project-entry boundaries
    (save_project, load_project) so the user always has builtin available
    by the time the canvas mounts.

    Safe to call repeatedly: :func:`seed_dev_packageages` consults the
    per-user marker file and only re-seeds when fixtures have actually
    moved.
    """
    from utk_curio.backend.app.packages.seed import seed_dev_packageages

    try:
        seed_dev_packageages(user_key=user_key)
    except Exception:  # noqa: BLE001 — seeding must never block a project request
        log.warning("Builtin seed failed for user_key=%s", user_key, exc_info=True)


# ---------------------------------------------------------------------------
# Project lockfile read/write
# ---------------------------------------------------------------------------

def get_project_lockfile(user_key: str, project_id: str) -> set[str]:
    """Read the project's declared package dirNames (with backfill for legacy specs)."""
    spec = projects_storage.read_spec(user_key, project_id)
    if spec is None:
        raise PackageServiceError(f"project {project_id} has no spec", 404)
    return project_packages(spec, _installed_majors_by_pkg(user_key))


# DEC-051 (dev/67-3): where a template's DECLARED cardinality and its RENDERED
# input capacity disagree, the rendered capacity is the enforceable truth —
# merge-flow declares one "[1,n]" port but the canvas renders exactly 5 slots
# (mergeFlowBehavior MERGE_SLOT_COUNT), so 5 is what a graph can actually hold.
_RENDERED_INPUT_CAPACITY: dict[str, int] = {"curio.builtin/merge-flow": 5}


def _input_arity(canonical: str, template) -> tuple[list[dict], int]:
    """Per-port ``{types, min, max}`` rows + the template's incoming-edge
    capacity.

    ``inputs`` carries the DECLARED cardinalities (parsed to min/max) as
    metadata. ``maxIncomingEdges`` is the RENDERED truth the canvas actually
    implements: one edge per rendered input handle — handles are 1:1 with
    ports, and each holds a single scalar ``data.input`` (a second edge
    silently overwrites it) — with merge-flow's slot machinery the sole
    multi-edge surface (5 slots). Declared ``[1,n]`` maxima (e.g.
    computation-analysis) are aspirational: the input plumbing is scalar per
    handle, so they are NOT enforceable capacity (DEC-051).
    """
    from utk_curio.backend.app.packages.manifest import parse_cardinality

    inputs: list[dict] = []
    for port in template.input_ports:
        lo, hi = parse_cardinality(port.cardinality)
        inputs.append({"types": list(port.types), "min": lo, "max": hi})
    max_incoming = _RENDERED_INPUT_CAPACITY.get(canonical, len(inputs))
    return inputs, max_incoming


# One value, three legal spellings (memo dev/93 D3; the dev/90 A14 family).
# The canonical form is UNVERSIONED ``<packageId>/<templateId>`` — what
# ``available_templates`` returns and what a spec pins — but the ecosystem
# hands models the other two constantly: the client registry keys descriptors
# VERSIONED (``<packageId>/<templateId>@<major>``, so the run context, the
# canvas graph, and the runtime's own proposal previews all speak it), and
# legacy trill files carry the pre-package ENUM names (``DATA_LOADING``).
# A model quoting an id from its own context must never be refused for
# quoting it in a spelling the system itself produced.
_VERSIONED_TEMPLATE_RE = re.compile(r"^(?P<base>.+/.+)@(?P<major>0|[1-9][0-9]{0,3})$")
_LEGACY_ENUM_RE = re.compile(r"^[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)*$")


def canonical_template_id(node_type: object) -> str:
    """Any legal spelling of a node type → the canonical unversioned id.

    Shape only: no filesystem access, no availability check — availability is
    :func:`resolve_template`'s job, and keeping this pure lets it run at the
    parse boundary where a plan is first read.

    The legacy enum names are DERIVED rather than tabulated: every member of
    the frontend's ``NodeType`` enum is its template id upper-snake-cased
    (``DATA_LOADING`` ↔ ``curio.builtin/data-loading``), so the rule cannot
    drift out of sync with a hand-maintained list the way a table would, and
    it covers built-in templates that never got an enum member (spatial-join)
    for free. A bogus ALL-CAPS token maps to a canonical id that simply is not
    available, which refuses with the ordinary message.

    Anything unrecognised is returned unchanged — including a bare
    ``data-loading`` with no package id, which stays ambiguous on purpose, and
    a case variant, since template ids are case-sensitive by contract.
    """
    if not isinstance(node_type, str):
        return ""
    text = node_type.strip()
    if not text:
        return ""
    versioned = _VERSIONED_TEMPLATE_RE.match(text)
    if versioned:
        return versioned.group("base")
    if "/" not in text and _LEGACY_ENUM_RE.match(text):
        return f"{BUILTIN_PACKAGE_ID}/{text.lower().replace('_', '-')}"
    return text


def resolve_template(
    user_key: str,
    project_id: str,
    node_type: object,
    *,
    require_authorable: bool = False,
) -> tuple[dict | None, str]:
    """The ONE availability gate for a node type (memo dev/93 D3).

    Accepts every spelling :func:`canonical_template_id` knows and returns
    ``(entry | None, error_text)``, where ``entry`` is the
    :func:`available_templates` row — so the caller pins the canonical id, not
    whatever the model typed. Plans and ``node.create`` share this so they can
    no longer disagree about what a template id is: before this, a plan naming
    ``curio.builtin/data-loading@1`` was refused while ``node.create`` accepted
    the very same string, and the model — quoting an id its own prompt had
    given it — had no way to tell which spelling any given tool wanted.

    ``require_authorable`` is the one intended difference between the callers
    and is therefore explicit at both: ``node.create`` writes content, so it
    needs a template that holds authored content; a PLAN places a typed
    placeholder whose content arrives later from Solve, so it does not.

    A degraded registry is reported as such rather than blamed on the id: an
    unreadable package store used to surface as "that template is not
    available", which is how a corrupted install (dev/93 D1) reached a model
    as its own mistake.
    """
    return resolve_templates(
        user_key, project_id, [node_type], require_authorable=require_authorable,
    )[0]


def resolve_templates(
    user_key: str,
    project_id: str,
    node_types: list,
    *,
    require_authorable: bool = False,
) -> list[tuple[dict | None, str]]:
    """:func:`resolve_template` for many node types against ONE snapshot
    (memo dev/99 R1.2).

    Returns ``(entry | None, error_text)`` per input, positionally. The point
    is the snapshot, not the batching: a plan mint resolves every node it
    proposes, so resolving them one at a time re-walked the package store —
    and once readers hold the seed lock, re-acquired it — once per node. A
    12-node plan meant 13 walks and 13 acquisitions. Here the store is read
    once however many types are asked about, so the cost stops scaling with
    plan size and every node is judged against the same instant.
    """
    try:
        report = available_templates_report(user_key, project_id)
    except Exception as exc:  # unavailable registry is data, not a run error
        message = f"the node template registry is unavailable: {exc}"
        return [(None, message) for _ in node_types]
    by_id = {t["id"]: t for t in report["templates"]}
    out: list[tuple[dict | None, str]] = []
    for node_type in node_types:
        out.append(
            _resolve_one(node_type, by_id, report["skipped"], require_authorable)
        )
    return out


def _resolve_one(
    node_type: object,
    by_id: dict,
    skipped: list,
    require_authorable: bool,
) -> tuple[dict | None, str]:
    """One resolution against an existing availability snapshot. No I/O."""
    if not isinstance(node_type, str) or not node_type.strip():
        return None, "params.nodeType must be a non-empty template id string"
    entry = by_id.get(canonical_template_id(node_type))
    if entry is None:
        if skipped:
            unreadable = ", ".join(sorted(skipped))
            return None, (
                f"nodeType {node_type!r} is not available AND this project's "
                f"package store is degraded — {unreadable} could not be read, so "
                "templates it provides are missing from the list. Report this "
                "rather than choosing a different template"
            )
        return None, (
            f"nodeType {node_type!r} is not an available template for this project — "
            "choose an id from the Available node templates list (the versioned "
            "form '<packageId>/<templateId>@<major>' is also accepted)"
        )
    if require_authorable and not entry.get("authorable"):
        return None, (
            f"template {node_type!r} does not hold authored content — choose an "
            "authorable template from the Available node templates list"
        )
    return entry, ""


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
    from utk_curio.backend.app.packages.manifest import (
        ManifestError,
        load_packageage_manifest,
    )

    out: dict[str, object] = {}
    for path in list_user_packageages(user_key):
        try:
            out[path.name] = load_packageage_manifest(path)
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


def _lockfile_or_empty(user_key: str, project_id: str) -> set[str]:
    """The project's declared package dirNames, or empty when the project has
    no readable lockfile. A genuine (non-``PackageServiceError``) fault still
    propagates — the callers that swallow everything do so deliberately."""
    try:
        return set(get_project_lockfile(user_key, project_id))
    except PackageServiceError:
        return set()


def _template_entry(package_id: str, template) -> dict:
    """One roster row for a manifest template — the shape every template
    listing in this module returns (memo dev/48; arity per dev/67-3, DEC-051).
    """
    canonical = f"{package_id}/{template.template_id}"
    inputs, max_incoming = _input_arity(canonical, template)
    return {
        "id": canonical,
        "label": template.label,
        "description": template.description,
        # dev/90 A14: a PRESENTATION template (editor none + a custom
        # behavior — the dev/89 post-it profile) holds authorable CONTENT
        # (the note text its behavior renders) even though it has no code
        # editor; without this, reuse-first note creation was impossible by
        # construction (node.create refused every note template).
        "authorable": bool(
            template.has_code or template.has_grammar
            or (template.behavior and template.editor == "none")
        ),
        # dev/105 S1 (additive): a PRESENTATION template renders content
        # without code — the note profile. The roster tells a note-composing
        # agent when none of the available templates is one, so it never
        # reaches for a code template (or a canvas node's type) to hold a note.
        "presentation": bool(template.behavior and template.editor == "none"),
        "inputs": inputs,
        "maxIncomingEdges": max_incoming,
    }


def installed_templates_not_in_project(user_key: str, project_id: str) -> list[dict]:
    """Templates the user HAS installed that this project has not enlisted.

    The reuse-first counterpart to :func:`available_templates` (memo dev/93
    D4). Availability is *store ∩ project lockfile*, so a package the user
    already owns is invisible to a project whose lockfile omits it — and an
    agent told to "reuse an installed template" then concludes none exists
    and authors a duplicate package instead. This listing is what makes the
    distinction sayable: these templates exist and are one reviewed
    ``package.install`` away from being usable here.

    Each row is a :func:`_template_entry` plus ``dirName`` — the
    ``<packageId>@<major>`` a ``package.install`` proposal takes. Built-ins
    are excluded (always present, never proposable) and so is anything the
    lockfile already names.
    """
    wanted = _lockfile_or_empty(user_key, project_id)  # project-spec I/O: outside
    return _installed_templates_not_in_project_unlocked(
        wanted, _locked_store_index(user_key),
    )


def _installed_templates_not_in_project_unlocked(
    wanted: set[str], store: dict[str, object],
) -> list[dict]:
    """:func:`installed_templates_not_in_project` over an existing store
    snapshot (dev/99 R2). Takes no locks and performs no I/O."""
    out: list[dict] = []
    seen: set[str] = set()
    for dir_name in sorted(store):
        pkg_id = dir_name.split("@", 1)[0]
        if pkg_id == BUILTIN_PACKAGE_ID or dir_name in wanted:
            continue
        manifest = store[dir_name]
        if isinstance(manifest, Exception):
            continue
        for t in manifest.templates:
            entry = _template_entry(manifest.package_id, t)
            if entry["id"] in seen:
                continue
            seen.add(entry["id"])
            out.append({**entry, "dirName": dir_name})
    return sorted(out, key=lambda e: e["id"])


def available_templates(user_key: str, project_id: str) -> list[dict]:
    """The node templates a project may instantiate (memo dev/48).

    Scope = the seeded ``curio.builtin@<highest-major>`` store package (always
    present on every canvas) plus every package in the project's package
    lockfile. Each entry is ``{"id", "label", "description", "authorable",
    "inputs", "maxIncomingEdges"}`` (arity per dev/67-3, DEC-051) where
    ``id`` is the canonical UNVERSIONED ``<packageId>/<templateId>``
    node type the canvas stores in ``data.nodeType``. This is the single
    source of template knowledge for agent node creation (`ADR-AG-007`) —
    the agents module owns none of its own. Unreadable packages are skipped
    (they cannot provide working nodes); a project without a spec resolves
    to the builtin templates only.

    See :func:`available_templates_report` when the caller needs to know
    whether anything WAS skipped — silence about that is what let a
    truncated package store reach a model as "that template is not
    available" (memo dev/93 D2).
    """
    return available_templates_report(user_key, project_id)["templates"]


def available_templates_report(user_key: str, project_id: str) -> dict:
    """:func:`available_templates` plus what it could not read.

    ``{"templates": [...], "skipped": [dirName, ...]}``. The skip list exists
    because the bare ``except (ManifestError, OSError): continue`` this
    function is built on is silent by nature: a package whose manifest will
    not load simply vanishes from every roster, so a store that lost its
    built-in manifest looked identical to a project that legitimately has few
    templates — and the refusal three layers away blamed the node type. Each
    skip is also logged at WARNING; an unreadable installed package is an
    abnormal state, not routine.
    """
    wanted = _lockfile_or_empty(user_key, project_id)  # project-spec I/O: outside
    return _available_templates_report_unlocked(wanted, _locked_store_index(user_key))


def _available_templates_report_unlocked(
    wanted: set[str], store: dict[str, object],
) -> dict:
    """:func:`available_templates_report` over an existing store snapshot
    (dev/99 R2). Takes no locks and performs no I/O.

    The scope filter runs BEFORE the readability check, exactly as before: a
    package outside this project's scope is passed over silently and never
    reported as skipped, so the skip list keeps meaning "in scope for this
    project and unreadable".
    """
    out: list[dict] = []
    seen: set[str] = set()
    skipped: list[str] = []
    # Prefer the highest seeded builtin major when several exist.
    for dir_name in sorted(store, reverse=True):
        pkg_id = dir_name.split("@", 1)[0]
        if pkg_id != BUILTIN_PACKAGE_ID and dir_name not in wanted:
            continue
        manifest = store[dir_name]
        if isinstance(manifest, Exception):
            # Loud, because the consequence is invisible: every template this
            # package provides disappears from the roster (dev/93 D2).
            log.warning(
                "Package %s is installed but unreadable (%s) — its templates are "
                "missing from this project's roster",
                dir_name, manifest,
            )
            skipped.append(dir_name)
            continue
        for t in manifest.templates:
            entry = _template_entry(manifest.package_id, t)
            if entry["id"] in seen:
                continue
            seen.add(entry["id"])
            out.append(entry)
    return {
        "templates": sorted(out, key=lambda e: e["id"]),
        "skipped": sorted(skipped),
    }


def presentation_templates(user_key: str, project_id: str) -> list[dict]:
    """dev/95: the installed+enlisted PRESENTATION templates (a custom
    ``behavior`` + editor ``"none"`` — the dev/90 A14 profile whose content
    IS the note text its behavior renders).

    These are the note-surface candidates the runtime offers a delegated
    Researcher (a DEC-046 child cannot browse the roster itself); the child
    picks one by id and the mint re-validates through the ONE template
    vocabulary. Same enumeration and skip posture as
    :func:`available_templates_report` — an unreadable package stays loud
    there; here it simply contributes no candidates."""
    wanted = _lockfile_or_empty(user_key, project_id)  # project-spec I/O: outside
    return _presentation_templates_unlocked(wanted, _locked_store_index(user_key))


def _presentation_templates_unlocked(
    wanted: set[str], store: dict[str, object],
) -> list[dict]:
    """:func:`presentation_templates` over an existing store snapshot
    (dev/99 R2). Takes no locks and performs no I/O."""
    out: list[dict] = []
    seen: set[str] = set()
    for dir_name in sorted(store, reverse=True):
        pkg_id = dir_name.split("@", 1)[0]
        if pkg_id != BUILTIN_PACKAGE_ID and dir_name not in wanted:
            continue
        manifest = store[dir_name]
        if isinstance(manifest, Exception):
            continue  # available_templates_report already logs this loudly
        for t in manifest.templates:
            if not (t.behavior and t.editor == "none"):
                continue
            canonical = f"{manifest.package_id}/{t.template_id}"
            if canonical in seen:
                continue
            seen.add(canonical)
            out.append({
                "id": canonical,
                "label": t.label,
                "description": t.description,
            })
    return sorted(out, key=lambda e: e["id"])


# Agent-drafted packages (memo dev/48 §3.2b) are namespaced so they can never
# collide with the seeded builtin or a catalog publisher's id space.
AGENT_PACKAGE_NAMESPACE = "curio.agent"
_TEMPLATE_SLUG_MAX = 48


def template_slug(label: str) -> str:
    """A ``TEMPLATE_ID_RE``-safe slug from a human label (empty when nothing
    survives normalization)."""
    import re

    slug = re.sub(r"[^a-z0-9]+", "-", (label or "").lower()).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)[:_TEMPLATE_SLUG_MAX].strip("-")
    if slug and not slug[0].isalpha():
        slug = f"n-{slug}".rstrip("-")[:_TEMPLATE_SLUG_MAX]
    return slug


def create_template_package(user_key: str, project_id: str, template: dict) -> dict:
    """Register ONE agent-drafted node template through the EXISTING factory
    (memo dev/48 §3.2b — the reviewed creation fallback's apply half).

    Builds a single-template draft package (the same envelope the palette's
    Save-as flow produces), installs it to the user store via the factory's
    atomic staging, and adds it to *project_id*'s package lockfile. Returns
    the created template entry (``available_templates`` shape, plus
    ``packageDir``). Factory/installer validation failures raise
    :class:`PackageServiceError` with the verbatim message — nothing is ever
    half-registered (the factory stages atomically).
    """
    from utk_curio.backend.app.packages.factory import FactoryError, build_packageage_archive
    from utk_curio.backend.app.packages.installer import install_packageage_from_archive

    label = str(template.get("label") or "").strip()
    slug = template_slug(label)
    if not slug:
        raise PackageServiceError("template.label must yield a usable name", 400)
    engine = template.get("engine") or "python"
    description = str(template.get("description") or "").strip()
    code = template.get("content")
    if not isinstance(code, str) or not code.strip():
        raise PackageServiceError("template.content must be a non-empty string", 400)
    filename = f"{slug}.py" if engine == "python" else f"{slug}.js"
    package_id = f"{AGENT_PACKAGE_NAMESPACE}.{slug}"
    template_manifest = {
        "id": slug,
        "label": label,
        "category": str(template.get("category") or "computation"),
        "engine": engine,
        "editor": "code",
        "description": description,
        "inputPorts": template.get("inputPorts") or [],
        "outputPorts": template.get("outputPorts")
        or [{"types": ["JSON"], "cardinality": "1"}],
        "source": f"sources/{filename}",
        "badge": "AGENT",
    }
    draft = {
        "manifest": {
            "id": package_id,
            "version": "1.0.0",
            "name": label,
            "publisher": "Curio Agent",
            "description": description or f"Agent-drafted node type: {label}",
            "license": "MIT",
            "compatibility": {"curioRuntime": ">=0.5.0", "major": 1},
            "permissions": [],
            "dependencies": {"packages": {}, "python": {}, "js": {}},
            "templates": [template_manifest],
        },
        "sources": {slug: {"filename": filename, "code": code}},
    }
    try:
        built = build_packageage_archive(draft)
        install_packageage_from_archive(user_key, built.archive, replace=False)
    except (FactoryError, InstallerError) as exc:
        raise PackageServiceError(str(exc), 409) from exc
    dir_name = built.manifest.dir_name
    install_to_project(user_key, project_id, dir_name)
    return {
        "id": f"{package_id}/{slug}",
        "label": label,
        "description": description,
        "authorable": True,
        "packageDir": dir_name,
    }


def _write_lockfile(user_key: str, project_id: str, dirs: Iterable[str]) -> dict:
    # Hold the per-project spec lock across the read-modify-write so a concurrent
    # dataset mutation (replace_dataflow_datasets) or project save can't
    # clobber the package lockfile (or vice versa).
    with projects_storage.spec_write_lock(user_key, project_id):
        spec = projects_storage.read_spec(user_key, project_id)
        if spec is None:
            raise PackageServiceError(f"project {project_id} has no spec", 404)
        set_project_packages(spec, dirs)
        projects_storage.write_spec(user_key, project_id, spec)
        return spec


# ---------------------------------------------------------------------------
# Install/uninstall — per-project (drawer)
# ---------------------------------------------------------------------------

def install_to_store(user_key: str, dir_name: str) -> InstallOutcome:
    """Install *dir_name* into the user's package store (+ its python deps),
    without touching any project lockfile.

    Used by the workflow-deps auto-install: a freshly loaded/imported
    dataflow has no project to scope a lockfile to, but installing the
    owning package into the store is enough to make it show as installed
    (catalog drawer / libraries menu key off the store) and to provision
    its libraries + nodes. Raises :class:`PackageServiceError` on failure
    (catalog miss, pip failure); ``InstallOutcome.copied`` says whether a copy
    was performed, and ``.import_errors`` whether the libraries actually work.

    If the package is already in the store, its declared python deps are
    re-ensured (idempotent pip run) — this repairs the case where a lib was
    pip-uninstalled out from under an installed package. The repair routes by
    the same rule the original install did, so a backend-bearing package's
    overlay is rebuilt rather than its deps being quietly redirected at the
    host interpreter its handlers never import from.
    """
    if not PACKAGE_DIR_RE.match(dir_name):
        raise PackageServiceError(f"invalid dirName: {dir_name!r}")
    if not _is_installed_in_user_store(user_key, dir_name):
        return _ensure_user_store_install(user_key, dir_name)
    # Already in the store — repair any declared dep that isn't present.
    manifest = _read_manifest(user_key, dir_name)
    if manifest is None:
        return InstallOutcome()
    from utk_curio.backend.app.packages import backend_runtime
    from utk_curio.backend.app.packages.pip_runner import PipInstallError

    try:
        return provision_python_deps(user_key, dir_name, manifest)
    except (PipInstallError, backend_runtime.BackendRuntimeError) as exc:
        raise PackageServiceError(f"pip install failed: {exc}", 502) from exc


def install_to_project(
    user_key: str, project_id: str, dir_name: str,
) -> dict:
    """Add *dir_name* to *project_id*'s lockfile; install to user store if missing.

    Returns ``{"packages": [...], "addedToUserStore": bool, "importErrors":
    {lib: reason}}``, plus ``restartRecommended`` when pip actually changed a
    shared library under the running server.
    """
    if not PACKAGE_DIR_RE.match(dir_name):
        raise PackageServiceError(f"invalid dirName: {dir_name!r}")

    outcome = _ensure_user_store_install(user_key, dir_name)
    # dev/92 B-2: additive restart-honesty field — present exactly when pip
    # actually changed shared libraries under the running server.
    extra: dict = {}
    if outcome.installed:
        extra["restartRecommended"] = {"libs": outcome.installed}
    # The package arrived and one of its libraries does not work. pip counts
    # matching metadata as satisfaction, so this reads as a clean install right
    # up until a node touches the library; the response is the last place the
    # failure is still attached to the package that brought it in. Always
    # present, empty included — an absent key is how an OLD backend answers, and
    # "nothing is broken" is a different statement from "nobody looked".
    extra["importErrors"] = outcome.import_errors

    current = get_project_lockfile(user_key, project_id)
    if dir_name not in current:
        current.add(dir_name)
        _write_lockfile(user_key, project_id, current)
    return {
        "packages": sorted(current),
        "addedToUserStore": outcome.copied,
        **extra,
    }


def uninstall_from_project(
    user_key: str, project_id: str, dir_name: str,
) -> dict:
    """Drop *dir_name* from *project_id*'s lockfile and run the prune sweep.

    Returns ``{"packages": [...], "pruned": [...], "removedFromDefaults": [...]}``.
    """
    if not PACKAGE_DIR_RE.match(dir_name):
        raise PackageServiceError(f"invalid dirName: {dir_name!r}")
    if dir_name.startswith(f"{BUILTIN_PACKAGE_ID}@"):
        raise PackageServiceError(
            f"{BUILTIN_PACKAGE_ID} is built-in and cannot be uninstalled",
        )

    # memo dev/101: refuse while canvas nodes still use the package. The
    # backfill in ``project_packages`` would re-derive it from those nodes on
    # the next read, so a "successful" uninstall here was a permanent no-op
    # that reported success — the drawer showed the package installed again
    # on every reload with no explanation. Name the count instead.
    spec = projects_storage.read_spec(user_key, project_id)
    users = referencing_nodes(spec, dir_name, _installed_majors_by_pkg(user_key))
    if users:
        raise PackageServiceError(
            f"{len(users)} node{'s' if len(users) != 1 else ''} on this canvas "
            f"use{'s' if len(users) == 1 else ''} {dir_name} — delete "
            f"{'them' if len(users) != 1 else 'it'} first",
            409,
        )

    current = get_project_lockfile(user_key, project_id)
    if dir_name in current:
        current.discard(dir_name)
        _write_lockfile(user_key, project_id, current)

    prune = prune_unreferenced_packages(user_key, {dir_name})
    return {
        "packages": sorted(current),
        "pruned": sorted(prune["pruned"]),
        "removedFromDefaults": sorted(prune["removedFromDefaults"]),
    }


# ---------------------------------------------------------------------------
# Install — global (catalog page)
# ---------------------------------------------------------------------------

def uninstall_from_defaults(user, dir_name: str) -> dict:
    """Stop seeding *dir_name* into new projects.

    The mirror of :func:`install_to_defaults`, and the twin of
    ``datasets.application.mutations.remove_dataset_from_defaults``. Detach
    only: existing projects keep the package in their lockfiles and the user
    store copy stays, because "stop adding this to NEW dataflows" and "take it
    out of the ones I already have" are different decisions and only the first
    one was asked for. Removing it from one dataflow is
    ``DELETE /projects/<id>/<dir_name>``.

    Idempotent: removing something that is not in the defaults is a no-op, so a
    double click (or a retry) reports the same list rather than an error.
    """
    if not PACKAGE_DIR_RE.match(dir_name):
        raise PackageServiceError(f"invalid dirName: {dir_name!r}")

    user_key = _user_key_from_user(user)
    defaults_io.remove_from_defaults(user_key, dir_name)
    return {"packages": sorted(defaults_io.load_defaults(user_key))}


def install_to_defaults(user, dir_name: str) -> dict:
    """Add *dir_name* to defaults + every user's project lockfile + user store.

    Best-effort per project: a single project failure (e.g. malformed spec)
    is reported and the rest continue. Returns
    ``{"packages": [...], "projects": [{"id", "ok", "error?"}],
    "importErrors": {lib: reason}}``.
    """
    if not PACKAGE_DIR_RE.match(dir_name):
        raise PackageServiceError(f"invalid dirName: {dir_name!r}")

    user_key = _user_key_from_user(user)
    outcome = _ensure_user_store_install(user_key, dir_name)
    defaults_io.add_to_defaults(user_key, dir_name)

    results: list[dict] = []
    for project in projects_repo.list_for_user(user.id):
        try:
            current = get_project_lockfile(user_key, project.id)
            if dir_name in current:
                results.append({"id": project.id, "ok": True, "alreadyPresent": True})
                continue
            current.add(dir_name)
            _write_lockfile(user_key, project.id, current)
            results.append({"id": project.id, "ok": True, "alreadyPresent": False})
        except Exception as exc:  # noqa: BLE001 — per-project failure is OK
            log.warning(
                "install_to_defaults: failed to patch project %s: %s",
                project.id, exc,
            )
            results.append({"id": project.id, "ok": False, "error": str(exc)})

    payload = {
        "packages": sorted(defaults_io.load_defaults(user_key)),
        "projects": results,
    }
    # Same reason as the per-project install: every project now references a
    # package whose library cannot be imported, and pip said nothing.
    payload["importErrors"] = outcome.import_errors
    return payload


# ---------------------------------------------------------------------------
# Prune
# ---------------------------------------------------------------------------

def prune_unreferenced_packages(
    user_key: str, candidate_dirs: Iterable[str],
) -> dict[str, set[str]]:
    """Delete user-store copies (and defaults entries) for unreferenced candidates.

    For each candidate dirName:
      - Skip if it's the builtin (never prunable).
      - Scan all of the user's projects' lockfiles.
      - If no project references it, delete from user store AND remove from
        defaults. (Defaults exists explicitly to keep something seeded into
        new projects — if nothing actually uses it, the seed has no future
        purpose.)

    Returns ``{"pruned": <dirs>, "removedFromDefaults": <dirs>}``.
    """
    candidates = {
        d for d in candidate_dirs
        if isinstance(d, str)
        and PACKAGE_DIR_RE.match(d)
        and not d.startswith(f"{BUILTIN_PACKAGE_ID}@")
    }
    if not candidates:
        return {"pruned": set(), "removedFromDefaults": set()}

    # Need a User to enumerate projects. We accept user_key (the on-disk
    # segment) but resolving projects requires the DB id. Detect: numeric
    # user_key → DB id; "guest" → look up the shared guest user.
    from utk_curio.backend.app.users.services import _shared_guest_user

    if user_key == "guest":
        owner = _shared_guest_user()
        user_id = owner.id
    elif user_key.isdigit():
        user_id = int(user_key)
    else:
        raise PackageServiceError(f"invalid user_key {user_key!r}")

    referenced: set[str] = set()
    installed_majors = _installed_majors_by_pkg(user_key)
    for project in projects_repo.list_for_user(user_id):
        spec = projects_storage.read_spec(user_key, project.id)
        if spec is None:
            continue
        referenced.update(project_packages(spec, installed_majors))
        if candidates.issubset(referenced):
            break  # short-circuit: every candidate has at least one reference

    unreferenced = candidates - referenced
    pruned: set[str] = set()
    removed_from_defaults: set[str] = set()
    current_defaults = defaults_io.load_defaults(user_key)
    new_defaults = set(current_defaults)
    # Track each pruned package's manifest.python_deps BEFORE deletion so
    # we can ref-count and pip-uninstall after the files are gone.
    pruned_python_deps: dict[str, dict[str, str]] = {}
    for dn in unreferenced:
        try:
            pruned_python_deps[dn] = _read_python_deps(user_key, dn)
        except Exception:  # noqa: BLE001 — keep prune resilient
            pruned_python_deps[dn] = {}
        try:
            if uninstall_packageage(user_key, dn):
                pruned.add(dn)
                # dev/97: the sweep dev/91 §6.7 promised — overlay + data
                # dir + pin go with the package; the audit ledger survives.
                from utk_curio.backend.app.packages.backend_runtime import (
                    remove_backend_residue,
                )
                remove_backend_residue(user_key, dn)
        except Exception as exc:  # noqa: BLE001
            log.warning("prune: uninstall of %s failed: %s", dn, exc)
            continue
        if dn in new_defaults:
            new_defaults.discard(dn)
            removed_from_defaults.add(dn)
    if removed_from_defaults:
        defaults_io.save_defaults(user_key, new_defaults)

    # Pip-uninstall every Python dep that *was* declared by a pruned
    # package and is no longer declared by anything still installed.
    # Walking the surviving manifests by hand is safer than trying to
    # diff before/after — it gives a single authoritative reference set.
    deps_to_remove = _python_deps_unique_to_pruned(user_key, pruned_python_deps, pruned)
    if deps_to_remove:
        try:
            from utk_curio.backend.app.packages.pip_runner import (
                PipInstallError, uninstall_python_deps,
            )
            uninstall_python_deps(deps_to_remove)
        except PipInstallError as exc:
            # Don't fail the whole prune over a pip uninstall hiccup;
            # the user can clean up manually if needed.
            log.warning("prune: pip uninstall failed: %s", exc)
    return {"pruned": pruned, "removedFromDefaults": removed_from_defaults}


def _read_manifest(user_key: str, dir_name: str):
    """The installed package's typed manifest, or ``None`` if unreadable.

    ``None`` rather than a raise: every caller here is reporting on an install
    that already happened, and a manifest that will not parse is a separate
    complaint from the one being made.
    """
    from utk_curio.backend.app.packages.manifest import (
        ManifestError,
        load_packageage_manifest,
    )
    from utk_curio.backend.app.packages.storage import package_dir

    try:
        return load_packageage_manifest(package_dir(user_key, dir_name))
    except (ManifestError, OSError, PackageIdError):
        return None


def _read_python_deps(user_key: str, dir_name: str) -> dict[str, str]:
    """Read the installed package's ``manifest.dependencies.python`` map."""
    m = _read_manifest(user_key, dir_name)
    return dict(m.python_deps or {}) if m is not None else {}


def _python_deps_unique_to_pruned(
    user_key: str,
    pruned_deps: dict[str, dict[str, str]],
    pruned_names: set[str],
) -> list[str]:
    """Return the dep names that were declared by a pruned package and
    are NOT declared by any other package still in the user store.

    Walks every surviving package's manifest once so cost stays linear
    in the user's installed-package count.
    """
    candidate_dep_names: set[str] = set()
    for dn in pruned_names:
        candidate_dep_names.update(pruned_deps.get(dn, {}).keys())
    if not candidate_dep_names:
        return []
    still_needed: set[str] = set()
    for dir_name, manifest in _locked_store_index(user_key).items():
        if dir_name in pruned_names or isinstance(manifest, Exception):
            continue  # just removed, or unreadable — declares nothing we can see
        still_needed.update(dict(manifest.python_deps or {}).keys())
    return sorted(candidate_dep_names - still_needed)


# ---------------------------------------------------------------------------
# New-project seeding
# ---------------------------------------------------------------------------

def seed_spec_with_defaults(user_key: str, spec: dict | None) -> dict:
    """Merge per-user defaults into a new project's spec lockfile.

    Only acts when the spec's existing packages list is empty/missing.
    Returns the (possibly mutated) spec; safe to call with ``None``
    (returns an empty spec template).
    """
    if spec is None or not isinstance(spec, dict):
        spec = {"dataflow": {"nodes": [], "edges": [], "packages": []}}
    existing = project_packages(spec)
    if existing:
        return spec
    defaults = defaults_io.load_defaults(user_key)
    if not defaults:
        return spec
    set_project_packages(spec, defaults)
    return spec


# ---------------------------------------------------------------------------
# Agent read surfaces (memo dev/84) — plain-dict summaries so the agents
# module (ADR-AG-007: thin wrappers, no package knowledge) can serve its
# packages.catalog / packages.resolve tools from the domain's single truth.
# ---------------------------------------------------------------------------

def _catalog_manifests() -> dict[str, "PackageManifest"]:
    """``dirName -> manifest`` for every well-formed committed catalog package."""
    from utk_curio.backend.app.packages.manifest import (
        ManifestError,
        load_packageage_manifest,
    )

    root = catalog_root()
    out: dict[str, PackageManifest] = {}
    if not root.is_dir():
        return out
    for entry in sorted(root.iterdir()):
        if not entry.is_dir() or not PACKAGE_DIR_RE.match(entry.name):
            continue
        try:
            out[entry.name] = load_packageage_manifest(entry)
        except ManifestError:
            continue  # malformed fixtures are skipped, matching the catalog route
    return out


def agent_catalog_overview(user_key: str, project_id: str | None) -> list[dict]:
    """Per-package summaries for the agents' ``packages.catalog`` read tool.

    ``installed`` means the CURRENT project's lockfile (what matters for a node
    running in this project — dev/84); ``builtin`` marks ``curio.builtin``,
    which is always present and never proposable.

    Scope is the committed catalog PLUS whatever is already in this user's
    package store (memo dev/93 D4). The store half matters because an
    agent-authored package (``curio.agent``/``curio.notes``-style) never
    enters the committed catalog: before this, such a package could not be
    enlisted into a second project at all — ``package.install`` refused it as
    "not in the Nodes Catalog" — so an agent asked to reuse it had no move
    left except authoring yet another near-duplicate. A store manifest wins
    over a catalog one of the same dirName: it is the copy an install would
    actually enlist.
    """
    lockfile: set[str] = set()
    if project_id:
        try:
            lockfile = get_project_lockfile(user_key, project_id)
        except Exception:  # noqa: BLE001 — an unreadable project reads as empty
            lockfile = set()
    catalog = _catalog_manifests()  # committed catalog, not the store: outside
    return _agent_catalog_overview_unlocked(
        lockfile, _locked_store_index(user_key), catalog,
    )


def _agent_catalog_overview_unlocked(
    lockfile: set[str],
    store: dict[str, object],
    catalog: dict[str, "PackageManifest"],
) -> list[dict]:
    """:func:`agent_catalog_overview` over existing snapshots (dev/99 R2).
    Takes no locks and performs no I/O."""
    manifests: dict[str, "PackageManifest"] = dict(catalog)
    for dir_name, manifest in store.items():
        if isinstance(manifest, Exception):
            continue  # an unreadable store copy cannot provide working nodes
        manifests[dir_name] = manifest
    rows: list[dict] = []
    for dir_name, manifest in sorted(manifests.items()):
        builtin = manifest.package_id == BUILTIN_PACKAGE_ID
        rows.append(
            {
                "dirName": dir_name,
                "packageId": manifest.package_id,
                "name": manifest.name,
                "description": manifest.description or "",
                "installed": builtin or dir_name in lockfile,
                "builtin": builtin,
            }
        )
    return rows


def template_landscape(user_key: str, project_id: str) -> dict:
    """Everything an agent needs to know about what already exists, from ONE
    walk of the package store (memo dev/99 R2).

    Returns ``{"available", "notEnlisted", "catalog", "skipped"}`` — the same
    data as :func:`available_templates`, :func:`installed_templates_not_in_project`
    and :func:`agent_catalog_overview`, plus the availability report's
    degradation signal, all derived from a single snapshot.

    Two reasons this exists rather than callers making three calls. It is
    CHEAPER: each of those public readers independently resolves the project
    lockfile and independently walks the store, so composing three of them for
    one payload cost three spec reads and three traversals. And it is the only
    shape that can be made ATOMIC: when the seed lock reaches readers (dev/99
    proper), one composite acquires it once and every part of the payload
    describes the same instant, where three separately-locked calls would each
    be internally consistent yet able to straddle a seeding pass — which is
    exactly the tear that lets an agent see a package in one half of its
    evidence and not the other, and author a duplicate.

    Callers in the agents domain consume this; they never own the lock
    (`ADR-AG-007` keeps package knowledge here). It calls the unlocked cores
    directly, never the public readers, so the non-reentrant seed lock can be
    acquired exactly once on every path.
    """
    # Non-store I/O first, so the lock covers only the store snapshot (§3.3).
    wanted = _lockfile_or_empty(user_key, project_id)
    catalog = _catalog_manifests()
    store = _locked_store_index(user_key)
    report = _available_templates_report_unlocked(wanted, store)
    return {
        "available": report["templates"],
        "skipped": report["skipped"],
        "notEnlisted": _installed_templates_not_in_project_unlocked(wanted, store),
        "catalog": _agent_catalog_overview_unlocked(wanted, store, catalog),
    }


def agent_resolve_report(user_key: str, dir_names: list[str]) -> dict:
    """Deps/permissions per requested package + a conflict probe (dev/84).

    Mirrors the catalog UI's pre-install probe: the requested packages resolve
    together with everything already in the user's store, with not-yet-installed
    catalog packages overridden to their committed manifests. Raises
    :class:`PackageServiceError` for an unknown/unresolvable package.
    """
    from utk_curio.backend.app.packages.resolver import (
        ResolverError,
        resolve_for_project_unlocked,
    )

    # The committed catalog is not package-store data: read it before the
    # lock (memo dev/99 §3.3). Then ONE acquisition covers the installed set,
    # the resolver's two store reads and the per-package manifests — the
    # report describes a single instant of the store.
    catalog = _catalog_manifests()
    with package_seed_lock(user_key):
        store = _store_index(user_key)
        installed = set(store)
        unknown = [dn for dn in dir_names if dn not in installed and dn not in catalog]
        if unknown:
            raise PackageServiceError(
                f"unknown package(s): {', '.join(sorted(unknown))}", 404,
            )
        probe = sorted(set(dir_names) | installed)
        overrides = {
            dn: catalog_root() / dn for dn in probe if dn not in installed and dn in catalog
        }
        try:
            result = resolve_for_project_unlocked(user_key, probe, overrides=overrides)
        except ResolverError as exc:
            raise PackageServiceError(str(exc), 400) from exc

    def _manifest_for(dir_name: str) -> "PackageManifest | None":
        if dir_name in store:
            manifest = store[dir_name]
            return None if isinstance(manifest, Exception) else manifest
        return catalog.get(dir_name)

    packages: list[dict] = []
    for dir_name in dir_names:
        manifest = _manifest_for(dir_name)
        if manifest is None:
            continue
        packages.append(
            {
                "dirName": dir_name,
                "name": manifest.name,
                "permissions": list(manifest.permissions),
                "pythonDeps": dict(manifest.python_deps),
                "jsDeps": dict(manifest.js_deps),
            }
        )
    return {
        "packages": packages,
        "conflicts": [
            {
                "package": c.package,
                "ranges": [{"packageDir": p, "range": r} for (p, r) in c.ranges],
            }
            for c in result.conflicts
        ],
    }


# ---------------------------------------------------------------------------
# Internal
# ---------------------------------------------------------------------------

def _user_key_from_user(user) -> str:
    """Local copy of projects.services._user_dir_key to avoid a circular import."""
    from utk_curio.backend.config import CURIO_SHARED_GUEST_USERNAME

    if user.is_guest and user.username == CURIO_SHARED_GUEST_USERNAME:
        return "guest"
    return str(user.id)
