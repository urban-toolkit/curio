"""Every provider, against responses recorded from the real portal.

The corpus in ``fixtures/`` was recorded by driving these same providers
against the live sites (``scripts/record_discovery_fixtures.py``), so these
tests assert against what the portals actually answered rather than against a
hand-written idea of it. No test here opens a socket; the netguard would fail
it loudly if one tried.
"""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from utk_curio.backend.app.discovery.domain.errors import (
    CapabilityUnsupported,
    ResourceNotFound,
)
from utk_curio.backend.app.discovery.domain.manifest import load_source_manifest
from utk_curio.backend.app.discovery.domain.resource import SearchQuery
from utk_curio.backend.app.discovery.infrastructure.transport import (
    FixtureDiscoveryTransport,
    FixtureMissing,
)
from utk_curio.backend.app.discovery.providers import PROVIDERS, build_provider
from utk_curio.backend.app.discovery.providers import wfs as wfs_mod
from utk_curio.backend.tests.test_discovery.conftest import SHIPPED_ROOT

FIXTURES = Path(__file__).resolve().parent / "fixtures"

#: The query each source's fixtures were recorded with. A different query is a
#: FixtureMissing, which is the intended behaviour: a fixture set answers the
#: questions it was recorded for and says so loudly for anything else.
RECORDED = {
    "source.cityofchicago.data-portal@1": "crimes",
    "source.uk.data-gov@1": "cycling",
    "source.esri.hub-opendata@1": "bike lanes",
    "source.saopaulo.geosampa@1": "ciclo",
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
    transport = FixtureDiscoveryTransport(FIXTURES)
    return build_provider(manifest, transport), transport, manifest


class _OneDocument:
    """A transport that answers every request with the same document."""

    def __init__(self, body: str) -> None:
        self.body = body
        self.calls: list[str] = []

    def json_get(self, url, **_kwargs):
        self.calls.append(url)
        return self.body

    def download(self, *_args, **_kwargs):  # pragma: no cover
        raise NotImplementedError


#: Five layers, two of them named outside the ``workspace:layer`` grammar.
_CAPABILITIES = """<?xml version="1.0" encoding="UTF-8"?>
<wfs:WFS_Capabilities xmlns:wfs="http://www.opengis.net/wfs/2.0" version="2.0.0">
  <wfs:FeatureTypeList>
    <wfs:FeatureType><wfs:Name>no-workspace</wfs:Name><wfs:Title>Layer</wfs:Title></wfs:FeatureType>
    <wfs:FeatureType><wfs:Name>ws:first</wfs:Name><wfs:Title>Layer</wfs:Title></wfs:FeatureType>
    <wfs:FeatureType><wfs:Name>1ws:digit</wfs:Name><wfs:Title>Layer</wfs:Title></wfs:FeatureType>
    <wfs:FeatureType><wfs:Name>ws:second</wfs:Name><wfs:Title>Layer</wfs:Title></wfs:FeatureType>
    <wfs:FeatureType><wfs:Name>ws:third</wfs:Name><wfs:Title>Layer</wfs:Title></wfs:FeatureType>
  </wfs:FeatureTypeList>
</wfs:WFS_Capabilities>
"""


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
        provider, _, _ = _provider("source.cityofchicago.data-portal@1")
        page = provider.search(SearchQuery(text="crimes"))
        names = [r.name for r in page.resources]
        assert any("Crimes" in n for n in names), names
        assert page.resources[0].resource_id == "ijzp-q8t2"

    def test_describe_reads_the_column_list(self):
        provider, _, _ = _provider("source.cityofchicago.data-portal@1")
        detail = provider.describe("ijzp-q8t2")
        field_names = [f.name for f in detail.fields]
        assert "case_number" in field_names, field_names[:10]
        assert detail.resource.updated_at, "rowsUpdatedAt should become a date"

    def test_the_export_url_is_the_bulk_endpoint_with_a_limit(self):
        """SODA answers 1,000 rows to an export that names no ``$limit``: the
        Chicago crimes export came back with exactly 1,000 of its 8.6 million
        rows on 2026-10-01. So the export names one, and the byte cap is what
        bounds the download."""
        from utk_curio.backend.app.discovery.providers.socrata import EXPORT_LIMIT

        provider, _, _ = _provider("source.cityofchicago.data-portal@1")
        target = provider.download_url("ijzp-q8t2", "csv")
        assert target.url == (
            f"https://data.cityofchicago.org/resource/ijzp-q8t2.csv?$limit={EXPORT_LIMIT}"
        )
        assert EXPORT_LIMIT >= 2**31 - 1

    @pytest.mark.parametrize("bad", ["ijzp_q8t2", "IJZP-Q8T2", "ijzp-q8t2x", "abc-defg-hij"])
    def test_the_4x4_grammar_is_enforced(self, bad):
        provider, _, _ = _provider("source.cityofchicago.data-portal@1")
        with pytest.raises(ResourceNotFound):
            provider.describe(bad)


class TestCkan:
    def test_one_package_becomes_one_row_per_file(self):
        """Curio's unit is the file, so a package with four CSVs is four rows.
        Flattening to one row per package would mean asking the user to pick a
        file after choosing a result, from a list we already had."""
        provider, _, _ = _provider("source.uk.data-gov@1")
        page = provider.search(SearchQuery(text="cycling"))
        packages = {r.resource_id.split(":")[0] for r in page.resources}
        assert len(page.resources) > len(packages), "expected several files per package"

    def test_a_row_id_is_the_package_file_pair(self):
        provider, _, _ = _provider("source.uk.data-gov@1")
        row = provider.search(SearchQuery(text="cycling")).resources[0]
        assert row.resource_id.count(":") == 1
        assert provider.resource_id_re.match(row.resource_id)

    def test_landing_links_point_at_the_public_site_not_the_api_host(self):
        """data.gov.uk serves its CKAN from ckan.publishing.service.gov.uk.
        Requests go straight to the API - a redirect is charged per hop against
        the egress budget - but a human gets sent to the site they know."""
        provider, _, _ = _provider("source.uk.data-gov@1")
        row = provider.search(SearchQuery(text="cycling")).resources[0]
        assert row.landing_url.startswith("https://data.gov.uk/dataset/")

    def test_describe_and_download_share_one_package_fetch(self):
        """Each is one call, not two. Fetching the same document twice per
        operation is the bug CallBudget's docstring records being fixed once
        already for Socrata verification."""
        provider, transport, _ = _provider("source.uk.data-gov@1")
        row = provider.search(SearchQuery(text="cycling")).resources[0]
        before = len(transport.calls)
        provider.describe(row.resource_id)
        assert len(transport.calls) - before == 1
        before = len(transport.calls)
        provider.download_url(row.resource_id, None)
        assert len(transport.calls) - before == 1

    def test_an_off_base_distribution_is_allowed_only_when_the_manifest_says_so(self):
        provider, _, manifest = _provider("source.uk.data-gov@1")
        row = provider.search(SearchQuery(text="cycling")).resources[0]
        target = provider.download_url(row.resource_id, None)
        assert manifest.capabilities.allow_off_base_distributions
        assert target.url.startswith("https://")

    def test_with_the_flag_off_an_off_base_distribution_is_refused(self, monkeypatch):
        from dataclasses import replace

        provider, _, manifest = _provider("source.uk.data-gov@1")
        row = provider.search(SearchQuery(text="cycling")).resources[0]
        target = provider.download_url(row.resource_id, None)
        if target.url.startswith(manifest.provider.base_url):
            pytest.skip("this recorded row happens to be hosted on the portal itself")
        tightened = replace(
            manifest,
            capabilities=replace(manifest.capabilities, allow_off_base_distributions=False),
        )
        strict = build_provider(tightened, FixtureDiscoveryTransport(FIXTURES))
        with pytest.raises(ResourceNotFound, match="another host"):
            strict.download_url(row.resource_id, None)


class TestArcgis:
    def test_it_reads_the_hub_dataset_list(self):
        provider, _, _ = _provider("source.esri.hub-opendata@1")
        page = provider.search(SearchQuery(text="bike lanes"))
        assert any("Bike" in r.name for r in page.resources)
        assert page.total_hint and page.total_hint > 1000

    def test_html_is_stripped_from_descriptions(self):
        """Hub descriptions are HTML; a card renders text, so markup would read
        as tag soup."""
        provider, _, _ = _provider("source.esri.hub-opendata@1")
        page = provider.search(SearchQuery(text="bike lanes"))
        for row in page.resources:
            assert "<" not in row.description, row.description[:80]

    def test_a_layer_suffixed_id_is_accepted(self):
        provider, _, _ = _provider("source.esri.hub-opendata@1")
        ids = [r.resource_id for r in provider.search(SearchQuery(text="bike lanes")).resources]
        assert any("_" in i for i in ids), ids


class _Answer:
    """What ``requests.request`` returns, for the real transport to read."""

    def __init__(self, body: bytes) -> None:
        self.status_code = 200
        self.headers = {"Content-Type": "application/json"}
        self._body = body

    def iter_content(self, chunk_size=8192):
        for start in range(0, len(self._body), chunk_size):
            yield self._body[start:start + chunk_size]

    def close(self) -> None:
        pass


class _ArcgisSearchPortal:
    """hub.arcgis.com's ``/api/v3/datasets`` search, as it answered on 2026-10-17.

    Every row carries every attribute, unless the request names some in a
    JSON:API sparse fieldset (``fields[datasets]=name,owner``): then it carries
    only those. Each row here is a census tract layer of 160 columns, which a
    full answer carries four times over (``fields``, ``layer``, ``layers`` and
    ``statistics``) along with the layer's metadata, as CDC's SVI 2020 layers
    do. "SVI 2020 tract" at 20 rows answered 2,674,086 bytes that day.
    """

    TOTAL = 645346
    COLUMNS = 160

    def __init__(self) -> None:
        self.asked: list[str] = []

    @classmethod
    def row(cls, n: int) -> dict:
        columns = [
            {
                "name": f"EP_COLUMN_{c}", "alias": f"Percentage estimate {c}, 2016-2020 ACS",
                "type": "esriFieldTypeDouble", "length": 8, "nullable": True, "editable": True,
                "domain": None, "defaultValue": None, "sqlType": "sqlTypeOther",
            }
            for c in range(cls.COLUMNS)
        ]
        attributes = {
            "name": f"SVI2020 tract layer {n}",
            "description": f"<p>CDC/ATSDR <b>Social Vulnerability Index</b> 2020, census tracts ({n}).</p>",
            "owner": f"publisher_{n}",
            "orgName": f"Organization {n}",
            "modified": 1700000000000 + n,
            "fields": columns,
            "layer": {"id": 2, "name": "SVI2020_US_tract", "geometryType": "esriGeometryPolygon",
                      "fields": columns},
            "layers": [{"id": 2, "name": "SVI2020_US_tract", "fields": columns}],
            "statistics": {
                column["name"]: {"min": 0.0, "max": 100.0, "mean": 28.4, "count": 84122, "nulls": 0}
                for column in columns
            },
            "metadata": {"dataIdInfo": {"idAbs": "How vulnerable each census tract is. " * 300}},
        }
        if n % 5 == 0:
            # A row whose publisher is its organization: it names no owner.
            del attributes["owner"]
        return {"id": f"{n:032x}_2", "type": "dataset", "attributes": attributes}

    def body_for(self, url: str) -> bytes:
        query = parse_qs(urlsplit(url).query)
        size = int(query["page[size]"][0])
        first = (int(query["page[number]"][0]) - 1) * size + 1
        asked = query.get("fields[datasets]")
        data = []
        for n in range(first, first + size):
            entry = self.row(n)
            if asked:
                kept = set(asked[0].split(","))
                entry["attributes"] = {k: v for k, v in entry["attributes"].items() if k in kept}
            data.append(entry)
        return json.dumps({"data": data, "meta": {"stats": {"totalCount": self.TOTAL}}}).encode()

    def __call__(self, method, url, **_kwargs):
        self.asked.append(url)
        return _Answer(self.body_for(url))


@pytest.fixture()
def arcgis_portal(monkeypatch):
    """The stand-in, behind the real transport: no request leaves the process."""
    import requests

    from utk_curio.backend.app.common import egress_policy

    portal = _ArcgisSearchPortal()
    monkeypatch.setattr(egress_policy, "_default_resolver", lambda host: ["93.184.216.34"])
    monkeypatch.setattr(requests, "request", portal)
    return portal


class TestASearchWhoseFullAnswerPassesTheMetadataCap:
    """#967: the ArcGIS Hub Open Data source answers a search even when
    hub.arcgis.com's full answer is over the transport's ``MAX_METADATA_BYTES``.

    On 2026-10-17 "SVI 2020 tract", "Social Vulnerability Index 2020", "NHD
    flowline" and "National Hydrography Dataset" failed at the UI's 20 rows:
    the search across sources said "ArcGIS Hub Open Data did not answer", and
    the source's own page said "hub.arcgis.com returned more than 1048576
    bytes of metadata". These drive the real transport, its cap included.
    """

    QUERY = "SVI 2020 tract"

    def _browse(self):
        from utk_curio.backend.app.discovery.application.browse import DiscoveryBrowse
        from utk_curio.backend.app.discovery.infrastructure.transport import HttpDiscoveryTransport

        manifest = load_source_manifest(SHIPPED_ROOT / "source.esri.hub-opendata@1")
        browse = DiscoveryBrowse(user_key="u-arcgis", transport_for=lambda _m: HttpDiscoveryTransport())
        return browse, manifest

    def _full_answer_is_over_the_cap(self, portal, manifest, limit):
        from utk_curio.backend.app.discovery.infrastructure.transport import MAX_METADATA_BYTES

        full = portal.body_for(
            f"{manifest.provider.base_url}/api/v3/datasets"
            f"?page[size]={limit}&page[number]=1&q=SVI%202020%20tract"
        )
        assert len(full) > MAX_METADATA_BYTES, "the stand-in answers less than hub.arcgis.com did"

    def test_a_search_across_sources_gets_every_row_with_what_its_card_shows(self, arcgis_portal):
        from utk_curio.backend.app.discovery.service import DEFAULT_SEARCH_LIMIT

        browse, manifest = self._browse()
        self._full_answer_is_over_the_cap(arcgis_portal, manifest, DEFAULT_SEARCH_LIMIT)

        rows, legs = browse.search_all(
            [manifest], SearchQuery(text=self.QUERY, limit=DEFAULT_SEARCH_LIMIT)
        )

        assert legs == [{"sourceId": manifest.id, "status": "ok", "count": DEFAULT_SEARCH_LIMIT}]
        expected = [_ArcgisSearchPortal.row(n) for n in range(1, DEFAULT_SEARCH_LIMIT + 1)]
        assert [r.resource_id for r in rows] == [e["id"] for e in expected]
        for row, entry in zip(rows, expected):
            attributes = entry["attributes"]
            assert row.name == attributes["name"]
            assert row.publisher == attributes.get("owner", attributes["orgName"])
            assert row.updated_at == str(attributes["modified"])
            assert row.description.startswith("CDC/ATSDR Social Vulnerability Index 2020, census tracts")

    def test_the_sources_own_page_keeps_the_count_and_shows_more(self, arcgis_portal):
        from utk_curio.backend.app.discovery.service import DEFAULT_SEARCH_LIMIT

        browse, manifest = self._browse()
        self._full_answer_is_over_the_cap(arcgis_portal, manifest, DEFAULT_SEARCH_LIMIT)

        page = browse.search(manifest, SearchQuery(text=self.QUERY, limit=DEFAULT_SEARCH_LIMIT))

        assert len(page.resources) == DEFAULT_SEARCH_LIMIT
        assert page.total_hint == _ArcgisSearchPortal.TOTAL
        assert page.next_cursor == "2"
        more = browse.search(
            manifest,
            SearchQuery(text=self.QUERY, limit=DEFAULT_SEARCH_LIMIT, cursor=page.next_cursor),
        )
        assert [r.resource_id for r in more.resources] == [
            _ArcgisSearchPortal.row(n)["id"]
            for n in range(DEFAULT_SEARCH_LIMIT + 1, 2 * DEFAULT_SEARCH_LIMIT + 1)
        ]


class TestWfs:
    def test_it_parses_the_real_geosampa_capabilities(self):
        provider, _, _ = _provider("source.saopaulo.geosampa@1")
        page = provider.search(SearchQuery(text=""))
        assert page.total_hint == 483, "GeoSampa published 483 feature types when recorded"

    def test_search_filters_locally_against_the_catalogue(self):
        provider, _, _ = _provider("source.saopaulo.geosampa@1")
        page = provider.search(SearchQuery(text="ciclo", limit=10))
        assert page.resources
        assert all(
            "ciclo" in (r.name + r.resource_id + r.description).lower()
            for r in page.resources
        )

    @pytest.mark.parametrize(
        "query,first",
        [
            ("distrito municipal", "geoportal:distrito_municipal"),  # title "Distrito"
            ("ponto onibus", "geoportal:ponto_onibus"),  # title "Pontos de ônibus"
            ("onibus ponto", "geoportal:ponto_onibus"),
            ("ponto de ônibus", "geoportal:ponto_onibus"),
            ("pontos onibus", "geoportal:ponto_onibus"),
            ("distritos", "geoportal:distrito_municipal"),
        ],
    )
    def test_each_word_matches_on_its_own_and_the_layer_they_name_comes_first(self, query, first):
        """Words match separately, in any order, with or without accents, and
        a plural finds its singular. The layer whose name or title holds the
        most of them is first."""
        provider, _, _ = _provider("source.saopaulo.geosampa@1")
        page = provider.search(SearchQuery(text=query))
        assert [r.resource_id for r in page.resources][:1] == [first]

    def test_a_word_finds_the_same_layers_with_or_without_its_accent(self):
        provider, _, _ = _provider("source.saopaulo.geosampa@1")
        plain = provider.search(SearchQuery(text="onibus", limit=50))
        accented = provider.search(SearchQuery(text="ônibus", limit=50))
        assert [r.resource_id for r in plain.resources] == [r.resource_id for r in accented.resources]
        assert plain.total_hint == accented.total_hint == 34
        assert "geoportal:ponto_onibus" in {r.resource_id for r in plain.resources}

    def test_a_page_is_full_when_the_server_lists_ids_curio_refuses(self):
        """A layer whose name the provider would refuse is never offered, and
        is left out before the page is cut: the page holds as many rows as
        asked for, and the count and the cursor are of rows it can offer."""
        manifest = load_source_manifest(SHIPPED_ROOT / "source.saopaulo.geosampa@1")
        provider = build_provider(manifest, _OneDocument(_CAPABILITIES))
        first = provider.search(SearchQuery(text="", limit=2))
        assert [r.resource_id for r in first.resources] == ["ws:first", "ws:second"]
        assert first.total_hint == 3
        assert first.next_cursor == "2"
        rest = provider.search(SearchQuery(text="", limit=2, cursor=first.next_cursor))
        assert [r.resource_id for r in rest.resources] == ["ws:third"]
        assert rest.next_cursor is None

    def test_a_warm_cache_makes_a_second_search_free(self):
        """Capabilities is a CATALOGUE, not a query: it lists every published
        layer and changes only when an operator publishes one. Caching it is
        what makes a WFS source nearly free inside a federated fan-out."""
        provider, transport, _ = _provider("source.saopaulo.geosampa@1")
        provider.search(SearchQuery(text="ciclo"))
        assert len(transport.calls) == 1
        provider.search(SearchQuery(text="onibus"))
        assert len(transport.calls) == 1, "the second search should issue no request"

    def test_the_cache_expires_so_a_new_layer_is_findable(self, monkeypatch):
        provider, transport, _ = _provider("source.saopaulo.geosampa@1")
        provider.search(SearchQuery(text="ciclo"))
        assert len(transport.calls) == 1
        monkeypatch.setattr(
            wfs_mod.time, "monotonic",
            lambda: 1e9,  # far past the TTL
        )
        provider.search(SearchQuery(text="ciclo"))
        assert len(transport.calls) == 2

    def test_describe_reads_the_feature_type_schema(self):
        provider, _, _ = _provider("source.saopaulo.geosampa@1")
        detail = provider.describe("geoportal:bicicletario_paraciclo")
        assert detail.fields, "DescribeFeatureType should yield a field list"
        assert detail.extra.get("crs"), "capabilities carries the layer's CRS"

    def test_the_download_url_asks_for_geojson_in_wgs84(self):
        provider, _, _ = _provider("source.saopaulo.geosampa@1")
        target = provider.download_url("geoportal:bicicletario_paraciclo", "geojson")
        assert "request=GetFeature" in target.url
        assert "outputFormat=application%2Fjson" in target.url
        assert "srsName=EPSG:4326" in target.url
        assert target.declared_format == "geojson"


class TestDirect:
    def test_it_has_nothing_to_search(self):
        provider, _, _ = _provider("source.curio.direct-url@1")
        with pytest.raises(CapabilityUnsupported, match="search"):
            provider.search(SearchQuery(text="anything"))

    def test_the_resource_id_is_the_url(self):
        provider, _, _ = _provider("source.curio.direct-url@1")
        url = "https://example.org/data/roads.geojson"
        detail = provider.describe(url)
        assert detail.resource.resource_id == url
        assert detail.resource.name == "roads.geojson"
        assert detail.resource.formats == ("geojson",)

    def test_the_format_comes_from_the_extension(self):
        provider, _, _ = _provider("source.curio.direct-url@1")
        target = provider.download_url("https://example.org/a/b.csv", None)
        assert target.declared_format == "csv"

    def test_an_unknown_extension_defers_rather_than_guessing(self):
        """The detection ladder gets another chance from the response headers,
        so guessing here would only be a worse first guess."""
        provider, _, _ = _provider("source.curio.direct-url@1")
        target = provider.download_url("https://example.org/download?id=7", None)
        assert target.declared_format is None

    @pytest.mark.parametrize(
        "bad",
        ["http://example.org/a.csv", "file:///etc/passwd", "ftp://x/y.csv",
         "javascript:alert(1)", "https://exa mple.org/a.csv"],
    )
    def test_only_https_urls_are_accepted(self, bad):
        provider, _, _ = _provider("source.curio.direct-url@1")
        with pytest.raises(ResourceNotFound):
            provider.describe(bad)

    def test_it_never_claims_a_url_for_verify(self):
        """Claiming every https URL would shadow every other refinement, and
        the generic probe already handles an unrecognised URL correctly."""
        from utk_curio.backend.app.discovery.providers import direct

        assert direct.recognize("https://anything.example/x") is None


class TestTheRegistry:
    def test_every_manifest_provider_type_can_be_built(self):
        from utk_curio.backend.app.discovery.providers import (
            build_model_provider, build_service, build_storage,
        )

        for dir_name in sorted(p.name for p in SHIPPED_ROOT.iterdir() if p.is_dir()):
            manifest = load_source_manifest(SHIPPED_ROOT / dir_name)
            if manifest.is_service:
                # OpenStreetMap sends its own requests (autk-db, from Node) and
                # ignores the transport; Mapillary is asked over it.
                provider = build_service(manifest, FixtureDiscoveryTransport(FIXTURES))
            elif manifest.is_model:
                provider = build_model_provider(manifest, FixtureDiscoveryTransport(FIXTURES))
            else:
                build = build_storage if manifest.is_storage else build_provider
                provider = build(manifest, FixtureDiscoveryTransport(FIXTURES))
            assert provider.type == manifest.provider.type

    def test_an_http_service_refuses_to_be_built_without_a_transport(self):
        from utk_curio.backend.app.discovery.domain.errors import CapabilityUnsupported
        from utk_curio.backend.app.discovery.providers import build_service

        manifest = load_source_manifest(SHIPPED_ROOT / "source.mapillary.imagery@1")
        with pytest.raises(CapabilityUnsupported):
            build_service(manifest)

    def test_a_transport_is_required_not_defaulted(self):
        """Forgetting to inject a fake must be a TypeError at construction,
        not a silent real request."""
        manifest = load_source_manifest(SHIPPED_ROOT / "source.cityofchicago.data-portal@1")
        with pytest.raises(TypeError):
            PROVIDERS["socrata"](manifest)  # type: ignore[call-arg]

    def test_an_unrecorded_url_is_a_loud_miss(self):
        provider, _, _ = _provider("source.cityofchicago.data-portal@1")
        with pytest.raises(FixtureMissing, match="record"):
            provider.search(SearchQuery(text="something never recorded"))
