"""The source manifest contract: what is accepted, and what is refused.

A manifest is operator-authored, so every refusal here is a message someone
will read while editing JSON at 2am. They name the field.
"""

from __future__ import annotations

import pytest

from utk_curio.backend.app.discovery.domain import manifest as M
from utk_curio.backend.app.discovery.domain.source_id import SourceId, SourceIdError
from utk_curio.backend.tests.test_discovery.conftest import (
    TINY_PNG,
    a_manifest,
    write_source,
)


def _parse(**overrides):
    return M._parse_manifest(a_manifest(**overrides), where="manifest.json")


class TestSourceId:
    @pytest.mark.parametrize(
        "dir_name",
        ["source.us.data-gov@1", "source.a.b@0", "source.a.b.c.d.e@9999", "source.x-y.z-w@2"],
    )
    def test_accepted(self, dir_name):
        assert SourceId.parse_dir(dir_name).dir_name == dir_name

    @pytest.mark.parametrize(
        "dir_name",
        [
            "us.data-gov@1",          # the source. prefix is mandatory
            "source.onlyone@1",         # needs at least 3 segments
            "source.a.b",               # no major
            "source.a.b@10000",         # major out of range
            "source.A.B@1",             # uppercase
            "source.a.b@01",            # leading zero
            "source.a.b@1/../x",        # separators
            "source.a.b.c.d.e.f@1",     # too many segments
            "",
        ],
    )
    def test_refused(self, dir_name):
        with pytest.raises(SourceIdError):
            SourceId.parse_dir(dir_name)

    def test_the_provider_is_not_in_the_id(self):
        """A portal that migrates Socrata -> CKAN keeps its id.

        Not a constraint the parser enforces - it is a convention - but the
        shipped set follows it and this records why.
        """
        m = _parse(id="source.us.data-gov", provider={"type": "ckan", "baseUrl": "https://x.example"})
        assert "ckan" not in m.id
        assert m.provider.type == "ckan"


class TestRequiredFields:
    @pytest.mark.parametrize("field", ["id", "name", "version"])
    def test_missing_is_refused_by_name(self, field):
        raw = a_manifest()
        del raw[field]
        with pytest.raises(M.ManifestError, match=field):
            M._parse_manifest(raw, where="manifest.json")

    def test_provider_is_required(self):
        raw = a_manifest()
        del raw["provider"]
        with pytest.raises(M.ManifestError, match="provider"):
            M._parse_manifest(raw, where="manifest.json")

    def test_defaults_are_permissive_for_everything_else(self):
        m = M._parse_manifest(
            {"id": "source.a.b", "name": "n", "version": "1",
             "provider": {"type": "socrata", "baseUrl": "https://a.example"}},
            where="manifest.json",
        )
        assert m.auth.mode == "public"
        assert m.capabilities.search is True
        assert m.capabilities.formats == M.DISCOVERY_ACQUIRABLE_FORMATS
        assert m.requests_per_minute == M.DEFAULT_REQUESTS_PER_MINUTE


class TestProvider:
    def test_an_unknown_type_is_refused(self):
        with pytest.raises(M.ManifestError, match="provider.type"):
            _parse(provider={"type": "bigquery", "baseUrl": "https://x.example"})

    def test_a_non_https_base_is_refused(self):
        with pytest.raises(M.ManifestError, match="https"):
            _parse(provider={"type": "ckan", "baseUrl": "http://portal.example"})

    def test_a_trailing_slash_is_normalised_away(self):
        """So a provider can join paths without minting '//' URLs."""
        m = _parse(provider={"type": "ckan", "baseUrl": "https://portal.example/"})
        assert m.provider.base_url == "https://portal.example"

    def test_only_direct_may_have_an_empty_base(self):
        assert _parse(
            provider={"type": "direct", "baseUrl": ""},
            capabilities={"search": False},
        ).provider.base_url == ""
        with pytest.raises(M.ManifestError, match="required"):
            _parse(provider={"type": "wfs", "baseUrl": ""})


