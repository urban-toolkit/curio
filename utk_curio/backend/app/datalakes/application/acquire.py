"""Download a portal resource into the Data Catalog.

The seam between the two catalogs, and the only place this package writes
anything. What comes out the far end is an **ordinary dataset** - manifest,
preview, schema, ``curio_dataset_path()`` loader - so nothing downstream has to
learn that portals exist. It carries a ``lakeSource`` block recording where it
came from, which is what makes "do I already hold this?" answerable.

The shape of the work:

    already held? ─ yes ─> return it, having made no request at all
         │ no
         v
    describe ──> download_url ──> stream to a temp file under the user's own
                                  tree, capped, hashed
                                        │
                                        v
                                  resolve the format from what actually arrived
                                        │
                                        v
                                  _install_imported_bytes  (the existing seam)
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable

from utk_curio.backend.app.common.safe_paths import validate_component
from utk_curio.backend.app.common.user_storage import user_key_segment, users_base
from utk_curio.backend.app.datalakes.domain.errors import (
    CapabilityUnsupported,
    DownloadTooLarge,
    ResourceNotFound,
)
from utk_curio.backend.app.datalakes.domain.formats import (
    SNIFF_BYTES,
    refuse_archives,
    resolve_format,
)
from utk_curio.backend.app.datalakes.domain.manifest import LakeSourceManifest
from utk_curio.backend.app.datalakes.infrastructure import ratelimit
from utk_curio.backend.app.datalakes.infrastructure.transport import (
    MAX_LAKE_DOWNLOAD_BYTES,
)


def _iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class LakeAcquire:
    """Turns a portal resource into a Data Catalog dataset."""

    def __init__(
        self,
        *,
        user,
        user_key: str,
        transport_for: Callable[[LakeSourceManifest], Any],
        download_target: Callable[[LakeSourceManifest, str, str | None], Any],
        install_bytes: Callable[..., dict[str, Any]],
        find_held: Callable[[str, str, str | None], dict[str, Any] | None],
        describe: Callable[[LakeSourceManifest, str], Any] | None = None,
        find_by_content: Callable[[str], dict[str, Any] | None] | None = None,
    ) -> None:
        self.user = user
        self.user_key = user_key
        self._transport_for = transport_for
        self._download_target = download_target
        self._install_bytes = install_bytes
        self._find_held = find_held
        self._describe = describe
        self._find_by_content = find_by_content

    # ── the check that avoids the network entirely ─────────────────────────

    def already_held(
        self, manifest: LakeSourceManifest, resource_id: str, fmt: str | None
    ) -> dict[str, Any] | None:
        return self._find_held(manifest.dir_name, resource_id, fmt)

    # ── the work ───────────────────────────────────────────────────────────

    def acquire(
        self,
        manifest: LakeSourceManifest,
        resource_id: str,
        *,
        fmt: str | None = None,
        title: str | None = None,
        refresh: bool = False,
        progress: Callable[[int, int | None], None] | None = None,
        cancelled: Callable[[], bool] | None = None,
    ) -> dict[str, Any]:
        """Download and register. Returns ``{dataset, alreadyPresent, unchanged}``."""
        if not manifest.capabilities.download:
            raise CapabilityUnsupported(f"{manifest.name} does not offer downloads")

        held = self.already_held(manifest, resource_id, fmt)
        if held is not None and not refresh:
            # The whole point of recording the resource id: this path issues no
            # request at all, so re-clicking Download costs a portal nothing.
            return {"dataset": held, "alreadyPresent": True, "unchanged": True}

        target = self._download_target(manifest, resource_id, fmt)
        if not target or not target.url:
            raise ResourceNotFound(f"{resource_id} has no download URL")

        bound = min(manifest.capabilities.max_download_bytes, MAX_LAKE_DOWNLOAD_BYTES)
        transport = self._transport_for(manifest)

        tmp_dir = self._tmp_dir()
        tmp_path = tmp_dir / f"{validate_component(_token())}.part"
        head = bytearray()
        written = 0

        def sink_factory(handle):
            def sink(chunk: bytes) -> None:
                nonlocal written
                if cancelled is not None and cancelled():
                    raise _Cancelled()
                if len(head) < SNIFF_BYTES:
                    head.extend(chunk[: SNIFF_BYTES - len(head)])
                handle.write(chunk)
                written += len(chunk)

            return sink

        try:
            with open(tmp_path, "wb") as handle:
                result = transport.download(
                    target.url,
                    sink_factory(handle),
                    max_bytes=bound,
                    progress=progress,
                )

            refuse_archives(
                _content_type(result.headers), target.filename_hint
            )
            fmt_detected, filename = resolve_format(
                declared=target.declared_format,
                final_url=getattr(result, "final_url", target.url),
                headers=dict(result.headers or {}),
                head=bytes(head),
                allowed=tuple(manifest.capabilities.formats),
            )

            # Held again, now that the real format is known: a caller who asked
            # for no particular format may already hold what the portal chose.
            if not refresh:
                held = self.already_held(manifest, resource_id, fmt_detected)
                if held is not None:
                    return {"dataset": held, "alreadyPresent": True, "unchanged": True}

            if held is not None and held.get("lakeSource", {}).get(
                "contentSha256"
            ) == result.sha256:
                # A refresh that found nothing new. The bytes were paid for; a
                # second identical row would not be.
                return {"dataset": held, "alreadyPresent": True, "unchanged": True}
            # The same bytes may already be here from another path: a file the
            # person downloaded by hand and imported with its origin.
            same = self._find_by_content(result.sha256) if self._find_by_content else None
            if same is not None:
                return {"dataset": same, "alreadyPresent": True, "unchanged": True}

            blob = tmp_path.read_bytes()
        except _Cancelled:
            raise
        finally:
            tmp_path.unlink(missing_ok=True)

        dataset = self._install_bytes(
            blob,
            filename,
            fmt_detected,
            title=title or (target.filename_hint or filename),
            lake_source={
                "lakeId": manifest.dir_name,
                "lakeName": manifest.name,
                "resourceId": resource_id,
                "resourceUrl": target.url,
                "finalUrl": getattr(result, "final_url", target.url),
                "fetchedAt": _iso_now(),
                "contentSha256": result.sha256,
            },
        )
        # A changed resource mints a NEW dataset rather than overwriting the
        # held one: a saved dataflow loads that dataset by id, and rewriting its
        # bytes would change that dataflow's results with nothing on screen to
        # explain it.
        return {"dataset": dataset, "alreadyPresent": False, "unchanged": False}

    # ── where the bytes land on the way in ─────────────────────────────────

    def _tmp_dir(self) -> Path:
        """A per-user staging directory, not /tmp.

        These are user data under a tree we already own and can scope, and a
        crashed job leaves an orphan somewhere a sweep can find it rather than
        in a shared system directory.
        """
        # ``user_key_segment`` rather than ``validate_component``: it is
        # stricter, allowing only a numeric id or the guest key, so a username
        # passed where an id belongs cannot become a directory name.
        path = users_base() / user_key_segment(self.user_key) / "datalakes" / "tmp"
        path.mkdir(parents=True, exist_ok=True)
        return path


class _Cancelled(Exception):
    """The user asked for this download to stop."""


def _token() -> str:
    import uuid

    return f"dl{uuid.uuid4().hex[:16]}"


def _content_type(headers) -> str:
    raw = (headers or {}).get("Content-Type") or (headers or {}).get("content-type") or ""
    return str(raw).split(";")[0].strip().lower()
