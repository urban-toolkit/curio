"""This Curio's own LLM endpoints, as a test stands in for the operator's
endpoint file (``config.DEFAULT_LLM_ENDPOINTS``, read at call time).

Fake names, hosts and keys only.
"""

from __future__ import annotations

import dataclasses

from utk_curio.common.llm_endpoint import Endpoint

#: The suite's stand-in endpoint: unroutable on purpose, so a test that forgot
#: to stub a call fails loudly rather than reaching anything.
TEST_ENDPOINT = Endpoint(
    name="Test gateway", api_type="openai_compatible", base_url="http://127.0.0.1:9/v1",
    api_key="test-key", models=("test-model",),
)


def endpoint(name: str = TEST_ENDPOINT.name, **fields) -> Endpoint:
    """An endpoint like the suite's, with *fields* changed."""
    return dataclasses.replace(TEST_ENDPOINT, name=name, **fields)


def offer(monkeypatch, *endpoints: Endpoint) -> tuple[Endpoint, ...]:
    """Make *endpoints* this Curio's own, in order: the first one's first
    model is the Deployment default. With none, Curio offers no endpoint."""
    from utk_curio.backend import config

    monkeypatch.setattr(config, "DEFAULT_LLM_ENDPOINTS", tuple(endpoints))
    return tuple(endpoints)


def change_first(monkeypatch, **fields) -> Endpoint:
    """Change the first endpoint on offer (its URL, key, provider or models)."""
    from utk_curio.backend import config

    first, *rest = config.DEFAULT_LLM_ENDPOINTS
    changed = dataclasses.replace(first, **fields)
    offer(monkeypatch, changed, *rest)
    return changed


def withdraw(monkeypatch) -> None:
    """No endpoint file: Curio offers no endpoint and no Deployment default."""
    offer(monkeypatch)
