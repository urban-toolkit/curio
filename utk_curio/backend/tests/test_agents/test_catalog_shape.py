"""The Agent Catalog speaks the shared catalog API shape (Phase 1).

Three claims, each about parity with the two catalogs that came before rather
than about agents specifically:

1. ``GET /api/agents/catalog`` returns ``{"items", "facets"}`` the way
   ``GET /api/datasets/catalog`` does, because the browse page's category rail
   reads its counts straight off ``facets`` and the drawer's tab badges seed
   from it before the rows arrive.
2. The facet keys are seeded at zero, so a rail renders a complete set of rows
   instead of only the ones that happen to be populated.
3. One decorator maps service errors, a missing dataflow, and an unconfigured
   provider onto status codes, mirroring ``datasets/routes.py``.
"""

from __future__ import annotations

import pytest

from utk_curio.backend.app.agents import routes as agents_routes
from utk_curio.backend.app.agents import services as agents_services
from utk_curio.backend.app.agents.manifest import AGENT_CATEGORIES
from utk_curio.backend.app.agents.provider_config import ProviderConfigError
from utk_curio.backend.app.agents.services import AgentServiceError


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


class TestCatalogEnvelope:
    def test_returns_items_and_facets(self, client, user_and_token, tmp_curio):
        _user, token = user_and_token
        body = client.get("/api/agents/catalog", headers=_auth(token)).get_json()

        assert isinstance(body["items"], list)
        assert body["items"], "the built-in roster should never list empty"
        assert set(body["facets"]) == {"category", "origin"}

    def test_agents_alias_matches_items(self, client, user_and_token, tmp_curio):
        """The drawer still reads ``agents``; it must not drift from ``items``."""
        _user, token = user_and_token
        body = client.get("/api/agents/catalog", headers=_auth(token)).get_json()
        assert body["agents"] == body["items"]

    def test_every_category_key_is_present_even_at_zero(
        self, client, user_and_token, tmp_curio
    ):
        _user, token = user_and_token
        body = client.get("/api/agents/catalog", headers=_auth(token)).get_json()
        assert set(body["facets"]["category"]) == set(AGENT_CATEGORIES)
        assert set(body["facets"]["origin"]) == {"builtin", "published", "imported"}

    def test_facet_counts_add_up_to_the_rows(self, client, user_and_token, tmp_curio):
        _user, token = user_and_token
        body = client.get("/api/agents/catalog", headers=_auth(token)).get_json()
        total = len(body["items"])
        assert sum(body["facets"]["origin"].values()) == total
        # Every built-in declares a category from the manifest vocabulary, so
        # the category axis is total too. A row that fell outside it would show
        # up here as a short count rather than silently vanishing from the rail.
        assert sum(body["facets"]["category"].values()) == total


class TestFacetHelper:
    """Unit-level, so a counting bug is not diagnosed through an HTTP round trip."""

    def test_counts_by_category_and_origin(self):
        cards = [
            {"category": "data", "published": False, "imported": False},
            {"category": "data", "published": True, "imported": False},
            {"category": "node", "published": False, "imported": True},
        ]
        facets = agents_services.agent_catalog_facets(cards)
        assert facets["category"]["data"] == 2
        assert facets["category"]["node"] == 1
        assert facets["category"]["canvas"] == 0
        assert facets["origin"] == {"builtin": 1, "published": 1, "imported": 1}

    def test_published_wins_over_imported(self):
        """A published agent the user also imported counts once, as published."""
        facets = agents_services.agent_catalog_facets(
            [{"category": "data", "published": True, "imported": True}]
        )
        assert facets["origin"] == {"builtin": 0, "published": 1, "imported": 0}

    def test_unknown_category_does_not_invent_a_key(self):
        facets = agents_services.agent_catalog_facets([{"category": "nonsense"}])
        assert set(facets["category"]) == set(AGENT_CATEGORIES)
        assert sum(facets["category"].values()) == 0


class TestErrorDecorator:
    """The mapping, exercised directly - no route needed to prove the contract."""

    def test_service_error_keeps_its_own_status(self, app):
        @agents_routes._map_agent_errors
        def handler():
            raise AgentServiceError("nope", status=409)

        with app.test_request_context():
            body, status = handler()
        assert status == 409
        assert body.get_json() == {"error": "nope"}

    def test_service_error_defaults_to_400(self, app):
        @agents_routes._map_agent_errors
        def handler():
            exc = AgentServiceError("bad")
            del exc.status
            raise exc

        with app.test_request_context():
            _body, status = handler()
        assert status == 400

    def test_missing_dataflow_is_404(self, app):
        from utk_curio.backend.app.projects.repositories import NotFoundError

        @agents_routes._map_agent_errors
        def handler():
            raise NotFoundError("gone")

        with app.test_request_context():
            body, status = handler()
        assert status == 404
        assert body.get_json() == {"error": "Dataflow not found"}

    def test_unconfigured_provider_is_400_naming_ai_settings(self, app):
        @agents_routes._map_agent_errors
        def handler():
            raise ProviderConfigError("No AI provider is configured. Set one up in AI Settings.")

        with app.test_request_context():
            body, status = handler()
        assert status == 400
        assert "AI Settings" in body.get_json()["error"]

    def test_a_clean_return_passes_straight_through(self, app):
        @agents_routes._map_agent_errors
        def handler():
            return {"ok": True}, 200

        with app.test_request_context():
            assert handler() == ({"ok": True}, 200)
