"""Deterministic external-source validators (memo dev/67-4, DEC-053) —
model-free, over the egress policy.

**Provider-agnostic by design (the owner's scope directive): the Socrata
hallucination fix generalizes to ANY dataset API connection.** The generic
endpoint probe is the universal gate every external source passes through
(reachability, HTTP status, content type, response-shape sample); provider-
specific validators — Socrata today — are REFINEMENTS in ``_VALIDATORS``,
keyed by recognizable URL shapes, each adding richer evidence (dataset name,
columns) on top of the generic verdict. Adding a provider (CKAN, ArcGIS,
Data.gov, …) is one registry entry, never a new gate.

Outcomes are honest data:
- ``verified`` — the endpoint answered 2xx; evidence carries what was seen;
- ``unreachable`` — it answered an error status or the transport failed;
- ``refused`` — the egress policy refused the URL (SSRF shapes, schemes);
- ``unverified`` — nothing probeable (no URL): stated loudly, never implied.
"""

from __future__ import annotations

import json
import re
import time
from urllib.parse import urlparse

from utk_curio.backend.app.agents import egress

_SAMPLE_KEYS_MAX = 12
_DETAIL_MAX = 200


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _sample_shape(body: str, content_type: str) -> dict:
    """A bounded response-shape sample: top-level keys of a JSON object, the
    first row's keys of a JSON list — never the data itself."""
    if "json" not in (content_type or "").lower():
        return {}
    try:
        payload = json.loads(body)
    except (ValueError, TypeError):
        return {}
    if isinstance(payload, dict):
        return {"sampleKeys": sorted(payload.keys())[:_SAMPLE_KEYS_MAX]}
    if isinstance(payload, list) and payload and isinstance(payload[0], dict):
        return {
            "sampleKeys": sorted(payload[0].keys())[:_SAMPLE_KEYS_MAX],
            "rows": len(payload),
        }
    return {}


_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
_PAGE_TITLE_MAX = 80
_BODY_SAMPLE_MAX = 120


def _body_evidence(body: str, content_type: str) -> dict:
    """What a NON-data answer looked like, bounded and tag-free: the page title
    of an HTML answer (a "Missing Key" page, a login page), the head of a
    plain-text one (an API's error sentence). JSON answers are described by
    :func:`_sample_shape` instead. Never the data itself — a short, stripped
    fragment the correction and the card can name (dev/115 field fix)."""
    lowered = (content_type or "").lower()
    if "json" in lowered or not body:
        return {}
    if "html" in lowered or body.lstrip()[:1] == "<":
        match = _TITLE_RE.search(body)
        title = " ".join(_TAG_RE.sub(" ", match.group(1)).split()) if match else ""
        return {"pageTitle": title[:_PAGE_TITLE_MAX]} if title else {}
    sample = " ".join(_TAG_RE.sub(" ", body[: _BODY_SAMPLE_MAX * 4]).split())
    return {"bodySample": sample[:_BODY_SAMPLE_MAX]} if sample else {}


def _redirect_evidence(url: str, result) -> dict:
    final = getattr(result, "final_url", None)
    return {"finalUrl": final[:_DETAIL_MAX]} if isinstance(final, str) and final and final != url else {}


