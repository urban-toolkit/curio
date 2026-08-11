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


def verify_endpoint(url: str, *, request_fn=None, resolver=None) -> dict:
    """The GENERIC probe — the universal gate for any dataset API URL."""
    try:
        result = egress.fetch(url, request_fn=request_fn, resolver=resolver)
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
            "checkedAt": _now(),
        }
    return {
        "status": "unreachable",
        "httpStatus": result.status,
        "detail": f"the endpoint answered {result.status}",
        "checkedAt": _now(),
    }


# Socrata URL shapes: /resource/<4x4>.<ext> or /api/views/<4x4>…
_SOCRATA_ID_RE = re.compile(r"/(?:resource|api/views)/([a-z0-9]{4}-[a-z0-9]{4})\b")


def verify_socrata(url: str, *, request_fn=None, resolver=None) -> dict:
    """The Socrata refinement: probe the dataset's metadata endpoint and
    extract its real name and columns — richer evidence over the same gate."""
    match = _SOCRATA_ID_RE.search(url)
    parsed_host = re.match(r"^(https?://[^/]+)", url)
    if not match or not parsed_host:
        return verify_endpoint(url, request_fn=request_fn, resolver=resolver)
    dataset_id = match.group(1)
    meta_url = f"{parsed_host.group(1)}/api/views/{dataset_id}.json"
    outcome = verify_endpoint(meta_url, request_fn=request_fn, resolver=resolver)
    outcome["provider"] = "socrata"
    outcome["datasetId"] = dataset_id
    if outcome["status"] != "verified":
        return outcome
    try:
        result = egress.fetch(meta_url, request_fn=request_fn, resolver=resolver)
        meta = json.loads(result.body)
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


def verify_external_source(url: str | None, *, request_fn=None, resolver=None) -> dict:
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
    for predicate, validator in _VALIDATORS:
        try:
            if predicate(url):
                return validator(url, request_fn=request_fn, resolver=resolver)
        except Exception:
            continue  # a broken refinement never blocks the generic gate
    return verify_endpoint(url, request_fn=request_fn, resolver=resolver)
