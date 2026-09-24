"""Every provider, against responses recorded from the real portal.

The corpus in ``fixtures/`` was recorded by driving these same providers
against the live sites (``scripts/record_datalake_fixtures.py``), so these
tests assert against what the portals actually answered rather than against a
hand-written idea of it. No test here opens a socket; the netguard would fail
it loudly if one tried.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from utk_curio.backend.app.datalakes.domain.errors import (
    CapabilityUnsupported,
    ResourceNotFound,
)
from utk_curio.backend.app.datalakes.domain.manifest import load_source_manifest
from utk_curio.backend.app.datalakes.domain.resource import SearchQuery
from utk_curio.backend.app.datalakes.infrastructure.transport import (
    FixtureLakeTransport,
    FixtureMissing,
)
from utk_curio.backend.app.datalakes.providers import PROVIDERS, build_provider
from utk_curio.backend.app.datalakes.providers import wfs as wfs_mod
from utk_curio.backend.tests.test_datalakes.conftest import SHIPPED_ROOT

FIXTURES = Path(__file__).resolve().parent / "fixtures"

#: The query each source's fixtures were recorded with. A different query is a
#: FixtureMissing, which is the intended behaviour: a fixture set answers the
#: questions it was recorded for and says so loudly for anything else.
RECORDED = {
    "lake.cityofchicago.data-portal@1": "crimes",
    "lake.uk.data-gov@1": "cycling",
    "lake.esri.hub-opendata@1": "bike lanes",
    "lake.saopaulo.geosampa@1": "ciclo",
}


@pytest.fixture(autouse=True)
def _clear_wfs_cache():
    # Module-level and shared between tests, so a cached capabilities document
    # would make a later test's call count wrong.
    wfs_mod.WfsProvider.clear_cache()
    yield
    wfs_mod.WfsProvider.clear_cache()


def _provider(dir_name: str):
    manifest = load_source_manifest(SHIPPED_ROOT / dir_name)
    transport = FixtureLakeTransport(FIXTURES)
    return build_provider(manifest, transport), transport, manifest


@pytest.mark.parametrize("dir_name,query", sorted(RECORDED.items()))
class TestEveryRecordedProvider:
    def test_search_returns_usable_rows(self, dir_name, query):
        provider, _, manifest = _provider(dir_name)
        page = provider.search(SearchQuery(text=query))
        assert page.resources, f"{dir_name} returned nothing for {query!r}"
        for row in page.resources:
            assert row.source_id == manifest.id
            assert row.name, "a row with no name is not selectable"
            # The id has to survive the provider's own guard, or the row is one
            # the user can see and not download.
            assert provider.resource_id_re.match(row.resource_id)

    def test_describe_resolves_the_first_row(self, dir_name, query):
        provider, _, _ = _provider(dir_name)
        first = provider.search(SearchQuery(text=query)).resources[0]
        detail = provider.describe(first.resource_id)
        assert detail.resource.resource_id == first.resource_id
        assert detail.resource.name

    def test_download_url_is_on_a_declared_format(self, dir_name, query):
        provider, _, manifest = _provider(dir_name)
        first = provider.search(SearchQuery(text=query)).resources[0]
        target = provider.download_url(first.resource_id, None)
        assert target.url.startswith("https://")
        if target.declared_format is not None:
            assert target.declared_format in manifest.capabilities.formats

    def test_an_undeclared_format_is_refused_by_name(self, dir_name, query):
        provider, _, manifest = _provider(dir_name)
        first = provider.search(SearchQuery(text=query)).resources[0]
        missing = next(
            f for f in ("csv", "geojson", "parquet", "geotiff")
            if f not in manifest.capabilities.formats
        )
        with pytest.raises(CapabilityUnsupported, match=missing):
            provider.download_url(first.resource_id, missing)

    @pytest.mark.parametrize(
        "bad", ["../../etc/passwd", "https://evil.example/x", "' OR 1=1", ""]
    )
    def test_a_malformed_resource_id_never_reaches_a_url(self, dir_name, query, bad):
        provider, transport, _ = _provider(dir_name)
        before = len(transport.calls)
        with pytest.raises(ResourceNotFound):
            provider.describe(bad)
        # Validated BEFORE any request: a rejected id must not have been sent
        # anywhere, even to be rejected by the portal.
        assert len(transport.calls) == before or all(
            bad not in call for call in transport.calls[before:]
        )


class TestSocrata:
    def test_it_reads_the_real_chicago_catalogue(self):
        provider, _, _ = _provider("lake.cityofchicago.data-portal@1")
        page = provider.search(SearchQuery(text="crimes"))
        names = [r.name for r in page.resources]
        assert any("Crimes" in n for n in names), names
        assert page.resources[0].resource_id == "ijzp-q8t2"

    def test_describe_reads_the_column_list(self):
        provider, _, _ = _provider("lake.cityofchicago.data-portal@1")
        detail = provider.describe("ijzp-q8t2")
        field_names = [f.name for f in detail.fields]
        assert "case_number" in field_names, field_names[:10]
        assert detail.resource.updated_at, "rowsUpdatedAt should become a date"

    def test_the_export_url_is_the_bulk_endpoint(self):
        provider, _, _ = _provider("lake.cityofchicago.data-portal@1")
        target = provider.download_url("ijzp-q8t2", "csv")
        assert target.url == "https://data.cityofchicago.org/resource/ijzp-q8t2.csv"
        # No $limit: that would silently truncate a dataset and hand the user a
        # partial file that looks whole. The byte cap is what bounds it.
        assert "$limit" not in target.url

    @pytest.mark.parametrize("bad", ["ijzp_q8t2", "IJZP-Q8T2", "ijzp-q8t2x", "abc-defg-hij"])
    def test_the_4x4_grammar_is_enforced(self, bad):
        provider, _, _ = _provider("lake.cityofchicago.data-portal@1")
        with pytest.raises(ResourceNotFound):
            provider.describe(bad)


class TestCkan:
    def test_one_package_becomes_one_row_per_file(self):
        """Curio's unit is the file, so a package with four CSVs is four rows.
        Flattening to one row per package would mean asking the user to pick a
        file after choosing a result, from a list we already had."""
        provider, _, _ = _provider("lake.uk.data-gov@1")
        page = provider.search(SearchQuery(text="cycling"))
        packages = {r.resource_id.split(":")[0] for r in page.resources}
        assert len(page.resources) > len(packages), "expected several files per package"

    def test_a_row_id_is_the_package_file_pair(self):
        provider, _, _ = _provider("lake.uk.data-gov@1")
        row = provider.search(SearchQuery(text="cycling")).resources[0]
        assert row.resource_id.count(":") == 1
        assert provider.resource_id_re.match(row.resource_id)

    def test_landing_links_point_at_the_public_site_not_the_api_host(self):
        """data.gov.uk serves its CKAN from ckan.publishing.service.gov.uk.
        Requests go straight to the API - a redirect is charged per hop against
        the egress budget - but a human gets sent to the site they know."""
        provider, _, _ = _provider("lake.uk.data-gov@1")
        row = provider.search(SearchQuery(text="cycling")).resources[0]
        assert row.landing_url.startswith("https://data.gov.uk/dataset/")

    def test_describe_and_download_share_one_package_fetch(self):
        """Each is one call, not two. Fetching the same document twice per
        operation is the bug CallBudget's docstring records being fixed once
        already for Socrata verification."""
        provider, transport, _ = _provider("lake.uk.data-gov@1")
        row = provider.search(SearchQuery(text="cycling")).resources[0]
        before = len(transport.calls)
        provider.describe(row.resource_id)
        assert len(transport.calls) - before == 1
        before = len(transport.calls)
        provider.download_url(row.resource_id, None)
        assert len(transport.calls) - before == 1

    def test_an_off_base_distribution_is_allowed_only_when_the_manifest_says_so(self):
        provider, _, manifest = _provider("lake.uk.data-gov@1")
        row = provider.search(SearchQuery(text="cycling")).resources[0]
        target = provider.download_url(row.resource_id, None)
        assert manifest.capabilities.allow_off_base_distributions
        assert target.url.startswith("https://")

    def test_with_the_flag_off_an_off_base_distribution_is_refused(self, monkeypatch):
        from dataclasses import replace

        provider, _, manifest = _provider("lake.uk.data-gov@1")
        row = provider.search(SearchQuery(text="cycling")).resources[0]
        target = provider.download_url(row.resource_id, None)
        if target.url.startswith(manifest.provider.base_url):
            pytest.skip("this recorded row happens to be hosted on the portal itself")
        tightened = replace(
            manifest,
            capabilities=replace(manifest.capabilities, allow_off_base_distributions=False),
        )
        strict = build_provider(tightened, FixtureLakeTransport(FIXTURES))
        with pytest.raises(ResourceNotFound, match="another host"):
            strict.download_url(row.resource_id, None)


class TestArcgis:
    def test_it_reads_the_hub_dataset_list(self):
        provider, _, _ = _provider("lake.esri.hub-opendata@1")
        page = provider.search(SearchQuery(text="bike lanes"))
        assert any("Bike" in r.name for r in page.resources)
        assert page.total_hint and page.total_hint > 1000

    def test_html_is_stripped_from_descriptions(self):
        """Hub descriptions are HTML; a card renders text, so markup would read
        as tag soup."""
        provider, _, _ = _provider("lake.esri.hub-opendata@1")
        page = provider.search(SearchQuery(text="bike lanes"))
        for row in page.resources:
            assert "<" not in row.description, row.description[:80]

    def test_a_layer_suffixed_id_is_accepted(self):
        provider, _, _ = _provider("lake.esri.hub-opendata@1")
        ids = [r.resource_id for r in provider.search(SearchQuery(text="bike lanes")).resources]
        assert any("_" in i for i in ids), ids


class TestWfs:
    def test_it_parses_the_real_geosampa_capabilities(self):
        provider, _, _ = _provider("lake.saopaulo.geosampa@1")
        page = provider.search(SearchQuery(text=""))
        assert page.total_hint == 483, "GeoSampa published 483 feature types when recorded"

    def test_search_filters_locally_against_the_catalogue(self):
        provider, _, _ = _provider("lake.saopaulo.geosampa@1")
        page = provider.search(SearchQuery(text="ciclo", limit=10))
        assert page.resources
        assert all(
            "ciclo" in (r.name + r.resource_id + r.description).lower()
            for r in page.resources
        )

    def test_a_warm_cache_makes_a_second_search_free(self):
        """Capabilities is a CATALOGUE, not a query: it lists every published
        layer and changes only when an operator publishes one. Caching it is
        what makes a WFS source nearly free inside a federated fan-out."""
        provider, transport, _ = _provider("lake.saopaulo.geosampa@1")
        provider.search(SearchQuery(text="ciclo"))
        assert len(transport.calls) == 1
        provider.search(SearchQuery(text="onibus"))
        assert len(transport.calls) == 1, "the second search should issue no request"

    def test_the_cache_expires_so_a_new_layer_is_findable(self, monkeypatch):
        provider, transport, _ = _provider("lake.saopaulo.geosampa@1")
        provider.search(SearchQuery(text="ciclo"))
        assert len(transport.calls) == 1
        monkeypatch.setattr(
            wfs_mod.time, "monotonic",
            lambda: 1e9,  # far past the TTL
        )
        provider.search(SearchQuery(text="ciclo"))
        assert len(transport.calls) == 2

    def test_describe_reads_the_feature_type_schema(self):
        provider, _, _ = _provider("lake.saopaulo.geosampa@1")
        detail = provider.describe("geoportal:bicicletario_paraciclo")
        assert detail.fields, "DescribeFeatureType should yield a field list"
        assert detail.extra.get("crs"), "capabilities carries the layer's CRS"

    def test_the_download_url_asks_for_geojson_in_wgs84(self):
        provider, _, _ = _provider("lake.saopaulo.geosampa@1")
        target = provider.download_url("geoportal:bicicletario_paraciclo", "geojson")
        assert "request=GetFeature" in target.url
        assert "outputFormat=application%2Fjson" in target.url
        assert "srsName=EPSG:4326" in target.url
        assert target.declared_format == "geojson"


class TestDirect:
    def test_it_has_nothing_to_search(self):
        provider, _, _ = _provider("lake.curio.direct-url@1")
        with pytest.raises(CapabilityUnsupported, match="search"):
            provider.search(SearchQuery(text="anything"))

    def test_the_resource_id_is_the_url(self):
        provider, _, _ = _provider("lake.curio.direct-url@1")
        url = "https://example.org/data/roads.geojson"
        detail = provider.describe(url)
        assert detail.resource.resource_id == url
        assert detail.resource.name == "roads.geojson"
        assert detail.resource.formats == ("geojson",)

    def test_the_format_comes_from_the_extension(self):
        provider, _, _ = _provider("lake.curio.direct-url@1")
        target = provider.download_url("https://example.org/a/b.csv", None)
        assert target.declared_format == "csv"

    def test_an_unknown_extension_defers_rather_than_guessing(self):
        """The detection ladder gets another chance from the response headers,
        so guessing here would only be a worse first guess."""
        provider, _, _ = _provider("lake.curio.direct-url@1")
        target = provider.download_url("https://example.org/download?id=7", None)
        assert target.declared_format is None

    @pytest.mark.parametrize(
        "bad",
        ["http://example.org/a.csv", "file:///etc/passwd", "ftp://x/y.csv",
         "javascript:alert(1)", "https://exa mple.org/a.csv"],
    )
    def test_only_https_urls_are_accepted(self, bad):
        provider, _, _ = _provider("lake.curio.direct-url@1")
        with pytest.raises(ResourceNotFound):
            provider.describe(bad)

    def test_it_never_claims_a_url_for_verify(self):
        """Claiming every https URL would shadow every other refinement, and
        the generic probe already handles an unrecognised URL correctly."""
        from utk_curio.backend.app.datalakes.providers import direct

        assert direct.recognize("https://anything.example/x") is None


class TestTheRegistry:
    def test_every_manifest_provider_type_can_be_built(self):
        for dir_name in sorted(p.name for p in SHIPPED_ROOT.iterdir() if p.is_dir()):
            manifest = load_source_manifest(SHIPPED_ROOT / dir_name)
            provider = build_provider(manifest, FixtureLakeTransport(FIXTURES))
            assert provider.type == manifest.provider.type

    def test_a_transport_is_required_not_defaulted(self):
        """Forgetting to inject a fake must be a TypeError at construction,
        not a silent real request."""
        manifest = load_source_manifest(SHIPPED_ROOT / "lake.cityofchicago.data-portal@1")
        with pytest.raises(TypeError):
            PROVIDERS["socrata"](manifest)  # type: ignore[call-arg]

    def test_an_unrecorded_url_is_a_loud_miss(self):
        provider, _, _ = _provider("lake.cityofchicago.data-portal@1")
        with pytest.raises(FixtureMissing, match="record"):
            provider.search(SearchQuery(text="something never recorded"))