def verify_endpoint(url: str, *, request_fn=None, resolver=None, budget=None,
                    headers=None, params=None) -> dict:
    """The GENERIC probe — the universal gate for any dataset API URL.
    ``headers``/``params`` (dev/116): a keyed probe sends a saved connection
    key the way the API expects it; the caller redacts the outcome."""
    try:
        result = egress.fetch(url, request_fn=request_fn, resolver=resolver, budget=budget,
                              headers=headers, params=params)
    except egress.EgressRefused as exc:
        return {"status": "refused", "detail": str(exc)[:_DETAIL_MAX], "checkedAt": _now()}
    except Exception as exc:  # transport: unreachable, never a policy claim
        return {
            "status": "unreachable",
            "detail": str(exc)[:_DETAIL_MAX],
            "checkedAt": _now(),
        }
    if 200 <= result.status < 300:
        return {
            "status": "verified",
            "httpStatus": result.status,
            "contentType": result.content_type[:100],
            **_sample_shape(result.body, result.content_type),
            **_body_evidence(result.body, result.content_type),
            **_redirect_evidence(result.url, result),
            "checkedAt": _now(),
            # The body the probe already read. Private (stripped before the
            # outcome reaches a card) and present so a refinement can enrich
            # from it instead of fetching the same URL a second time.
            "_body": result.body,
        }
    return {
        "status": "unreachable",
        "httpStatus": result.status,
        "contentType": result.content_type[:100],
        "detail": f"the endpoint answered {result.status}",
        **_body_evidence(result.body, result.content_type),
        **_redirect_evidence(result.url, result),
        "checkedAt": _now(),
    }


def _refine_with(provider_module):
    """Build the refinement for one provider family.

    The shape is always the same - recognise the id, probe that provider's
    metadata endpoint, read evidence out of the body the probe already
    fetched - so it is written once here rather than once per provider. What
    varies (the URL shape, the metadata endpoint, what counts as evidence)
    lives in the provider module, which is the only place that knows it.
    """

    def _refine(url: str, *, request_fn=None, resolver=None, budget=None,
                headers=None, params=None) -> dict:
        resource_id = provider_module.recognize(url)
        meta_url = provider_module.metadata_url(url, resource_id) if resource_id else None
        if not meta_url:
            return verify_endpoint(
                url, request_fn=request_fn, resolver=resolver, budget=budget,
                headers=headers, params=params
            )
        outcome = verify_endpoint(
            meta_url, request_fn=request_fn, resolver=resolver, budget=budget,
            headers=headers, params=params
        )
        outcome["provider"] = provider_module.PROVIDER_TYPE
        outcome["datasetId"] = resource_id
        if outcome["status"] != "verified":
            return outcome
        try:
            # Reuse the probe's body. This used to re-fetch the identical URL
            # and throw the first response away, doubling the request count for
            # every Socrata row and its whole redirect chain with it.
            body = outcome.get("_body") or ""
            payload = body if provider_module.EVIDENCE_TAKES_TEXT else json.loads(body)
            outcome.update(provider_module.metadata_evidence(payload))
        except Exception:
            pass  # the generic verdict stands; the refinement is best-effort
        return outcome

    return _refine


def verify_socrata(url: str, *, request_fn=None, resolver=None, budget=None,
                   headers=None, params=None) -> dict:
    """Kept as a name because tests and callers refer to it; the Socrata URL
    knowledge itself now lives in ``datalakes/providers/socrata.py``."""
    from utk_curio.backend.app.datalakes.providers import socrata

    return _refine_with(socrata)(
        url, request_fn=request_fn, resolver=resolver, budget=budget,
        headers=headers, params=params
    )


def _validators() -> list[tuple]:
    """URL-shape recogniser → refinement, one entry per provider family.

    Imported lazily so ``agents`` does not pull the datalakes package in at
    import time. The dependency direction (agents → datalakes.providers) is the
    right way round: agents already reaches into ``packages`` and ``datasets``
    the same way, per ADR-AG-007.
    """
    from utk_curio.backend.app.datalakes.providers import RECOGNISERS

    return [(module.recognize, _refine_with(module)) for module in RECOGNISERS]


class _LazyValidators(list):
    """``_VALIDATORS`` stayed a module-level list for the sake of anything that
    reads it; it fills itself on first use so the import stays lazy."""

    def _ensure(self):
        if not list.__len__(self):
            self.extend(_validators())
        return self

    def __iter__(self):
        return list.__iter__(self._ensure())

    def __len__(self):
        return list.__len__(self._ensure())


# The registry: URL-shape recogniser → refinement. The GENERIC probe is the
# fallback for everything - the gate covers ANY dataset API connection, and a
# provider only ever adds richer evidence on top of the same verdict.
_VALIDATORS: list = _LazyValidators()


