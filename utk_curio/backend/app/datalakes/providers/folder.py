"""A folder on the machine running Curio.

The root comes from the manifest, never from a request, and every access is
checked against it after resolving symlinks. Reading only: nothing is written
into the folder.
"""

from __future__ import annotations

import io
import os
from pathlib import Path
from typing import BinaryIO, ClassVar, Iterator

from utk_curio.backend.app.common.safe_paths import is_within
from utk_curio.backend.app.datalakes.domain.errors import ResourceNotFound
from utk_curio.backend.app.datalakes.domain.manifest import LakeSourceManifest
from utk_curio.backend.app.datalakes.infrastructure import storage
from utk_curio.backend.app.datalakes.providers.storage_base import (
    MAX_DEPTH,
    FileEntry,
    is_skipped,
    validate_relpath,
)


class FolderStorage:
    type: ClassVar[str] = "folder"

    def __init__(self, manifest: LakeSourceManifest, transport=None) -> None:
        # ``transport`` is accepted for a uniform constructor and ignored: a
        # folder is read from disk, and no request leaves the machine.
        self.manifest = manifest
        self.root = storage.storage_root(manifest)

    # ── guards ─────────────────────────────────────────────────────────────

    def _resolve(self, relpath: str) -> Path:
        validate_relpath(relpath)
        candidate = (self.root / relpath).resolve()
        if not is_within(candidate, self.root) or not candidate.is_file():
            raise ResourceNotFound(f"{relpath} is not a file of {self.manifest.name}")
        return candidate

    # ── the contract ───────────────────────────────────────────────────────

    def scan(self, prefix: str = "") -> Iterator[FileEntry]:
        start = self.root
        if prefix:
            validate_relpath(prefix.rstrip("/"))
            start = (self.root / prefix).resolve()
            if not is_within(start, self.root) or not start.is_dir():
                return
        base_depth = len(start.relative_to(self.root).parts)
        for dirpath, dirnames, filenames in os.walk(start, followlinks=False):
            current = Path(dirpath)
            depth = len(current.relative_to(self.root).parts)
            dirnames[:] = sorted(
                d for d in dirnames
                if not is_skipped(d) and depth - base_depth < MAX_DEPTH
            )
            for name in sorted(filenames):
                if is_skipped(name):
                    continue
                full = current / name
                try:
                    if full.is_symlink():
                        # A link is followed only when it lands inside the root.
                        if not is_within(full.resolve(), self.root):
                            continue
                    stat = full.stat()
                except OSError:
                    continue
                if not full.is_file():
                    continue
                relpath = full.relative_to(self.root).as_posix()
                yield FileEntry(relpath=relpath, size=stat.st_size, mtime=stat.st_mtime)

    def open(self, relpath: str, *, byte_range: tuple[int, int] | None = None) -> BinaryIO:
        path = self._resolve(relpath)
        if byte_range is None:
            return path.open("rb")
        start, end = byte_range
        with path.open("rb") as handle:
            handle.seek(max(0, start))
            return io.BytesIO(handle.read(max(0, end - start)))

    def local_path(self, relpath: str) -> Path:
        return self._resolve(relpath)
