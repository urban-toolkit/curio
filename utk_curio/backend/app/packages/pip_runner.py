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
- **Idempotent.** Already-importable + version-matching deps are
  detected with ``importlib.metadata`` and skipped — repeat installs of
  the same package are essentially no-ops.
- **Never touches Curio's core ``pyproject`` deps.** Uninstall walks
  package manifests, but base-install libraries (``flask``,
  ``geopandas``, ``shapely`` …) aren't listed in any package manifest,
  so they're safe.
- **Captures pip's stderr/stdout** so failures surface in the install
  response with enough context to debug, not an opaque 500.
"""

from __future__ import annotations

import logging
import subprocess
import sys
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version as installed_version
from typing import Callable, Iterable, Mapping, Optional

log = logging.getLogger(__name__)

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
    """
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


def install_python_deps(
    deps: Mapping[str, str],
    *,
    on_line: Optional[Callable[[str], None]] = None,
) -> InstallReport:
    """Pip-install every dep in *deps* that isn't already importable.

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
        rc = proc.wait()
        if rc != 0:
            tail = "\n".join(last_lines)[-2000:]
            raise PipInstallError(
                f"pip install failed (exit {rc}): {tail.strip()}"
            )
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
    return InstallReport(installed=to_install, skipped=skipped)


def uninstall_python_deps(names: Iterable[str]) -> UninstallReport:
    """Pip-uninstall *names*. Best-effort — already-missing packages are
    silently ignored (pip exits 0 for "not installed" with --yes).

    Caller is responsible for ref-counting: don't pass a dep that's
    still listed by another installed package's manifest.
    """
    names = [n for n in names if n]
    if not names:
        return UninstallReport(removed=[], kept=[])

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
