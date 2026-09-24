"""Fanning out across portals, and surviving the ones that do not answer.

The property that matters most here is negative: **no single portal can fail
the request**. A federated search that 502s because one of five municipal
sites is having a bad afternoon is worse than no federated search, because it
turns someone else's outage into our bug report.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from utk_curio.backend.app.agents import egress
from utk_curio.backend.app.datalakes.application.browse import LakeBrowse, _interleave
from utk_curio.backend.app.datalakes.domain.errors import ProviderError, RateLimited
from utk_curio.backend.app.datalakes.domain.manifest import load_source_manifest
from utk_curio.backend.app.datalakes.domain.resource import (
    LakeResource,
    SearchPage,
    SearchQuery,
)
from utk_curio.backend.app.datalakes.infrastructure import ratelimit
from utk_curio.backend.app.datalakes.infrastructure.transport import FixtureLakeTransport
from utk_curio.backend.app.datalakes.providers import wfs as wfs_mod
from utk_curio.backend.tests.test_datalakes.conftest import SHIPPED_ROOT

FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture(autouse=True)
def _clean():
    ratelimit.limiter.reset()
    wfs_mod.WfsProvider.clear_cache()
    yield
    ratelimit.limiter.reset()
    wfs_mod.WfsProvider.clear_cache()


def manifests(*dir_names):
    return [load_source_manifest(SHIPPED_ROOT / d) for d in dir_names]


def browse(**over):
    kwargs = {
        "user_key": "alice",
        "transport_for": lambda _m: FixtureLakeTransport(FIXTURES),
    }
    kwargs.update(over)
    return LakeBrowse(**kwargs)


class TestTheHappyFanOut:
    def test_rows_come_back_from_several_portals_at_once(self):
        rows, legs = browse().search_all(
            manifests("lake.cityofchicago.data-portal@1", "lake.saopaulo.geosampa@1"),
            SearchQuery(text="ciclo", limit=10),
        )
        # Chicago has no fixture for "ciclo", so its leg fails; GeoSampa's
        # answers. The point is that the failure did not take the other with it.
        assert any(leg["status"] == "ok" for leg in legs)
        assert rows

    def test_every_source_reports_its_own_status(self):
        sources = manifests(
            "lake.saopaulo.geosampa@1",
            "lake.curio.direct-url@1",
            "lake.cityofchicago.data-portal@1",
        )
        _rows, legs = browse().search_all(sources, SearchQuery(text="ciclo", limit=5))
        by_id = {leg["sourceId"]: leg for leg in legs}
        assert set(by_id) == {m.id for m in sources}
        assert by_id["lake.saopaulo.geosampa"]["status"] == "ok"
        assert by_id["lake.curio.direct-url"]["status"] == "unsupported"

    def test_legs_are_returned_in_a_stable_order(self):
        sources = manifests("lake.saopaulo.geosampa@1", "lake.cityofchicago.data-portal@1")
        _r, first = browse().search_all(sources, SearchQuery(text="ciclo", limit=5))
        _r, second = browse().search_all(sources, SearchQuery(text="ciclo", limit=5))
        assert [x["sourceId"] for x in first] == [x["sourceId"] for x in second]


class TestPartialFailureIsData:
    def _legs_for(self, failure):
        class Boom:
            def json_get(self, *a, **k):
                raise failure

            def download(self, *a, **k):  # pragma: no cover
                raise failure

        _rows, legs = browse(transport_for=lambda _m: Boom()).search_all(
            manifests("lake.cityofchicago.data-portal@1"), SearchQuery(text="x", limit=5)
        )
        return legs[0]

    def test_a_provider_error_is_a_failed_leg_not_an_exception(self):
        leg = self._legs_for(ProviderError("the portal is confused"))
        assert leg["status"] == "failed"
        assert "confused" in leg["detail"]

    def test_a_policy_refusal_is_reported_as_refused(self):
        leg = self._legs_for(egress.EgressRefused("resolves to a private address"))
        assert leg["status"] == "refused"

    def test_a_rate_limit_is_reported_as_rate_limited(self):
        leg = self._legs_for(RateLimited("slow down"))
        assert leg["status"] == "rate-limited"

    def test_even_an_unexpected_bug_is_contained(self):
        """A provider raising something nobody anticipated must still not take
        the other portals' rows with it."""
        leg = self._legs_for(ZeroDivisionError("a provider bug"))
        assert leg["status"] == "failed"
        assert "ZeroDivisionError" in leg["detail"]

    def test_one_broken_leg_leaves_the_others_intact(self):
        good = load_source_manifest(SHIPPED_ROOT / "lake.saopaulo.geosampa@1")
        bad = load_source_manifest(SHIPPED_ROOT / "lake.cityofchicago.data-portal@1")

        class Selective:
            def __init__(self, manifest):
                self.manifest = manifest

            def json_get(self, url, **k):
                if "cityofchicago" in url:
                    raise ProviderError("down for maintenance")
                return FixtureLakeTransport(FIXTURES).json_get(url, **k)

            def download(self, *a, **k):  # pragma: no cover
                raise NotImplementedError

        rows, legs = browse(transport_for=Selective).search_all(
            [good, bad], SearchQuery(text="ciclo", limit=10)
        )
        by_id = {leg["sourceId"]: leg["status"] for leg in legs}
        assert by_id["lake.cityofchicago.data-portal"] == "failed"
        assert by_id["lake.saopaulo.geosampa"] == "ok"
        assert rows, "the working portal's rows must still be returned"