def verify_external_source(url: str | None, *, request_fn=None, resolver=None, budget=None,
                           headers=None, params=None) -> dict:
    """The one entry the Dataset Finder gate and the researcher enrichment
    call: dispatch to the matching refinement, else the generic probe; no
    URL at all is an honest ``unverified``."""
    if not isinstance(url, str) or not url.strip():
        return {
            "status": "unverified",
            "detail": "no probeable URL — the identifier was never checked",
            "checkedAt": _now(),
        }
    url = url.strip()
    outcome = None
    for recognize, validator in _VALIDATORS:
        try:
            # A recogniser returns the provider-native id, or None. Truthiness
            # is the predicate.
            if recognize(url):
                outcome = validator(
                    url, request_fn=request_fn, resolver=resolver, budget=budget,
                    headers=headers, params=params,
                )
                break
        except Exception:
            continue  # a broken refinement never blocks the generic gate
    if outcome is None:
        outcome = verify_endpoint(
            url, request_fn=request_fn, resolver=resolver, budget=budget,
            headers=headers, params=params,
        )
    # ``_body`` is an internal handoff between the probe and its refinement.
    # It is raw remote content and must not ride the outcome into a card.
    outcome.pop("_body", None)
    return outcome


# --- dev/132: what a verified row actually gives you --------------------------
#
# The owner's instruction splits the external lane in two: a row the runtime can
# FETCH (delegate the code) and a row a human must DOWNLOAD from a portal
# (teach the steps, then import). That split is not a guess — it is read from
# what the probe above already observed: the content type it got back, the HTTP
# status, and the page title of a non-data answer. Nothing here issues a
# request; `classify_access` is a pure function of one observation.

#: Content types a loader can parse directly. Archives are not among them:
#: the Data Lake refuses them (``datalakes/domain/formats.py``), so a person
#: unpacks one and imports the file.
_DATA_CONTENT_TYPES = (
    "json", "geo+json", "csv", "text/csv", "xml", "octet-stream",
    "spreadsheet", "excel", "parquet", "x-netcdf", "geopackage", "shapefile",
)
#: Content types that are a PAGE about the data, never the data.
_PAGE_CONTENT_TYPES = ("html", "xhtml")
#: Statuses whose page-shaped answer means "a human must go through the portal".
_GATED_STATUSES = (401, 403, 451)

ACCESS_FETCHABLE = "fetchable"
ACCESS_MANUAL = "manual-download"
ACCESS_UNKNOWN = "unknown"

_ACCESS_WHY_MAX = 160
_STEP_MAX_CHARS = 200
_STEPS_MAX = 6


def _is_archive(content_type: str, url: str | None) -> bool:
    """Whether the answer is an archive, by the Data Lake's own table: its
    content type (parameters such as ``charset`` stripped) or the URL's suffix."""
    from utk_curio.backend.app.datalakes.domain import formats

    if formats.content_type_of({"Content-Type": content_type}) in formats.ARCHIVE_CONTENT_TYPES:
        return True
    path = urlparse(url or "").path.lower()
    return path.endswith(formats.ARCHIVE_SUFFIXES)


def _content_type_kind(content_type: str, url: str | None = None) -> str:
    lowered = (content_type or "").lower()
    if any(marker in lowered for marker in _PAGE_CONTENT_TYPES):
        return "page"
    if _is_archive(content_type, url):
        return "archive"
    if any(marker in lowered for marker in _DATA_CONTENT_TYPES):
        return "data"
    return "unknown"