class TestAuth:
    def test_a_token_mode_needs_a_slot_and_a_header(self):
        with pytest.raises(M.ManifestError, match="secretId"):
            _parse(auth={"mode": "optional-token"})
        with pytest.raises(M.ManifestError, match="headerName"):
            _parse(auth={"mode": "optional-token", "secretId": "socrata.app-token"})

    def test_a_query_key_names_its_parameter_and_no_header(self):
        """A query key is sent as one parameter, added by the transport at send
        time (``test_credentials.py`` pins that it reaches no stored string)."""
        with pytest.raises(M.ManifestError, match="takes paramName, not headerName"):
            _parse(auth={"mode": "optional-token", "secretId": "socrata.app-token",
                         "headerName": "X-T", "scheme": "query"})
        with pytest.raises(M.ManifestError, match="paramName is required"):
            _parse(auth={"mode": "optional-token", "secretId": "socrata.app-token", "scheme": "query"})
        with pytest.raises(M.ManifestError, match="applies to scheme 'query' only"):
            _parse(auth={"mode": "optional-token", "secretId": "socrata.app-token",
                         "headerName": "X-T", "paramName": "key"})
        with pytest.raises(M.ManifestError, match="scheme must be one of"):
            _parse(auth={"mode": "optional-token", "secretId": "socrata.app-token",
                         "headerName": "X-T", "scheme": "cookie"})
        auth = _parse(auth={"mode": "optional-token", "secretId": "socrata.app-token",
                            "scheme": "query", "paramName": "key"}).auth
        assert (auth.scheme, auth.param_name, auth.header_name) == ("query", "key", None)

    def test_a_malformed_slot_is_refused(self):
        with pytest.raises(M.ManifestError, match="secretId"):
            _parse(auth={"mode": "optional-token", "secretId": "Not A Slot",
                         "headerName": "X-T"})

    def test_public_needs_nothing(self):
        auth = _parse(auth={"mode": "public"}).auth
        assert auth.secret_id is None and not auth.uses_token and not auth.needs_token


class TestCapabilities:
    def test_a_format_outside_the_acquirable_set_is_refused(self):
        """shp and bundle are Data Catalog formats but not remotely acquirable:
        a .shp needs sibling files, a bundle is a node output."""
        with pytest.raises(M.ManifestError, match="unacquirable"):
            _parse(capabilities={"formats": ["csv", "shp"]})

    def test_a_manifest_may_lower_the_download_ceiling(self):
        assert _parse(capabilities={"maxDownloadBytes": 1024}).capabilities.max_download_bytes == 1024

    def test_a_manifest_cannot_raise_it(self):
        """The hard bound is the server's. An operator editing JSON should not
        be able to talk it into a 10 GB download."""
        m = _parse(capabilities={"maxDownloadBytes": 10 * 1024 ** 3})
        assert m.capabilities.max_download_bytes == M.DEFAULT_MAX_DOWNLOAD_BYTES


class TestIcon:
    def test_a_plain_png_name_is_accepted(self):
        assert _parse(icon="icon.png").icon == "icon.png"
        assert _parse(icon="chicago-mark.png").icon == "chicago-mark.png"

    @pytest.mark.parametrize(
        "value",
        ["../../etc/passwd.png", "sub/dir/icon.png", "icon.svg", "icon.PNG.exe",
         "/abs/icon.png", ".png", "icon"],
    )
    def test_a_path_or_a_non_png_is_refused(self, value):
        with pytest.raises(M.ManifestError, match="icon"):
            _parse(icon=value)

    def test_absent_is_fine(self):
        assert _parse().icon is None


class TestLoading:
    def test_round_trips_through_the_serialiser(self, discovery_dir):
        original = _parse(icon="icon.png")
        rebuilt = M._parse_manifest(M.build_manifest_dict(original), where="x")
        assert rebuilt == original

    def test_the_directory_name_must_match_the_id(self, discovery_dir):
        path = write_source(discovery_dir, "source.wrong.name@1", a_manifest())
        with pytest.raises(M.ManifestError, match="does not match"):
            M.load_source_manifest(path)
        # ...but the lenient loader, used by the catalog scan, does not care.
        assert M.load_source_manifest_from_dir(path).id == "source.example.portal"

    def test_a_missing_manifest_says_so(self, discovery_dir):
        (discovery_dir / "source.empty.dir@1").mkdir()
        with pytest.raises(M.ManifestError, match="missing manifest.json"):
            M.load_source_manifest_from_dir(discovery_dir / "source.empty.dir@1")

    def test_broken_json_names_the_problem(self, discovery_dir):
        path = discovery_dir / "source.bad.json@1"
        path.mkdir()
        (path / "manifest.json").write_text("{not json", encoding="utf-8")
        with pytest.raises(M.ManifestError, match="not valid JSON"):
            M.load_source_manifest_from_dir(path)

    def test_an_icon_is_just_a_name_here(self, discovery_dir):
        """Whether the file EXISTS is a storage question, not a manifest one -
        so a manifest naming a deleted icon still loads, and the route serves
        the glyph instead."""
        path = write_source(discovery_dir, "source.example.portal@1", a_manifest(icon="icon.png"))
        assert M.load_source_manifest(path).icon == "icon.png"
        write_source(discovery_dir, "source.example.portal@1", a_manifest(icon="icon.png"), icon=TINY_PNG)
        assert M.load_source_manifest(path).icon == "icon.png"