class TestWhatIsNotEvenTried:
    def test_a_source_with_no_search_is_marked_and_never_contacted(self):
        contacted = []

        class Spy:
            def json_get(self, url, **k):
                contacted.append(url)
                return "{}"

            def download(self, *a, **k):  # pragma: no cover
                raise NotImplementedError

        _rows, legs = browse(transport_for=lambda _m: Spy()).search_all(
            manifests("lake.curio.direct-url@1"), SearchQuery(text="x", limit=5)
        )
        assert legs[0]["status"] == "unsupported"
        assert contacted == [], "a link-only source must not be asked"

    def test_a_source_needing_a_token_you_lack_is_marked_needs_token(self):
        from dataclasses import replace

        base = load_source_manifest(SHIPPED_ROOT / "lake.cityofchicago.data-portal@1")
        gated = replace(base, auth=replace(base.auth, mode="required-token"))
        _rows, legs = browse().search_all([gated], SearchQuery(text="crimes", limit=5))
        assert legs[0]["status"] == "needs-token"
        assert "token" in legs[0]["detail"]

    def test_holding_the_token_lets_it_through(self):
        from dataclasses import replace

        base = load_source_manifest(SHIPPED_ROOT / "lake.cityofchicago.data-portal@1")
        gated = replace(base, auth=replace(base.auth, mode="required-token"))
        _rows, legs = browse(credential_for=lambda _m: "X-App-Token:secret").search_all(
            [gated], SearchQuery(text="crimes", limit=5)
        )
        assert legs[0]["status"] == "ok"


class TestBounds:
    def test_the_rate_limit_applies_per_leg(self):
        source = load_source_manifest(SHIPPED_ROOT / "lake.saopaulo.geosampa@1")
        b = browse()
        # Spend the bucket, then fan out: the leg reports rate-limited rather
        # than the fan-out being a way around the per-source bound.
        for _ in range(source.requests_per_minute):
            ratelimit.limiter.check("alice", source.dir_name, source.requests_per_minute)
        _rows, legs = b.search_all([source], SearchQuery(text="ciclo", limit=5))
        assert legs[0]["status"] == "rate-limited"

    def test_the_merge_respects_the_limit(self):
        rows = _interleave(
            [
                SearchPage(resources=tuple(_row(f"a{i}") for i in range(10))),
                SearchPage(resources=tuple(_row(f"b{i}") for i in range(10))),
            ],
            limit=6,
        )
        assert len(rows) == 6

    def test_rows_are_interleaved_so_no_portal_owns_the_first_screen(self):
        rows = _interleave(
            [
                SearchPage(resources=tuple(_row(f"a{i}") for i in range(4))),
                SearchPage(resources=tuple(_row(f"b{i}") for i in range(4))),
            ],
            limit=6,
        )
        assert [r.resource_id for r in rows] == ["a0", "b0", "a1", "b1", "a2", "b2"]

    def test_a_short_source_does_not_stop_the_round_robin(self):
        rows = _interleave(
            [
                SearchPage(resources=(_row("a0"),)),
                SearchPage(resources=tuple(_row(f"b{i}") for i in range(3))),
            ],
            limit=10,
        )
        assert [r.resource_id for r in rows] == ["a0", "b0", "b1", "b2"]

    def test_no_sources_is_an_empty_result_not_a_crash(self):
        rows, legs = browse().search_all([], SearchQuery(text="x", limit=5))
        assert rows == [] and legs == []


def _row(rid: str) -> LakeResource:
    return LakeResource(source_id="lake.a.b", resource_id=rid, name=rid)
