"""Live search and describe, against one portal or across all of them.

The federated search is the useful behaviour and also the expensive one, so it
is bounded explicitly rather than left to chance:

- one request per searchable source, run concurrently, capped workers;
- **partial failure is a first-class result, never a 502.** One slow or broken
  portal must not make the whole search look broken. Every leg reports its own
  status and the rows that arrived are returned regardless;
- rows are interleaved round-robin across sources, so the first screen is not
  monopolised by whichever portal returned the most;
- the per-source rate limit applies to each leg independently, so a fan-out
  cannot be used to multiply one user's rate past a portal's bucket.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

from utk_curio.backend.app.agents import egress
from utk_curio.backend.app.datalakes.domain.errors import (
    CapabilityUnsupported,
    CredentialRequired,
    DataLakeError,
    RateLimited,
)
from utk_curio.backend.app.datalakes.domain.manifest import LakeSourceManifest
from utk_curio.backend.app.datalakes.domain.resource import SearchPage, SearchQuery
from utk_curio.backend.app.datalakes.infrastructure import ratelimit
from utk_curio.backend.app.datalakes.providers import build_provider

#: Enough to overlap five portals without opening a connection storm.
MAX_FANOUT_WORKERS = 4

#: What one leg of a fan-out may report. `unsupported` is not a failure: a
#: direct-link source has nothing to search and saying so is the right answer.
LEG_STATUSES = ("ok", "failed", "refused", "rate-limited", "unsupported", "needs-token")


class LakeBrowse:
    """Live portal access. Every method here makes outbound requests."""

    def __init__(
        self,
        *,
        user_key: str,
        transport_for: Callable[[LakeSourceManifest], Any],
        credential_for: Callable[[LakeSourceManifest], str | None] | None = None,
    ) -> None:
        self.user_key = user_key
        # Injected per manifest rather than one shared instance: a transport
        # may carry a per-source credential, and in tests it is the seam that
        # replaces the network entirely.
        self._transport_for = transport_for
        self._credential_for = credential_for or (lambda _m: None)

    # ── one source ─────────────────────────────────────────────────────────

    def _provider(self, manifest: LakeSourceManifest):
        auth = manifest.auth
        if auth.needs_token and not self._credential_for(manifest):
            raise CredentialRequired(
                f"{manifest.name} needs a {auth.secret_id} token before it can be used"
                + (f" - see {auth.help_url}" if auth.help_url else "")
            )
        return build_provider(manifest, self._transport_for(manifest))

    def _spend(self, manifest: LakeSourceManifest) -> None:
        ratelimit.limiter.check(self.user_key, manifest.dir_name, manifest.requests_per_minute)

    def search(self, manifest: LakeSourceManifest, query: SearchQuery) -> SearchPage:
        if not manifest.capabilities.search:
            raise CapabilityUnsupported(
                f"{manifest.name} has nothing to browse - it takes a direct link to a file"
            )
        self._spend(manifest)
        return self._provider(manifest).search(query)

    def describe(self, manifest: LakeSourceManifest, resource_id: str):
        self._spend(manifest)
        return self._provider(manifest).describe(resource_id)

    def download_target(self, manifest: LakeSourceManifest, resource_id: str, fmt: str | None):
        self._spend(manifest)
        return self._provider(manifest).download_url(resource_id, fmt)

    # ── every source ───────────────────────────────────────────────────────

    def search_all(
        self, manifests: list[LakeSourceManifest], query: SearchQuery
    ) -> tuple[list, list[dict]]:
        """Fan out. Returns ``(interleaved rows, per-source statuses)``.

        Never raises for a portal's sake. The only thing that can fail the
        whole call is something wrong with the request itself, and by this
        point that has already been validated.
        """
        legs: list[dict] = []
        searchable: list[LakeSourceManifest] = []
        for manifest in manifests:
            reason = self._why_not_searchable(manifest)
            if reason is not None:
                legs.append({"sourceId": manifest.id, **reason})
            else:
                searchable.append(manifest)

        pages: dict[str, SearchPage] = {}
        if searchable:
            # A per-source query: each leg asks for the full limit, and the
            # merge trims. Asking each for limit/N would mean a portal with one
            # good match could be crowded out by one with many mediocre ones.
            workers = min(MAX_FANOUT_WORKERS, len(searchable))
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = {
                    pool.submit(self._leg, manifest, query): manifest
                    for manifest in searchable
                }
                for future, manifest in futures.items():
                    status, page = future.result()
                    legs.append({"sourceId": manifest.id, **status})
                    if page is not None:
                        pages[manifest.id] = page

        order = [m.id for m in searchable if m.id in pages]
        rows = _interleave([pages[sid] for sid in order], query.limit)
        legs.sort(key=lambda leg: leg["sourceId"])
        return rows, legs

    def _why_not_searchable(self, manifest: LakeSourceManifest) -> dict | None:
        if not manifest.capabilities.search:
            return {"status": "unsupported", "detail": "this source has nothing to browse"}
        if manifest.auth.needs_token and not self._credential_for(manifest):
            return {
                "status": "needs-token",
                "detail": f"add a {manifest.auth.secret_id} token to search this source",
            }
        return None

    def _leg(self, manifest: LakeSourceManifest, query: SearchQuery):
        """One portal's leg of a fan-out. Converts every failure into a status.

        Deliberately broad: a provider bug, a portal returning HTML, a DNS
        failure and a policy refusal are all "this leg did not answer", and the
        other portals' rows are still worth showing. The detail carries what
        happened so the UI can say which portal and why.
        """
        try:
            self._spend(manifest)
            page = self._provider(manifest).search(query)
            return {"status": "ok", "count": len(page.resources)}, page
        except RateLimited as exc:
            return {"status": "rate-limited", "detail": str(exc)}, None
        except CredentialRequired as exc:
            return {"status": "needs-token", "detail": str(exc)}, None
        except CapabilityUnsupported as exc:
            return {"status": "unsupported", "detail": str(exc)}, None
        except egress.EgressRefused as exc:
            return {"status": "refused", "detail": str(exc)[:200]}, None
        except DataLakeError as exc:
            return {"status": "failed", "detail": str(exc)[:200]}, None
        except Exception as exc:  # noqa: BLE001 - one leg must not fail the request
            return {"status": "failed", "detail": f"{type(exc).__name__}: {exc}"[:200]}, None


def _interleave(pages: list[SearchPage], limit: int) -> list:
    """Round-robin across sources, preserving each source's own ranking.

    A portal that returns forty rows should not fill the first screen while one
    that returned three perfect matches sits below the fold.
    """
    lists = [list(page.resources) for page in pages]
    out = []
    index = 0
    while len(out) < limit and any(index < len(rows) for rows in lists):
        for rows in lists:
            if index < len(rows):
                out.append(rows[index])
                if len(out) >= limit:
                    break
        index += 1
    return out
