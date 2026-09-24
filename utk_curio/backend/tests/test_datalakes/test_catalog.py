"""The source roster: listing, filtering, facets, and surviving bad input.

Every test here runs against a temp catalog root and makes no request of any
kind - the roster is a filesystem question, and keeping it that way is what
lets the whole surface be tested before a transport exists.
"""

from __future__ import annotations

import pytest

from utk_curio.backend.app.datalakes.application.catalog import LakeCatalog
from utk_curio.backend.app.datalakes.domain.errors import SourceNotFound
from utk_curio.backend.tests.test_datalakes.conftest import a_manifest, write_source


def _seed(root):
    write_source(root, "lake.a.socrata-one@1", a_manifest(
        id="lake.a.socrata-one", name="Alpha Portal", publisher="Alpha City",
        tags=["alpha", "municipal"],
        provider={"type": "socrata", "baseUrl": "https://alpha.example"},
        auth={"mode": "optional-token", "secretId": "socrata.app-token",
              "headerName": "X-App-Token"}))
    write_source(root, "lake.b.ckan-one@1", a_manifest(
        id="lake.b.ckan-one", name="Beta Catalog", publisher="Beta Agency",
        description="Federal beta datasets.", tags=["beta"],
        provider={"type": "ckan", "baseUrl": "https://beta.example"}))
    write_source(root, "lake.c.direct@1", a_manifest(
        id="lake.c.direct", name="Direct URL", publisher="Curio",
        provider={"type": "direct", "baseUrl": ""},
        capabilities={"search": False, "formats": ["csv"]}))


@pytest.fixture()
def catalog(lake_root):
    _seed(lake_root)
    return LakeCatalog()


class TestListing:
    def test_it_lists_every_readable_source(self, catalog):
        rows = catalog.list_catalog()["sources"]
        assert [r["sourceId"] for r in rows] == [
            "lake.a.socrata-one", "lake.b.ckan-one", "lake.c.direct",
        ]

    def test_rows_are_sorted_by_name_not_by_directory(self, lake_root):
        write_source(lake_root, "lake.z.aaa@1", a_manifest(id="lake.z.aaa", name="Aaa"))
        write_source(lake_root, "lake.a.zzz@1", a_manifest(id="lake.a.zzz", name="Zzz"))
        rows = LakeCatalog().list_catalog()["sources"]
        assert [r["name"] for r in rows] == ["Aaa", "Zzz"]

    def test_an_empty_root_is_an_empty_list_not_an_error(self, lake_root):
        assert LakeCatalog().list_catalog() == {
            "sources": [], "facets": {"provider": {}, "auth": {}},
        }

    def test_a_missing_root_is_also_empty(self, tmp_path, monkeypatch):
        from utk_curio.backend.app.datalakes.infrastructure import storage

        monkeypatch.setenv(storage.ENV_ROOT, str(tmp_path / "nope"))
        assert LakeCatalog().list_catalog()["sources"] == []
        assert not (tmp_path / "nope").exists(), "the root must never be created eagerly"


class TestBadInputIsSkippedNotFatal:
    def test_a_malformed_manifest_does_not_empty_the_catalog(self, lake_root):
        """One bad folder must not take the listing down. A source that never
        appears is a recoverable absence; a 500 on the roster is not."""
        _seed(lake_root)
        bad = lake_root / "lake.bad.one@1"
        bad.mkdir()
        (bad / "manifest.json").write_text("{ not json", encoding="utf-8")
        assert len(LakeCatalog().list_catalog()["sources"]) == 3

    def test_a_directory_whose_name_does_not_match_its_id_is_skipped(self, lake_root):
        write_source(lake_root, "lake.right.name@1", a_manifest(id="lake.wrong.name"))
        assert LakeCatalog().list_catalog()["sources"] == []

    def test_a_folder_with_no_manifest_is_skipped(self, lake_root):
        _seed(lake_root)
        (lake_root / "lake.no.manifest@1").mkdir()
        assert len(LakeCatalog().list_catalog()["sources"]) == 3

    def test_a_stray_file_or_odd_folder_is_ignored(self, lake_root):
        _seed(lake_root)
        (lake_root / "README.md").write_text("hi", encoding="utf-8")
        (lake_root / "not-a-source").mkdir()
        assert len(LakeCatalog().list_catalog()["sources"]) == 3


class TestFilters:
    def test_by_provider(self, catalog):
        rows = catalog.list_catalog(provider="ckan")["sources"]
        assert [r["sourceId"] for r in rows] == ["lake.b.ckan-one"]

    def test_by_auth_mode(self, catalog):
        rows = catalog.list_catalog(auth="optional-token")["sources"]
        assert [r["sourceId"] for r in rows] == ["lake.a.socrata-one"]

    @pytest.mark.parametrize(
        "query,expected",
        [
            ("beta", "lake.b.ckan-one"),          # name
            ("federal", "lake.b.ckan-one"),       # description
            ("alpha city", "lake.a.socrata-one"), # publisher
            ("municipal", "lake.a.socrata-one"),  # tag
            ("socrata-one", "lake.a.socrata-one"),# id
        ],
    )
    def test_search_covers_the_fields_a_user_would_type(self, catalog, query, expected):
        rows = catalog.list_catalog(q=query)["sources"]
        assert [r["sourceId"] for r in rows] == [expected]

    def test_search_is_case_insensitive_and_trimmed(self, catalog):
        rows = catalog.list_catalog(q="   BETA  ")["sources"]
        assert [r["sourceId"] for r in rows] == ["lake.b.ckan-one"]

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
        assert catalog.get_manifest("lake.b.ckan-one@1").name == "Beta Catalog"

    def test_an_unknown_source_is_not_found(self, catalog):
        with pytest.raises(SourceNotFound):
            catalog.get_manifest("lake.no.such@1")

    @pytest.mark.parametrize(
        "dir_name",
        ["../../etc", "lake.a.socrata-one", "not-a-dir-name", "lake.a.b@99999"],
    )
    def test_a_malformed_name_is_not_found_rather_than_an_exception(self, catalog, dir_name):
        """Validated before the filesystem is touched, and reported as a 404 -
        a traversal attempt learns nothing from the response that a typo
        would not also learn."""
        with pytest.raises(SourceNotFound):
            catalog.get_manifest(dir_name)


class TestInjectedCollaborators:
    def test_credential_presence_comes_from_the_caller(self, lake_root):
        _seed(lake_root)
        catalog = LakeCatalog(credential_present=lambda slot: slot == "socrata.app-token")
        rows = {r["sourceId"]: r for r in catalog.list_catalog()["sources"]}
        assert rows["lake.a.socrata-one"]["auth"]["present"] is True
        assert rows["lake.b.ckan-one"]["auth"]["present"] is False

    def test_the_icon_url_comes_from_the_caller(self, lake_root):
        """Whether a file exists is storage's business and what the URL looks
        like is routing's, so the domain asks rather than deciding."""
        _seed(lake_root)
        catalog = LakeCatalog(icon_url_for=lambda m: f"/icons/{m.dir_name}")
        rows = catalog.list_catalog()["sources"]
        assert rows[0]["iconUrl"] == "/icons/lake.a.socrata-one@1"

    def test_without_collaborators_it_still_lists(self, lake_root):
        """The roster must be usable with no database and no request context."""
        _seed(lake_root)
        rows = LakeCatalog().list_catalog()["sources"]
        assert all(r["iconUrl"] is None for r in rows)
        assert all(r["auth"]["present"] is False for r in rows)
