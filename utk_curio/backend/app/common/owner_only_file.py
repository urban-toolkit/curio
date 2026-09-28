"""Owner-only JSON files in a user's store: the per-user files that hold secrets.

A file lives in the account's directory under ``.curio/users/<key>/``, which is
created 0700; the file itself is 0600. A write goes to a temp file beside the
target, is fsynced, and replaces the target with ``os.replace``, so a reader
sees the old document or the new one and never a partial write. Writers hold
the two-layer lock (a thread lock, then a file lock) the project spec uses.

``.curio/users`` is in the sandbox isolation's ``SENSITIVE_PATHS``, so node code
running under isolation cannot open these files. **Plaintext at rest**:
encryption is separate work that covers every secret at once.

Used by ``users.connection_keys`` and ``agents.llm_configs``.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from utk_curio.backend.app.common.file_locks import exclusive_lock


def ensure_private_dir(directory: Path) -> None:
    """Create *directory* if needed and make it 0700 (best effort on the mode)."""
    directory.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(directory, 0o700)
    except OSError:
        pass


def locked(directory: Path, filename: str, *, namespace: str, key: str):
    """The exclusive lock a writer of *filename* in *directory* holds. Creates
    *directory* 0700, since the lock file lives in it."""
    ensure_private_dir(directory)
    return exclusive_lock(directory / f".{filename}.lock", namespace=namespace, key=key)


def write_json(path: Path, doc: dict) -> None:
    """Write *doc* to *path* at mode 0600: a temp file in the same directory,
    fsynced, then renamed over the target. Nothing is left behind on failure."""
    fd, tmp = tempfile.mkstemp(prefix=f".{path.stem}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(doc, handle, indent=2, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
