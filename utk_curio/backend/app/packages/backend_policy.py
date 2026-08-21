"""Static policy scan + declaration reading for draft backend code
(memo dev/91 §3, commit 3).

The scan is honest about what a regex can do (§3): it blocks only the
**escape-hatch families** — dynamic code execution, process spawning, foreign
function interfaces, resident-service frameworks — and treats the network
family per the declared ``server-network`` permission (block undeclared,
warn declared). It does NOT pretend to be a jail: filesystem writes are
already rlimit/workspace-bounded at runtime, so ``open()`` is not blocked.
Every finding names the fix (the dev/90 A4/A5 refusal rule) and carries its
``file:line``.

Declaration reading reuses the manifest module's parser — ONE grammar for
the ``backend`` object (the A14 two-spellings lesson), whether it arrives in
an installed manifest or a draft request.
"""

from __future__ import annotations

import re
from typing import Any, Mapping

from utk_curio.backend.app.packages import backend_contract as bc
from utk_curio.backend.app.packages.build_deps import Finding
from utk_curio.backend.app.packages.manifest import (
    BackendManifest,
    ManifestError,
    _parse_backend,
)


class BackendPolicyError(ValueError):
    """A draft's backend declaration is malformed — reviewable message."""


def backend_declaration(manifest: Mapping[str, Any]) -> BackendManifest | None:
    """The draft manifest's ``backend`` object through the ONE parser.

    Returns None when the draft declares no backend. Raises
    :class:`BackendPolicyError` (with the manifest parser's fix-naming
    message) when the declaration is malformed — the build fails before any
    expensive phase, not at packaging."""
    raw = manifest.get("backend")
    if raw is None:
        return None
    permissions = manifest.get("permissions")
    perms = [p for p in permissions if isinstance(p, str)] if isinstance(permissions, list) else []
    try:
        return _parse_backend(raw, where="draft.manifest", permissions=perms)
    except ManifestError as exc:
        raise BackendPolicyError(str(exc)) from exc


def net_declared(manifest: Mapping[str, Any]) -> bool:
    permissions = manifest.get("permissions")
    return isinstance(permissions, list) and bc.PERMISSION_SERVER_NETWORK in permissions


#: (regex, code, message) — blocked in every backend source, declared or not.
_BLOCK_RULES: tuple[tuple[re.Pattern[str], str, str], ...] = (
    (re.compile(r"^\s*(import|from)\s+ctypes\b"), "backend-ctypes",
     "ctypes is a foreign-function escape hatch — backend handlers are pure Python"),
    (re.compile(r"^\s*(import|from)\s+(subprocess|multiprocessing|pty)\b"), "backend-spawn",
     "process spawning is not available in the backend sandbox — compute in the handler itself"),
    (re.compile(r"\bos\s*\.\s*(system|popen|exec\w*|spawn\w*|fork\w*)\s*\("), "backend-os-spawn",
     "os-level process execution is not available in the backend sandbox"),
    (re.compile(r"(?<![\w.])(eval|exec|compile|__import__)\s*\("), "backend-dynamic-code",
     "dynamic code execution defeats the policy scan — write the logic directly"),
    (re.compile(r"^\s*(import|from)\s+importlib\b"), "backend-dynamic-import",
     "dynamic imports defeat the policy scan — import dependencies at the top of the entry"),
    (re.compile(r"^\s*(import|from)\s+(flask|fastapi|django|aiohttp\.web)\b|Blueprint\s*\(|@\w+\.route\b|\.run\s*\(\s*host\s*="),
     "backend-resident-service",
     "resident services are out of scope (dev/89 Follow-up B) — the sandbox is "
     "on-demand: expose 'def handle(payload)' and return the result"),
    (re.compile(r"^\s*(import|from)\s+(socketserver|http\.server)\b"), "backend-resident-server",
     "serving sockets is a resident service (dev/89 Follow-up B) — handlers only answer invocations"),
)

#: Network family — verdict depends on the declared server-network permission.
_NET_RULE = re.compile(
    r"^\s*(import|from)\s+(socket|ssl|urllib|http\.client|requests|httpx|aiohttp|ftplib|smtplib|xmlrpc)\b"
)


def scan_backend_sources(
    files: Mapping[str, bytes], *, net_permission_declared: bool
) -> list[Finding]:
    """Line-scan every ``backend/**.py`` source. Returns findings; a caller
    treats any ``block`` severity as build-fatal (the gate is not advisory —
    the dev/89 §3.4 posture)."""
    findings: list[Finding] = []
    for path in sorted(files):
        if not path.startswith("backend/") or not path.endswith(".py"):
            continue
        try:
            text = files[path].decode("utf-8")
        except UnicodeDecodeError:
            findings.append(Finding(
                "block", "backend-not-utf8",
                f"{path}: backend sources must be UTF-8 text",
            ))
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            for rule, code, message in _BLOCK_RULES:
                if rule.search(line):
                    findings.append(Finding("block", code, f"{path}:{lineno}: {message}"))
            if _NET_RULE.search(line):
                if net_permission_declared:
                    findings.append(Finding(
                        "warn", "backend-network-declared",
                        f"{path}:{lineno}: network use rides the declared "
                        f"'{bc.PERMISSION_SERVER_NETWORK}' permission — the install "
                        "review surfaces it to the user",
                    ))
                else:
                    findings.append(Finding(
                        "block", "backend-network-undeclared",
                        f"{path}:{lineno}: network access requires the "
                        f"'{bc.PERMISSION_SERVER_NETWORK}' permission in the manifest — "
                        "declare it (reviewed at install) or drop the import",
                    ))
    return findings


def validate_backend_files(
    decl: BackendManifest, files: Mapping[str, bytes]
) -> list[Finding]:
    """Cross-check the declaration against the (merged) file set: the entry
    must ship; template↔handler agreement is the manifest loader's job."""
    if decl.entry not in files:
        return [Finding(
            "block", "backend-entry-missing",
            f"backend.entry {decl.entry!r} is declared but the file does not ride "
            "the draft — ship it in the request's files",
        )]
    return []
