"""Private content-addressed staging for built package artifacts (memo dev/89 §3.8/§3.10).

A finished build's archive is staged here, named by its own SHA-256. The
review proposal references the artifact DIGEST — never a mutable filesystem
path — and the promotion coordinator (dev/89 commit 7) reads the exact bytes
back through :func:`read_artifact`, which re-hashes on every read: a
tampered or corrupted file is removed and reported loudly, never installed.

Layout (sibling of the installer's ``.package-staging/`` transaction dir)::

    .curio/users/<user_key>/.package-build-staging/
      <sha256>.zip          # the staged archive, content-addressed
      <sha256>.meta.json    # {"createdAt": epoch_seconds, "bytes": n}

Staging is idempotent by construction (same bytes → same digest → same file)
and expiring: :func:`sweep_expired` removes artifacts past their TTL so an
abandoned proposal's bytes do not live forever (dev/89 §6: an expired
artifact marks the proposal expired — Apply never rebuilds silently).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from pathlib import Path

from utk_curio.backend.app.packages.storage import _user_key_segment, _users_base

log = logging.getLogger(__name__)

_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")

# Staged archives are compressed .curio.zip bytes; the installer's
# uncompressed ceiling is 128 MiB, so the compressed artifact is bounded
# by the same figure with room to spare.
MAX_ARTIFACT_BYTES = 128 * 1024 * 1024

# Default artifact lifetime. A proposal older than this must be rebuilt from
# its immutable request (same input digest → same build), never trusted.
DEFAULT_TTL_SECONDS = 24 * 60 * 60


class StagingError(ValueError):
    """Raised on invalid digests, missing/expired artifacts, or corruption."""


def user_build_staging_dir(user_key: str) -> Path:
    """``.curio/users/<user_key>/.package-build-staging/`` (may not exist yet)."""
    return _users_base() / _user_key_segment(user_key) / ".package-build-staging"


def _validate_digest(digest: str) -> str:
    if not isinstance(digest, str) or not _DIGEST_RE.match(digest):
        raise StagingError(f"artifact digest must be 64 lowercase hex chars, got {digest!r}")
    return digest


def _artifact_path(user_key: str, digest: str) -> Path:
    return user_build_staging_dir(user_key) / f"{digest}.zip"


def _meta_path(user_key: str, digest: str) -> Path:
    return user_build_staging_dir(user_key) / f"{digest}.meta.json"


def stage_artifact(user_key: str, data: bytes) -> str:
    """Store *data* content-addressed; returns its SHA-256 digest.

    Idempotent: restaging identical bytes refreshes the metadata timestamp
    (extending the TTL) without rewriting the artifact. The write is atomic
    (tmp file + ``os.replace``) so a crash never leaves a partial artifact
    under a valid digest name.
    """
    if not isinstance(data, (bytes, bytearray)) or not data:
        raise StagingError("artifact must be non-empty bytes")
    if len(data) > MAX_ARTIFACT_BYTES:
        raise StagingError(
            f"artifact exceeds the staging limit ({len(data)} > {MAX_ARTIFACT_BYTES} bytes)"
        )
    digest = hashlib.sha256(data).hexdigest()
    base = user_build_staging_dir(user_key)
    base.mkdir(parents=True, exist_ok=True)
    target = _artifact_path(user_key, digest)
    if not target.is_file():
        tmp = base / f".tmp-{digest}"
        tmp.write_bytes(bytes(data))
        os.replace(tmp, target)
    _meta_path(user_key, digest).write_text(
        json.dumps({"createdAt": time.time(), "bytes": len(data)}),
        encoding="utf-8",
    )
    return digest


def has_artifact(user_key: str, digest: str) -> bool:
    return _artifact_path(user_key, _validate_digest(digest)).is_file()


def read_artifact(user_key: str, digest: str) -> bytes:
    """Read one staged artifact, verifying its content hash on every read.

    Raises :class:`StagingError` when the artifact is absent (expired or never
    staged) or when the stored bytes no longer hash to *digest* — the corrupt
    file is removed so it can never be promoted (dev/89 §3.10: Apply installs
    only the exact reviewed digest).
    """
    digest = _validate_digest(digest)
    path = _artifact_path(user_key, digest)
    if not path.is_file():
        raise StagingError(
            f"artifact {digest} is not staged (expired or never built) — "
            "rebuild from the immutable request"
        )
    data = path.read_bytes()
    actual = hashlib.sha256(data).hexdigest()
    if actual != digest:
        path.unlink(missing_ok=True)
        _meta_path(user_key, digest).unlink(missing_ok=True)
        raise StagingError(
            f"artifact {digest} failed integrity verification (stored bytes "
            f"hash to {actual}) — removed; rebuild from the immutable request"
        )
    return data


def discard_artifact(user_key: str, digest: str) -> bool:
    """Remove one staged artifact + metadata. Returns True when removed."""
    digest = _validate_digest(digest)
    path = _artifact_path(user_key, digest)
    removed = path.is_file()
    path.unlink(missing_ok=True)
    _meta_path(user_key, digest).unlink(missing_ok=True)
    return removed


def _staged_at(user_key: str, digest: str, artifact: Path) -> float:
    meta = _meta_path(user_key, digest)
    try:
        payload = json.loads(meta.read_text(encoding="utf-8"))
        created = payload.get("createdAt")
        if isinstance(created, (int, float)):
            return float(created)
    except (OSError, ValueError):
        pass
    # Metadata missing/corrupt: fall back to the artifact's mtime so the
    # sweep still terminates the artifact eventually.
    try:
        return artifact.stat().st_mtime
    except OSError:
        return 0.0


def sweep_expired(
    user_key: str, *, ttl_seconds: float = DEFAULT_TTL_SECONDS, now: float | None = None
) -> list[str]:
    """Remove artifacts older than *ttl_seconds*; returns the removed digests.

    Best-effort per entry (one unremovable file never blocks the sweep), but
    every removal is logged. Also clears stray tmp files from crashed writes.
    """
    base = user_build_staging_dir(user_key)
    if not base.is_dir():
        return []
    current = time.time() if now is None else now
    removed: list[str] = []
    for entry in sorted(base.iterdir()):
        if entry.name.startswith(".tmp-"):
            entry.unlink(missing_ok=True)
            continue
        if not entry.name.endswith(".zip"):
            continue
        digest = entry.name[: -len(".zip")]
        if not _DIGEST_RE.match(digest):
            continue
        if current - _staged_at(user_key, digest, entry) < ttl_seconds:
            continue
        try:
            entry.unlink(missing_ok=True)
            _meta_path(user_key, digest).unlink(missing_ok=True)
            removed.append(digest)
            log.info("Expired staged package artifact %s for %s", digest, user_key)
        except OSError:
            log.warning("Failed to expire staged artifact %s for %s", digest, user_key,
                        exc_info=True)
    return removed
