"""The source roster: listing, filtering, facets, and surviving bad input.

Every test here runs against a temp catalog root and makes no request of any
kind - the roster is a filesystem question, and keeping it that way is what
lets the whole surface be tested before a transport exists.
"""

from __future__ import annotations

import pytest

from utk_curio.backend.app.discovery.application.catalog import DiscoveryCatalog
from utk_curio.backend.app.discovery.domain.errors import SourceNotFound
from utk_curio.backend.tests.test_discovery.conftest import a_manifest, write_source


def _seed(root):
    write_source(root, "source.a.socrata-one@1", a_manifest(
        id="source.a.socrata-one", name="Alpha Portal", publisher="Alpha City",
        tags=["alpha", "municipal"],
        provider={"type": "socrata", "baseUrl": "https://alpha.example"},
        auth={"mode": "optional-token", "secretId": "socrata.app-token",
              "headerName": "X-App-Token"}))
    write_source(root, "source.b.ckan-one@1", a_manifest(
        id="source.b.ckan-one", name="Beta Catalog", publisher="Beta Agency",
        description="Federal beta datasets.", tags=["beta"],
        provider={"type": "ckan", "baseUrl": "https://beta.example"}))
    write_source(root, "source.c.direct@1", a_manifest(
        id="source.c.direct", name="Direct URL", publisher="Curio",
        provider={"type": "direct", "baseUrl": ""},
        capabilities={"search": False, "formats": ["csv"]}))


@pytest.fixture()
def catalog(discovery_dir):
    _seed(discovery_dir)
    return DiscoveryCatalog()


class TestListing:
    def test_it_lists_every_readable_source(self, catalog):
        rows = catalog.list_catalog()["sources"]
        assert [r["sourceId"] for r in rows] == [
            "source.a.socrata-one", "source.b.ckan-one", "source.c.direct",
        ]

    def test_rows_are_sorted_by_name_not_by_directory(self, discovery_dir):
        write_source(discovery_dir, "source.z.aaa@1", a_manifest(id="source.z.aaa", name="Aaa"))
        write_source(discovery_dir, "source.a.zzz@1", a_manifest(id="source.a.zzz", name="Zzz"))
        rows = DiscoveryCatalog().list_catalog()["sources"]
        assert [r["name"] for r in rows] == ["Aaa", "Zzz"]

    def test_an_empty_root_is_an_empty_list_not_an_error(self, discovery_dir):
        assert DiscoveryCatalog().list_catalog() == {
            "sources": [], "facets": {"provider": {}, "auth": {}},
        }

    def test_a_missing_root_is_also_empty(self, tmp_path, monkeypatch):
        from utk_curio.backend.app.discovery.infrastructure import storage

        monkeypatch.setenv(storage.ENV_ROOT, str(tmp_path / "nope"))
        assert DiscoveryCatalog().list_catalog()["sources"] == []
        assert not (tmp_path / "nope").exists(), "the root must never be created eagerly"


class TestBadInputIsSkippedNotFatal:
    def test_a_malformed_manifest_does_not_empty_the_catalog(self, discovery_dir):
        """One bad folder must not take the listing down. A source that never
        appears is a recoverable absence; a 500 on the roster is not."""
        _seed(discovery_dir)
        bad = discovery_dir / "source.bad.one@1"
        bad.mkdir()
        (bad / "manifest.json").write_text("{ not json", encoding="utf-8")
        assert len(DiscoveryCatalog().list_catalog()["sources"]) == 3

    def test_a_directory_whose_name_does_not_match_its_id_is_skipped(self, discovery_dir):
        write_source(discovery_dir, "source.right.name@1", a_manifest(id="source.wrong.name"))
        assert DiscoveryCatalog().list_catalog()["sources"] == []

    def test_a_folder_with_no_manifest_is_skipped(self, discovery_dir):
        _seed(discovery_dir)
        (discovery_dir / "source.no.manifest@1").mkdir()
        assert len(DiscoveryCatalog().list_catalog()["sources"]) == 3

    def test_a_stray_file_or_odd_folder_is_ignored(self, discovery_dir):
        _seed(discovery_dir)
        (discovery_dir / "README.md").write_text("hi", encoding="utf-8")
        (discovery_dir / "not-a-source").mkdir()
        assert len(DiscoveryCatalog().list_catalog()["sources"]) == 3


