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


def verify_endpoint(url: str, *, request_fn=None, resolver=None, budget=None) -> dict:
    """The GENERIC probe — the universal gate for any dataset API URL."""
    try:
        result = egress.fetch(url, request_fn=request_fn, resolver=resolver, budget=budget)
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
            # The body the probe already read. Private (stripped before the
            # outcome reaches a card) and present so a refinement can enrich
            # from it instead of fetching the same URL a second time.
            "_body": result.body,
        }
    return {
        "status": "unreachable",
        "httpStatus": result.status,
        "detail": f"the endpoint answered {result.status}",
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

    def _refine(url: str, *, request_fn=None, resolver=None, budget=None) -> dict:
        resource_id = provider_module.recognize(url)
        meta_url = provider_module.metadata_url(url, resource_id) if resource_id else None
        if not meta_url:
            return verify_endpoint(
                url, request_fn=request_fn, resolver=resolver, budget=budget
            )
        outcome = verify_endpoint(
            meta_url, request_fn=request_fn, resolver=resolver, budget=budget
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


def verify_socrata(url: str, *, request_fn=None, resolver=None, budget=None) -> dict:
    """Kept as a name because tests and callers refer to it; the Socrata URL
    knowledge itself now lives in ``datalakes/providers/socrata.py``."""
    from utk_curio.backend.app.datalakes.providers import socrata

    return _refine_with(socrata)(
        url, request_fn=request_fn, resolver=resolver, budget=budget
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


def verify_external_source(url: str | None, *, request_fn=None, resolver=None, budget=None) -> dict:
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
                    url, request_fn=request_fn, resolver=resolver, budget=budget
                )
                break
        except Exception:
            continue  # a broken refinement never blocks the generic gate
    if outcome is None:
        outcome = verify_endpoint(
            url, request_fn=request_fn, resolver=resolver, budget=budget
        )
    # ``_body`` is an internal handoff between the probe and its refinement.
    # It is raw remote content and must not ride the outcome into a card.
    outcome.pop("_body", None)
    return outcome
