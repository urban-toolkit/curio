"""Per-package Python dependency installation via ``pip``.

A package's ``manifest.dependencies.python`` declares the libraries the
package's behavior hooks need at runtime. The catalog install flow calls
:func:`install_python_deps` after copying the package files; uninstall
walks every other installed package's manifest and pip-uninstalls deps
that no remaining package still declares.

Design choices:

- **Runs synchronously** in the install request. A heavy first-time
  install of ``torch`` can take many minutes, but the v1 UX is "blocks
  the Install button until done." Async-with-job-progress is the future
  upgrade, not the current contract.
- **Uses ``sys.executable -m pip``** so the install lands in whichever
  interpreter the Curio backend is running under (conda env or venv).
- **Idempotent.** Deps already present at a matching version are detected
  with ``importlib.metadata`` and skipped — repeat installs of the same
  package are essentially no-ops. Note that metadata presence is not
  importability: see :func:`import_failure`.
- **Never touches Curio's core ``pyproject`` deps.** Uninstall walks
  package manifests, but base-install libraries (``flask``,
  ``geopandas``, ``shapely`` …) aren't listed in any package manifest,
  so they're safe.
- **Captures pip's stderr/stdout** so failures surface in the install
  response with enough context to debug, not an opaque 500.
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
import sys
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version as installed_version
from typing import Callable, Iterable, Mapping, Optional

log = logging.getLogger(__name__)

#: Hard cap on one import probe. Generous enough for a slow cold import of a
#: large library, short enough that a hung extension cannot stall a page load.
_IMPORT_PROBE_TIMEOUT = 60

# Hard cap on a single pip invocation. Torch on a cold conda env without
# a wheel cache can take ~10 minutes on a moderate connection — 30 minutes
# is generous but not infinite.
_PIP_TIMEOUT_SECONDS = 30 * 60


class PipInstallError(RuntimeError):
    """Pip failed (non-zero exit). Carries the tail of stderr/stdout."""


@dataclass(frozen=True)
class InstallReport:
    installed: list[str]
    skipped: list[str]


@dataclass(frozen=True)
class UninstallReport:
    removed: list[str]
    kept: list[str]


#: A PEP 508 distribution name: alphanumeric ends, ``.``/``-``/``_`` inside.
#: Anything else is not a package name, and the argv entry built from it is not
#: a package either.
_PY_NAME_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?$")

#: A version constraint: comparators, digits, dots, wildcards, commas, and the
#: npm-ish ``^`` / bare-version forms ``_spec_argv`` accepts. No whitespace, no
#: shell metacharacters, no URLs.
_PY_SPEC_RE = re.compile(r"^[\^~=<>!]{0,2}[A-Za-z0-9.*+!_-]+(?:\s*,\s*[~=<>!]{1,2}[A-Za-z0-9.*+!_-]+)*$")


class PipSpecError(ValueError):
    """A requirement that is not a package name plus an optional constraint."""


def validate_python_requirement(name: str, spec: str = "") -> None:
    """Refuse anything that is not ``name`` + an optional version constraint.

    Nothing else validates this. The requirement reaches ``pip install`` as one
    argv element, and pip is happy to read an argv element as a URL to download
    and build (``https://host/x.tar.gz`` runs that sdist's ``setup.py``) or as
    an option (``--index-url=http://attacker/simple`` repoints the whole
    resolve). Neither is shell injection - every call site passes a list argv
    with no ``shell=True`` - but both are arbitrary code execution on the host,
    reachable by any authenticated user through ``POST /api/packages/libraries``
    and by any package manifest's ``dependencies.python``.

    Checked here rather than only at the route because the route is one of
    seven call paths: catalog install, install repair, build promotion, overlay
    build and the launcher all reach pip through manifest-declared names that
    never pass a request handler.
    """
    if not isinstance(name, str) or not _PY_NAME_RE.match(name.strip()):
        raise PipSpecError(
            f"{name!r} is not a Python package name. Requirements are a name "
            f"plus an optional version, not a URL, path or pip option."
        )
    spec = (spec or "").strip()
    if spec and spec != "*" and not _PY_SPEC_RE.match(spec):
        raise PipSpecError(f"{spec!r} is not a valid version constraint for {name!r}")


def _spec_argv(name: str, spec: str) -> str:
    """Build a ``pip install`` argv entry from a manifest ``{name, spec}`` pair.

    Accepts:

    - PEP 440 comparators (``>=2.0``, ``~=4.30``, ``==1.5.0``, ``!=2.0``)
      — passed through verbatim.
    - Bare versions (``1.2.3``) — treated as exact match.
    - npm-style carets (``^0.14``) — rewritten to PEP 440's
      compatible-release ``~=0.14`` so the streetvision / UHVI manifests
      authored in the original PR's npm-influenced style still install.
    - Empty spec — install latest.

    Every requirement passes :func:`validate_python_requirement` first, so a
    URL, path or pip option cannot become an argv entry.
    """
    validate_python_requirement(name, spec)
    spec = (spec or "").strip()
    if not spec or spec == "*":
        return name
    if spec[0] == "^":
        # ``^X.Y`` ≈ ``~=X.Y``: same major (and same minor for 0.x), any
        # patch. Good-enough approximation; documented in EXTENDING.md so
        # future package authors don't expect strict semver caret rules.
        return f"{name}~={spec[1:]}"
    if spec[0] in "=<>~!":
        return f"{name}{spec}"
    # Bare "1.2.3" → treat as exact match (== prefix is PEP 440-canonical).
    return f"{name}=={spec}"


def _is_satisfied(name: str, spec: str) -> bool:
    """Return True if *name* is installed at a version that satisfies *spec*.

    Uses ``packaging.specifiers`` so the version constraint is actually
    evaluated — not just whether the package is importable. Falls back to
    True (let pip decide) if the installed version string can't be parsed.
    """
    from packaging.specifiers import SpecifierSet
    from packaging.version import Version, InvalidVersion

    try:
        ver_str = installed_version(name)
    except PackageNotFoundError:
        return False

    spec = (spec or "").strip()
    if not spec or spec == "*":
        return True

    # Derive the PEP 440 specifier string from the manifest spec the same
    # way _spec_argv does, then strip the package name prefix.
    full = _spec_argv(name, spec)        # e.g. "pyproj>=3.7.3" or "pandas==3.0.2"
    pep440 = full[len(name):]            # e.g. ">=3.7.3"  or  "==3.0.2"

    try:
        return Version(ver_str) in SpecifierSet(pep440)
    except (InvalidVersion, Exception):
        return True  # unparseable — let pip be the authority


#: Top-level modules a distribution ships that are never the import people mean.
#: ``pythermalcomfort`` maps to ``['pythermalcomfort', 'tests']``; probing
#: ``tests`` would be meaningless and, worse, could pass while the real module
#: is broken.
_NON_LIBRARY_MODULES = frozenset({"tests", "test", "docs", "doc", "examples", "example"})

#: Probing costs a subprocess, and a broken install does not heal on its own, so
#: the verdict is memoised per (distribution, version). An install bumps or adds
#: a version, which changes the key; ``forget_import_probes`` covers a
#: same-version repair (``--force-reinstall``).
_import_probe_cache: dict[tuple[str, str], Optional[str]] = {}


def forget_import_probes() -> None:
    """Drop memoised import verdicts, after anything that may have repaired one."""
    _import_probe_cache.clear()


def _module_for_distribution(name: str) -> str:
    """The top-level module *name* is imported as.

    A distribution's name is not its module: ``pillow`` imports as ``PIL``,
    ``scikit-learn`` as ``sklearn``. ``packages_distributions()`` carries the
    real mapping, so use it and fall back to the PEP 503-ish normalisation only
    when the distribution is not installed (where the probe will fail anyway).
    """
    try:
        from importlib.metadata import packages_distributions
    except ImportError:  # pragma: no cover - Python < 3.10
        return name.replace("-", "_")

    try:
        mapping = packages_distributions()
    except Exception:  # pragma: no cover - defensive; probe falls back
        return name.replace("-", "_")

    candidates = [mod for mod, dists in mapping.items() if name in dists]
    if not candidates:
        return name.replace("-", "_")
    normalized = name.replace("-", "_").lower()
    for mod in candidates:
        if mod.lower() == normalized:
            return mod
    real = [m for m in candidates if m.lower() not in _NON_LIBRARY_MODULES]
    return sorted(real or candidates)[0]


#: Imports every requested module in ONE interpreter and reports each verdict.
#: Reads the ``{distribution: module}`` map on stdin so no name has to survive
#: shell quoting, and writes ``{distribution: reason}`` for the failures.
#: ``BaseException`` because a broken extension is not restricted to raising
#: ``Exception`` — some abort with ``SystemExit`` on import.
_PROBE_SRC = """
import importlib, json, sys
mapping = json.load(sys.stdin)
out = {}
for dist, module in mapping.items():
    try:
        importlib.import_module(module)
    except BaseException as exc:
        out[dist] = "{}: {}".format(type(exc).__name__, exc)
print(json.dumps(out))
"""


def _run_probe(mapping: Mapping[str, str]) -> Optional[dict[str, str]]:
    """Verdicts for *mapping* from one subprocess, or None if it could not run.

    None means "no answer", never "all fine" — the caller falls back rather than
    reporting a clean bill of health it did not earn.
    """
    if not mapping:
        return {}
    try:
        proc = subprocess.run(
            [sys.executable, "-c", _PROBE_SRC],
            input=json.dumps(mapping),
            capture_output=True,
            text=True,
            timeout=min(300, _IMPORT_PROBE_TIMEOUT * len(mapping)),
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        log.warning("import probe for %s failed to run: %s", sorted(mapping), exc)
        return None
    # A module that hard-crashes the interpreter (segfault in a native
    # extension) takes the whole batch's output with it, so a non-zero exit or
    # unparseable stdout is treated as "no answer" and retried one at a time.
    if proc.returncode != 0 or not (proc.stdout or "").strip():
        return None
    try:
        parsed = json.loads(proc.stdout)
    except ValueError:
        return None
    return {k: v for k, v in parsed.items() if isinstance(v, str)}


def import_failures(deps: Iterable[str]) -> dict[str, str]:
    """``{distribution: reason}`` for every dep in *deps* that cannot be imported.

    Metadata presence is not importability. A wheel whose native extension
    cannot load — the common case for GDAL/CUDA-backed builds — records a
    perfectly good version, so a version check alone reports it satisfied and
    the failure only surfaces later, as a raw ``ImportError`` from whichever
    node happens to run first.

    Probed in a SUBPROCESS, deliberately: importing an arbitrary library into
    the backend process to test it would load torch-sized dependencies into a
    long-lived server, and a segfaulting extension would take the server with it
    rather than being reported.

    **One subprocess for the whole set.** Probing per dep cost 4.7 s for
    ``curio.weather``'s three libraries (pythermalcomfort 1.9 + rasterio 1.0 +
    rasterstats 1.8) because each paid its own interpreter start and re-imported
    the shared GDAL stack; batched they overlap. The verdict is memoised per
    ``(distribution, version)``, so the cost is paid once per backend process —
    but it is paid on a dataflow load, which is why it is worth batching.

    Uses ``sys.executable``, matching :func:`install_python_deps` — the probe
    asks about the interpreter the installs land in.
    """
    failures: dict[str, str] = {}
    to_probe: dict[str, str] = {}     # distribution -> module
    versions: dict[str, str] = {}

    for name in deps:
        try:
            ver = installed_version(name)
        except PackageNotFoundError:
            failures[name] = f"{name} is not installed"
            continue
        key = (name, ver)
        if key in _import_probe_cache:
            cached = _import_probe_cache[key]
            if cached:
                failures[name] = cached
            continue
        versions[name] = ver
        to_probe[name] = _module_for_distribution(name)

    if not to_probe:
        return failures

    verdicts = _run_probe(to_probe)
    if verdicts is None:
        # The batch gave no answer. Retry singly so one hard-crashing module
        # cannot hide the verdict for every other dep in the set.
        for name, module in to_probe.items():
            one = _run_probe({name: module})
            if one is None:
                continue          # still no answer: report nothing, cache nothing
            reason = one.get(name)
            _import_probe_cache[(name, versions[name])] = reason
            if reason:
                failures[name] = reason
        return failures

    for name in to_probe:
        reason = verdicts.get(name)
        _import_probe_cache[(name, versions[name])] = reason
        if reason:
            failures[name] = reason
    return failures


def import_failure(name: str) -> Optional[str]:
    """Why importing *name* fails, or ``None`` if it imports cleanly.

    Convenience wrapper over :func:`import_failures`; prefer that when checking
    more than one dep, so they share a single interpreter start.
    """
    return import_failures([name]).get(name)


def is_satisfied(name: str, spec: str) -> bool:
    """Public wrapper over :func:`_is_satisfied` for callers outside this
    module (e.g. the ``/api/packages/workflow-deps/check`` route)."""
    return _is_satisfied(name, spec)


def install_python_deps(
    deps: Mapping[str, str],
    *,
    on_line: Optional[Callable[[str], None]] = None,
) -> InstallReport:
    """Pip-install every dep in *deps* that isn't already present at a
    satisfying version.

    "Present" means ``importlib.metadata`` knows it and the version matches -
    NOT that it imports. A wheel whose native extension is broken is skipped
    here, correctly: pip would report "already satisfied" and change nothing.
    :func:`import_failure` is what notices that case, and the workflow-deps
    check reports it rather than pretending an install would repair it.

    If *on_line* is supplied, pip's stdout+stderr are streamed live: each
    line is passed to the callback as it arrives, and nothing is buffered.
    The launcher uses this to gate pip's chatter behind ``--verbose 2``
    while still surfacing progress live for long downloads.

    Without *on_line*, pip's output is captured (the legacy API behaviour
    used by ``/api/packages/libraries`` and the catalog install path —
    those return errors via HTTP responses, not terminal output).

    Raises :class:`PipInstallError` if pip exits non-zero. Returns an
    :class:`InstallReport` describing what was installed vs. skipped so
    the caller can include it in the install-API response.
    """
    if not deps:
        return InstallReport(installed=[], skipped=[])

    skipped: list[str] = []
    to_install: list[str] = []
    for name, spec in deps.items():
        if _is_satisfied(name, spec):
            skipped.append(name)
        else:
            to_install.append(_spec_argv(name, spec))

    if not to_install:
        log.info("All Python deps already satisfied; skipping pip: %s", skipped)
        return InstallReport(installed=[], skipped=skipped)

    cmd = [sys.executable, "-m", "pip", "install", "--no-input", *to_install]
    log.info("Running %s", " ".join(cmd))

    if on_line is not None:
        # Streaming path: Popen + readline so the caller sees progress in
        # near-real time (heavy installs like ``torch`` take minutes).
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        last_lines: list[str] = []  # tail kept for the error message
        if proc.stdout is not None:
            for line in proc.stdout:
                stripped = line.rstrip()
                on_line(stripped)
                last_lines.append(stripped)
                if len(last_lines) > 40:
                    last_lines.pop(0)
        # The buffered branch below bounds pip with _PIP_TIMEOUT_SECONDS; this
        # one used a bare wait(), so a mirror that accepts the connection and
        # then never sends EOF pinned the calling thread forever. Reachable
        # over HTTP, not just from the CLI: build_overlay streams, and it sits
        # on the promotion and catalog-install paths.
        try:
            rc = proc.wait(timeout=_PIP_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            raise PipInstallError(
                f"pip timed out after {_PIP_TIMEOUT_SECONDS}s and was killed"
            )
        if rc != 0:
            tail = "\n".join(last_lines)[-2000:]
            raise PipInstallError(
                f"pip install failed (exit {rc}): {tail.strip()}"
            )
        # pip ran: a repair may have landed without the version changing, which
        # the (name, version) memo key would otherwise hide.
        forget_import_probes()
        return InstallReport(installed=to_install, skipped=skipped)

    # Buffered path (API consumers): capture, surface tail on failure.
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=_PIP_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise PipInstallError(
            f"pip install timed out after {_PIP_TIMEOUT_SECONDS}s "
            f"(packages: {to_install})"
        ) from exc

    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "")[-2000:]
        raise PipInstallError(
            f"pip install failed (exit {proc.returncode}): {tail.strip()}"
        )
    forget_import_probes()
    return InstallReport(installed=to_install, skipped=skipped)


def install_python_deps_to_target(
    deps: Mapping[str, str],
    target_dir: str,
    *,
    on_line: Optional[Callable[[str], None]] = None,
) -> InstallReport:
    """dev/97: pip-install *deps* (and their transitive closure) into
    *target_dir* via ``pip install --target`` — the backend sandbox's
    per-package OVERLAY primitive. The shared host interpreter is never
    touched; workers receive the overlay on ``PYTHONPATH``.

    No skip logic ON PURPOSE: the caller wipes the target first (the dev/97
    wipe-before-build discipline — a fresh dir has nothing to skip, and pip's
    ``--target`` semantics over an existing tree are overwrite-ish rather
    than idempotent). Same timeout/error posture as the siblings; the
    report's ``installed`` lists every requested spec."""
    if not deps:
        return InstallReport(installed=[], skipped=[])
    specs = [_spec_argv(name, spec) for name, spec in sorted(deps.items())]
    cmd = [sys.executable, "-m", "pip", "install", "--no-input",
           "--target", str(target_dir), *specs]
    log.info("Running %s", " ".join(cmd))
    if on_line is not None:
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
        last_lines: list[str] = []
        if proc.stdout is not None:
            for line in proc.stdout:
                stripped = line.rstrip()
                on_line(stripped)
                last_lines.append(stripped)
                if len(last_lines) > 40:
                    last_lines.pop(0)
        # The buffered branch below bounds pip with _PIP_TIMEOUT_SECONDS; this
        # one used a bare wait(), so a mirror that accepts the connection and
        # then never sends EOF pinned the calling thread forever. Reachable
        # over HTTP, not just from the CLI: build_overlay streams, and it sits
        # on the promotion and catalog-install paths.
        try:
            rc = proc.wait(timeout=_PIP_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            raise PipInstallError(
                f"pip timed out after {_PIP_TIMEOUT_SECONDS}s and was killed"
            )
        if rc != 0:
            tail = "\n".join(last_lines)[-2000:]
            raise PipInstallError(
                f"pip install --target failed (exit {rc}): {tail.strip()}"
            )
        return InstallReport(installed=specs, skipped=[])
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=_PIP_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise PipInstallError(
            f"pip install --target timed out after {_PIP_TIMEOUT_SECONDS}s "
            f"(packages: {specs})"
        ) from exc
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "")[-2000:]
        raise PipInstallError(
            f"pip install --target failed (exit {proc.returncode}): {tail.strip()}"
        )
    return InstallReport(installed=specs, skipped=[])


def uninstall_python_deps(names: Iterable[str]) -> UninstallReport:
    """Pip-uninstall *names*. Best-effort — already-missing packages are
    silently ignored (pip exits 0 for "not installed" with --yes).

    Caller is responsible for ref-counting: don't pass a dep that's
    still listed by another installed package's manifest.
    """
    names = [n for n in names if n]
    if not names:
        return UninstallReport(removed=[], kept=[])
    # Same argv, same exposure: ``pip uninstall`` also reads ``-r`` and friends.
    for name in names:
        validate_python_requirement(name)

    cmd = [sys.executable, "-m", "pip", "uninstall", "-y", *names]
    log.info("Running %s", " ".join(cmd))
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=_PIP_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise PipInstallError(
            f"pip uninstall timed out after {_PIP_TIMEOUT_SECONDS}s "
            f"(packages: {names})"
        ) from exc

    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "")[-2000:]
        raise PipInstallError(
            f"pip uninstall failed (exit {proc.returncode}): {tail.strip()}"
        )
    return UninstallReport(removed=list(names), kept=[])