class TestFilters:
    def test_by_provider(self, catalog):
        rows = catalog.list_catalog(provider="ckan")["sources"]
        assert [r["sourceId"] for r in rows] == ["source.b.ckan-one"]

    def test_by_auth_mode(self, catalog):
        rows = catalog.list_catalog(auth="optional-token")["sources"]
        assert [r["sourceId"] for r in rows] == ["source.a.socrata-one"]

    @pytest.mark.parametrize(
        "query,expected",
        [
            ("beta", "source.b.ckan-one"),          # name
            ("federal", "source.b.ckan-one"),       # description
            ("alpha city", "source.a.socrata-one"), # publisher
            ("municipal", "source.a.socrata-one"),  # tag
            ("socrata-one", "source.a.socrata-one"),# id
        ],
    )
    def test_search_covers_the_fields_a_user_would_type(self, catalog, query, expected):
        rows = catalog.list_catalog(q=query)["sources"]
        assert [r["sourceId"] for r in rows] == [expected]

    def test_search_is_case_insensitive_and_trimmed(self, catalog):
        rows = catalog.list_catalog(q="   BETA  ")["sources"]
        assert [r["sourceId"] for r in rows] == ["source.b.ckan-one"]

    @pytest.mark.parametrize("query", ["paulo sao", "sao paulo", "portals paulo"])
    def test_words_match_in_any_order_without_accents_and_as_plurals(self, catalog, discovery_dir, query):
        write_source(discovery_dir, "source.br.sao-paulo@1", a_manifest(
            id="source.br.sao-paulo", name="São Paulo Portal", publisher="Prefeitura de São Paulo",
            provider={"type": "ckan", "baseUrl": "https://sp.example"}))
        rows = catalog.list_catalog(q=query)["sources"]
        assert [r["sourceId"] for r in rows] == ["source.br.sao-paulo"]

    def test_no_match_is_an_empty_list(self, catalog):
        assert catalog.list_catalog(q="nothing here")["sources"] == []


class TestFacets:
    def test_they_count_every_source(self, catalog):
        facets = catalog.list_catalog()["facets"]
        assert facets["provider"] == {"ckan": 1, "direct": 1, "socrata": 1}
        assert facets["auth"] == {"optional-token": 1, "public": 2}

    def test_they_are_counted_before_filtering(self, catalog):
        """So a chip never reads 0 for a filter that would show something once
        another chip is cleared."""
        filtered = catalog.list_catalog(provider="ckan")
        assert len(filtered["sources"]) == 1
        assert filtered["facets"]["provider"] == {"ckan": 1, "direct": 1, "socrata": 1}


class TestGetOne:
    def test_it_returns_the_row(self, catalog):
        assert catalog.get_manifest("source.b.ckan-one@1").name == "Beta Catalog"

    def test_an_unknown_source_is_not_found(self, catalog):
        with pytest.raises(SourceNotFound):
            catalog.get_manifest("source.no.such@1")

    @pytest.mark.parametrize(
        "dir_name",
        ["../../etc", "source.a.socrata-one", "not-a-dir-name", "source.a.b@99999"],
    )
    def test_a_malformed_name_is_not_found_rather_than_an_exception(self, catalog, dir_name):
        """Validated before the filesystem is touched, and reported as a 404 -
        a traversal attempt learns nothing from the response that a typo
        would not also learn."""
        with pytest.raises(SourceNotFound):
            catalog.get_manifest(dir_name)


class TestInjectedCollaborators:
    def test_credential_presence_comes_from_the_caller(self, discovery_dir):
        _seed(discovery_dir)
        catalog = DiscoveryCatalog(credential_present=lambda slot: slot == "socrata.app-token")
        rows = {r["sourceId"]: r for r in catalog.list_catalog()["sources"]}
        assert rows["source.a.socrata-one"]["auth"]["present"] is True
        assert rows["source.b.ckan-one"]["auth"]["present"] is False

    def test_the_icon_url_comes_from_the_caller(self, discovery_dir):
        """Whether a file exists is storage's business and what the URL looks
        like is routing's, so the domain asks rather than deciding."""
        _seed(discovery_dir)
        catalog = DiscoveryCatalog(icon_url_for=lambda m: f"/icons/{m.dir_name}")
        rows = catalog.list_catalog()["sources"]
        assert rows[0]["iconUrl"] == "/icons/source.a.socrata-one@1"

    def test_without_collaborators_it_still_lists(self, discovery_dir):
        """The roster must be usable with no database and no request context."""
        _seed(discovery_dir)
        rows = DiscoveryCatalog().list_catalog()["sources"]
        assert all(r["iconUrl"] is None for r in rows)
        assert all(r["auth"]["present"] is False for r in rows)
