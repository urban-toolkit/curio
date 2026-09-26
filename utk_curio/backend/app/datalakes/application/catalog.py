"""The read side: the source roster, from disk. Never touches the network.

Kept apart from ``browse`` (which queries portals live) so the whole roster
surface can be reasoned about, and tested, without a transport existing at
all. Listing what this deployment connects to is a filesystem question.
"""

from __future__ import annotations

from typing import Any, Callable

from utk_curio.backend.app.datalakes.domain.errors import SourceNotFound
from utk_curio.backend.app.datalakes.domain.manifest import (
    LakeSourceManifest,
    ManifestError,
    load_source_manifest_from_dir,
)
from utk_curio.backend.app.datalakes.infrastructure import storage
from utk_curio.backend.app.datalakes.schemas.payloads import source_row


class LakeCatalog:
    """Lists and resolves lake sources from the catalog root."""

    def __init__(
        self,
        *,
        credential_present: Callable[[str | None], bool] | None = None,
        icon_url_for: Callable[[LakeSourceManifest], str | None] | None = None,
    ) -> None:
        # Injected rather than imported so the roster has no dependency on the
        # credential store or on Flask's url_for, and so a test can list
        # sources without a database or a request context.
        self._credential_present = credential_present or (lambda _slot: False)
        self._icon_url_for = icon_url_for or (lambda _manifest: None)

    # ── reading ────────────────────────────────────────────────────────────

    def manifests(self) -> list[LakeSourceManifest]:
        """Every readable source. A malformed manifest is skipped, not raised.

        Same posture as the Data Catalog's registry scan: one bad folder must
        not empty the catalog. A source that never appears is visible as an
        absence, which is recoverable; a 500 on the listing is not.
        """
        out = []
        for path in storage.list_lake_sources():
            try:
                manifest = load_source_manifest_from_dir(path)
            except (ManifestError, ValueError):
                continue
            if manifest.dir_name != path.name:
                continue
            out.append(manifest)
        return out

    def get_manifest(self, dir_name: str) -> LakeSourceManifest:
        try:
            path = storage.source_dir(dir_name)
        except ValueError as exc:
            raise SourceNotFound(str(exc)) from exc
        if not path.is_dir():
            raise SourceNotFound(f"no data lake source {dir_name!r}")
        try:
            manifest = load_source_manifest_from_dir(path)
        except ManifestError as exc:
            raise SourceNotFound(f"data lake source {dir_name!r} is unreadable: {exc}") from exc
        return manifest

    # ── presenting ─────────────────────────────────────────────────────────

    def row(self, manifest: LakeSourceManifest) -> dict[str, Any]:
        return source_row(
            manifest,
            credential_present=self._credential_present(manifest.auth.secret_id),
            icon_url=self._icon_url_for(manifest),
        )

    def list_catalog(
        self,
        *,
        q: str | None = None,
        provider: str | None = None,
        auth: str | None = None,
    ) -> dict[str, Any]:
        manifests = self.manifests()
        # Facets are counted over everything readable, before filtering, so a
        # chip never reads "0" for a filter that would in fact show something
        # once another chip is cleared.
        facets = {
            "provider": _counts(m.provider.type for m in manifests),
            "auth": _counts(m.auth.mode for m in manifests),
        }
        rows = [self.row(m) for m in manifests]
        if provider:
            rows = [r for r in rows if r["provider"] == provider]
        if auth:
            rows = [r for r in rows if r["auth"]["mode"] == auth]
        if q and q.strip():
            rows = [r for r in rows if _matches(r, q.strip().lower())]
        rows.sort(key=lambda r: r["name"].lower())
        return {"sources": rows, "facets": facets}


def _counts(values) -> dict[str, int]:
    out: dict[str, int] = {}
    for value in values:
        out[value] = out.get(value, 0) + 1
    return dict(sorted(out.items()))


def _matches(row: dict[str, Any], needle: str) -> bool:
    haystack = " ".join(
        [
            str(row.get("name") or ""),
            str(row.get("description") or ""),
            str(row.get("publisher") or ""),
            str(row.get("sourceId") or ""),
            " ".join(row.get("tags") or []),
        ]
    ).lower()
    return needle in haystack
