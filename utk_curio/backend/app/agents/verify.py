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


# Socrata URL shapes: /resource/<4x4>.<ext> or /api/views/<4x4>…
_SOCRATA_ID_RE = re.compile(r"/(?:resource|api/views)/([a-z0-9]{4}-[a-z0-9]{4})\b")


def verify_socrata(url: str, *, request_fn=None, resolver=None, budget=None,
                   headers=None, params=None) -> dict:
    """The Socrata refinement: probe the dataset's metadata endpoint and
    extract its real name and columns — richer evidence over the same gate."""
    match = _SOCRATA_ID_RE.search(url)
    parsed_host = re.match(r"^(https?://[^/]+)", url)
    if not match or not parsed_host:
        return verify_endpoint(url, request_fn=request_fn, resolver=resolver, budget=budget,
                               headers=headers, params=params)
    dataset_id = match.group(1)
    meta_url = f"{parsed_host.group(1)}/api/views/{dataset_id}.json"
    outcome = verify_endpoint(
        meta_url, request_fn=request_fn, resolver=resolver, budget=budget,
        headers=headers, params=params,
    )
    outcome["provider"] = "socrata"
    outcome["datasetId"] = dataset_id
    if outcome["status"] != "verified":
        return outcome
    try:
        # Reuse the probe's body. This used to re-fetch the identical URL and
        # throw the first response away, doubling the request count for every
        # Socrata row and its whole redirect chain with it.
        meta = json.loads(outcome.get("_body") or "")
        outcome["datasetName"] = str(meta.get("name") or "")[:120]
        columns = meta.get("columns") or []
        outcome["columns"] = [
            str(c.get("fieldName") or c.get("name") or "")[:60]
            for c in columns[:_SAMPLE_KEYS_MAX]
            if isinstance(c, dict)
        ]
    except Exception:
        pass  # the generic verdict stands; the refinement is best-effort
    return outcome


# The registry: URL-shape predicate → refinement. The GENERIC probe is the
# fallback for everything — the gate covers ANY dataset API connection.
_VALIDATORS: list[tuple] = [
    (lambda url: bool(_SOCRATA_ID_RE.search(url)), verify_socrata),
]


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
    for predicate, validator in _VALIDATORS:
        try:
            if predicate(url):
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

#: Content types a loader can parse directly.
_DATA_CONTENT_TYPES = (
    "json", "geo+json", "csv", "text/csv", "xml", "zip", "octet-stream",
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


def _content_type_kind(content_type: str) -> str:
    lowered = (content_type or "").lower()
    if any(marker in lowered for marker in _PAGE_CONTENT_TYPES):
        return "page"
    if any(marker in lowered for marker in _DATA_CONTENT_TYPES):
        return "data"
    return "unknown"


def classify_access(observation: dict | None) -> dict:
    """``{"access": …, "why": …}`` — whether code can fetch this row's URL.

    dev/132: the three answers of memo §3A, each traceable to the probe's own
    evidence (`DEC-053` — a verdict the runtime recorded, never a claim the
    model made):

    - ``fetchable`` — 2xx with a data body (a JSON/CSV/GeoJSON/archive content
      type, or a JSON shape sample the probe read);
    - ``manual-download`` — the data URL answered with a PAGE (``text/html``),
      or refused with a gated status (401/403/451) — a portal a person passes
      through, not an endpoint code can read;
    - ``unknown`` — nothing was probed, the policy refused the URL, or the
      answer was neither (a 404, a transport failure, an unrecognized type).
      The row says so; nothing downstream may upgrade it silently.
    """
    obs = observation if isinstance(observation, dict) else {}
    status = str(obs.get("status") or "")
    http_status = obs.get("httpStatus")
    kind = _content_type_kind(str(obs.get("contentType") or ""))
    title = str(obs.get("pageTitle") or "").strip()
    if status == "verified":
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
    if url:
        steps.append(f"Open the portal page in your browser: {url}")
    title = str(obs.get("pageTitle") or "").strip()
    if title:
        steps.append(
            f'The page answered as "{title}" — use its own download control '
            "(the portal describes the click path, not Curio)."
        )
    elif url:
        steps.append(
            "Use the page's own download control — the portal describes the "
            "click path, not Curio."
        )
    fmt = str(row.get("format") or "").strip()
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