def classify_access(observation: dict | None, url: str | None = None) -> dict:
    """``{"access": …, "why": …}`` — whether code can fetch this row's URL.

    dev/132: the three answers of memo §3A, each traceable to the probe's own
    evidence (`DEC-053` — a verdict the runtime recorded, never a claim the
    model made):

    - ``fetchable`` — 2xx with a data body (a JSON/CSV/GeoJSON/archive content
      type, or a JSON shape sample the probe read);
    - ``manual-download`` — the data URL answered with a PAGE (``text/html``),
      or refused with a gated status (401/403/451) — a portal a person passes
      through, not an endpoint code can read; or with an archive, which a
      person unpacks before importing the file;
    - ``unknown`` — nothing was probed, the policy refused the URL, or the
      answer was neither (a 404, a transport failure, an unrecognized type).
      The row says so; nothing downstream may upgrade it silently.
    """
    obs = observation if isinstance(observation, dict) else {}
    status = str(obs.get("status") or "")
    http_status = obs.get("httpStatus")
    kind = _content_type_kind(str(obs.get("contentType") or ""), obs.get("finalUrl") or url)
    title = str(obs.get("pageTitle") or "").strip()
    if status == "verified":
        if kind == "archive":
            why = (
                f"the URL serves an archive ({obs.get('contentType') or 'by its suffix'}), "
                "which Curio does not unpack"
            )
            return {"access": ACCESS_MANUAL, "why": why[:_ACCESS_WHY_MAX]}
        if kind == "data" or obs.get("sampleKeys"):
            detail = (
                f"the endpoint answered {http_status or 200} with "
                f"{obs.get('contentType') or 'a data body'}"
            )
            return {"access": ACCESS_FETCHABLE, "why": detail[:_ACCESS_WHY_MAX]}
        if kind == "page":
            why = "the data URL answered with a web page"
            if title:
                why += f' titled "{title}"'
            return {"access": ACCESS_MANUAL, "why": why[:_ACCESS_WHY_MAX]}
        return {
            "access": ACCESS_UNKNOWN,
            "why": (
                f"answered {http_status or 200} with "
                f"{obs.get('contentType') or 'no content type'} — not recognized as data"
            )[:_ACCESS_WHY_MAX],
        }
    if status == "unreachable" and http_status in _GATED_STATUSES:
        why = f"the data URL answered {http_status} — the portal gates it"
        if title:
            why += f' ("{title}")'
        return {"access": ACCESS_MANUAL, "why": why[:_ACCESS_WHY_MAX]}
    if status == "refused":
        return {
            "access": ACCESS_UNKNOWN,
            "why": ("the egress policy refused the URL — nothing was observed")[:_ACCESS_WHY_MAX],
        }
    detail = str(obs.get("detail") or "the URL was never checked")
    return {"access": ACCESS_UNKNOWN, "why": detail[:_ACCESS_WHY_MAX]}


def download_steps(row: dict | None, observation: dict | None) -> list[str]:
    """The steps for a ``manual-download`` row — the portal's own description.

    dev/132 (R4): every line comes from the row's metadata or from what the
    probe observed. Nothing invents a click path: when the page title is all
    the portal gave, that is what the step says, and the framing is explicit
    about it. Bounded (6 steps, 200 chars each) like every other minted field.
    """
    row = row if isinstance(row, dict) else {}
    obs = observation if isinstance(observation, dict) else {}
    url = str(obs.get("finalUrl") or row.get("url") or "").strip()
    steps: list[str] = []
    title = str(obs.get("pageTitle") or "").strip()
    fmt = str(row.get("format") or "").strip()
    if url and _is_archive(str(obs.get("contentType") or ""), url):
        steps.append(f"Download the archive: {url}")
        steps.append("Unpack it and keep the data file inside (Curio does not unpack archives).")
    else:
        if url:
            steps.append(f"Open the portal page in your browser: {url}")
        if title:
            steps.append(
                f'The page answered as "{title}"; use its own download control '
                "(the portal describes the click path, not Curio)."
            )
        elif url:
            steps.append(
                "Use the page's own download control; the portal describes the "
                "click path, not Curio."
            )
        if fmt:
            steps.append(f"Save the {fmt} file the portal offers.")
    requirement = str(row.get("requirement") or "").strip()
    if requirement:
        steps.append(f"The row states this requirement: {requirement}")
    steps.append(
        "Then use Import dataset below: it registers the file in this "
        "project's Data Catalog, and the node is built from it."
    )
    return [step[:_STEP_MAX_CHARS] for step in steps[:_STEPS_MAX]]
