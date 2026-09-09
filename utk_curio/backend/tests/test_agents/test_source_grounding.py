"""dev/114 (DEC-072) — the one source-grounding gate: a local path is grounded
only by the user or the Data Catalog, a URL only by the runtime's probe, inline
data only when synthetic was asked for; everything else is refused with the
correction named. Pure — no Flask, no network, no store."""

from __future__ import annotations

from utk_curio.backend.app.agents import source_grounding as sg

ISSUE_298 = 'import pandas as pd\ndf = pd.read_csv("bras_ibge_data.csv")\nreturn df'
CATALOG_PATH = "/curio/users/4242/datasets/census-acs@1/census_acs.parquet"


def _ctx(**kw) -> sg.GroundingContext:
    return sg.GroundingContext(**kw)


class TestScanner:
    def test_bare_filename_and_fstring_url_prefix(self):
        code = ISSUE_298 + '\nu = f"https://api.census.gov/data/{year}/acs/acs5"'
        refs = sg.scan_sources(code, "python")
        kinds = {(r.kind, r.literal, r.partial) for r in refs}
        assert ("path", "bras_ibge_data.csv", False) in kinds
        assert ("url", "https://api.census.gov/data/", True) in kinds
        # node content is a function body: the top-level return parsed fine
        assert next(r for r in refs if r.kind == "path").line == 2

    def test_fstring_constant_children_are_not_double_scanned(self):
        refs = sg.scan_sources('u = f"https://x.org/{a}/b.json"', "python")
        assert len(refs) == 1 and refs[0].partial is True

    def test_non_source_strings_are_ignored(self):
        code = 'cols = ["population", "area_km2"]\nfmt = "%Y-%m-%d"\nmod = "utils/helpers.py"\nreturn cols'
        assert sg.scan_sources(code, "python") == []

    def test_syntax_error_falls_back_to_regex(self):
        code = 'df = pd.read_csv("x.csv"\nreturn df'  # unclosed paren
        refs = sg.scan_sources(code, "python")
        assert [(r.kind, r.literal) for r in refs] == [("path", "x.csv")]

    def test_non_python_engine_uses_regex(self):
        refs = sg.scan_sources("const d = await fetch('https://a.gov/data.json');", "javascript")
        assert [(r.kind, r.literal) for r in refs] == [("url", "https://a.gov/data.json")]

    def test_extension_table_and_rooted_paths(self):
        assert sg.classify_literal("bras_geosampa_boundary.shp") == "path"
        assert sg.classify_literal("data/tracts.geojson") == "path"
        assert sg.classify_literal("./out/result.dat") == "path"
        assert sg.classify_literal("C:\\data\\f.shp") == "path"
        assert sg.classify_literal("a/b/c.bin") == "path"
        assert sg.classify_literal("hello world") is None
        assert sg.classify_literal("utils/helpers.py") is None
        assert sg.classify_literal("HTTPS://Data.Gov/x") == "url"

    def test_bounded_and_deduplicated(self):
        code = "\n".join(f'a{i} = "f{i % 3}.csv"' for i in range(100))
        refs = sg.scan_sources(code, "python")
        assert len(refs) == 3


class TestComposedRequests:
    """dev/115 field fix: the request the loader MAKES, composed from literal
    url + params, so the correction probes what the server actually saw."""

    CENSUS = ('import requests\nurl = "https://api.census.gov/data/2022/acs/acs5"\n'
              'params = {"get": "NAME,B19013_001E", "for": "tract:*", "in": "state:17 place:16085"}\n'
              'response = requests.get(url, params=params)\nreturn response.json()')

    def test_url_and_params_through_names_compose_the_real_request(self):
        assert sg.composed_requests(self.CENSUS) == [
            "https://api.census.gov/data/2022/acs/acs5?get=NAME%2CB19013_001E&for=tract%3A%2A&in=state%3A17+place%3A16085"
        ]

    def test_inline_literals_query_suffix_and_session_get(self):
        code = ('s = requests.Session()\n'
                'r = s.get("https://x.org/api?fmt=json", params={"q": 1, "flag": True})\n'
                'r2 = requests.request("GET", "https://y.org/v1", params={"a": "b"})')
        assert sg.composed_requests(code) == [
            "https://x.org/api?fmt=json&q=1&flag=True",
            "https://y.org/v1?a=b",
        ]

    def test_dynamic_pieces_are_never_composed(self):
        dynamic = ('key = os.environ["K"]\nurl = "https://x.org/api"\n'
                   'r = requests.get(url, params={"key": key})\n'          # computed value
                   'r2 = requests.get(f"https://x.org/{v}", params={"a": 1})\n'  # dynamic url
                   'r3 = requests.get("https://x.org/plain")\n'            # no params: nothing to compose
                   'r4 = requests.get("not a url", params={"a": 1})')
        assert sg.composed_requests(dynamic) == []
        assert sg.composed_requests("") == [] and sg.composed_requests("def (") == []

    def test_bounded_and_deduplicated(self):
        code = "\n".join(f'r{i} = requests.get("https://x.org/{i % 2}", params={{"a": 1}})' for i in range(10))
        assert sg.composed_requests(code) == ["https://x.org/0?a=1", "https://x.org/1?a=1"]
        many = "\n".join(f'r{i} = requests.get("https://x.org/{i}", params={{"a": 1}})' for i in range(10))
        assert len(sg.composed_requests(many)) == sg.MAX_COMPOSED_REQUESTS


class TestCatalogIdForm:
    """main's loader recipe emits the portable ``curio_dataset_path("<id>")``
    call (resolved by the sandbox at run time) — grounded by dataset id."""

    def test_known_id_is_grounded_and_unknown_refused(self):
        ctx = _ctx(is_data_loading=True, catalog_ids={"imported.x1@1": sg.CatalogRef("imported.x1@1", "Tracts", "csv", "")})
        ok = sg.check_grounding('dataset_path = curio_dataset_path("imported.x1@1")\ndf = pd.read_csv(dataset_path)\nreturn df', "python", ctx)
        assert ok.ok and ok.source["kind"] == "catalog"
        assert ok.source["refs"][0]["value"] == 'curio_dataset_path("imported.x1@1")'
        assert ok.source["refs"][0]["datasetId"] == "imported.x1@1"
        bad = sg.check_grounding("dataset_path = curio_dataset_path('imported.ghost@1')\nreturn dataset_path", "python", ctx)
        assert not bad.ok and "not a dataset in this project's Data Catalog" in bad.violations[0]

    def test_id_is_not_double_counted_and_regex_fallback_matches(self):
        refs = sg.scan_sources('p = curio_dataset_path("computed.n1@1")', "python")
        assert [(r.kind, r.literal) for r in refs] == [("catalog-id", "computed.n1@1")]
        broken = 'p = curio_dataset_path("computed.n1@1")\nreturn (p'  # syntax error → regex
        assert [(r.kind, r.literal) for r in sg.scan_sources(broken, "python")] == [("catalog-id", "computed.n1@1")]


class TestUserTexts:
    def test_user_paths_from_free_text(self):
        paths = sg.user_paths(["load /data/tracts.geojson and also `raw/pop.csv`, please."])
        assert paths == {"/data/tracts.geojson", "raw/pop.csv"}

    def test_synthetic_needs_the_users_words(self):
        assert sg.synthetic_requested(["generate synthetic sample data for 5 tracts"]) is True
        assert sg.synthetic_requested(["load the IBGE demographic data"]) is False
        # The model's declaration alone never authorizes.
        assert sg.synthetic_requested(["load the IBGE data"], {"synthetic": True}) is False


class TestVerdicts:
    def test_issue_298_shape_is_refused_with_the_literal_named(self):
        verdict = sg.check_grounding(ISSUE_298, "python", _ctx(is_data_loading=True))
        assert verdict.ok is False
        assert "bras_ibge_data.csv" in verdict.violations[0]
        assert "Curio cannot see" in verdict.violations[0]
        assert verdict.source is None

    def test_catalog_path_is_grounded_with_the_real_id(self):
        ctx = _ctx(
            is_data_loading=True,
            catalog_paths={CATALOG_PATH: sg.CatalogRef("ds-acs", "Census ACS 5-year", "parquet", CATALOG_PATH)},
        )
        code = f'dataset_path = "{CATALOG_PATH}"\ndf = pd.read_parquet(dataset_path)\nreturn df'
        verdict = sg.check_grounding(code, "python", ctx)
        assert verdict.ok is True
        assert verdict.source["kind"] == "catalog"
        assert verdict.source["refs"][0]["datasetId"] == "ds-acs"
        assert "Census ACS 5-year (parquet)" in verdict.source["label"]

    def test_catalog_match_tolerates_path_normalization_only(self):
        ctx = _ctx(catalog_paths={CATALOG_PATH: sg.CatalogRef("d", "T", "parquet", CATALOG_PATH)})
        drifted = CATALOG_PATH.replace("/datasets/", "/./datasets/")
        assert sg.check_grounding(f'p = "{drifted}"', "python", ctx).ok is True
        sibling = CATALOG_PATH.replace("census_acs", "other")
        assert sg.check_grounding(f'p = "{sibling}"', "python", ctx).ok is False

    def test_user_path_is_grounded_and_labeled(self):
        ctx = _ctx(is_data_loading=True, user_paths={"data/tracts.geojson"})
        verdict = sg.check_grounding('gdf = gpd.read_file("data/tracts.geojson")\nreturn gdf', "python", ctx)
        assert verdict.ok and verdict.source["kind"] == "user-path"
        assert "User-provided path" in verdict.source["label"]

    def test_verified_session_url_needs_no_probe(self):
        calls = []
        ctx = _ctx(
            is_data_loading=True,
            verified_urls={"https://api.census.gov/data/": {"status": "verified", "httpStatus": 200}},
            probe=lambda url: calls.append(url) or {"status": "unreachable"},
        )
        code = 'r = requests.get("https://api.census.gov/data", timeout=10)\nreturn r.json()'
        verdict = sg.check_grounding(code, "python", ctx)
        assert verdict.ok and verdict.source["kind"] == "external"
        assert calls == []  # trailing-slash drift matched; nothing re-spent

    def test_unverified_url_is_probed_and_404_refused(self):
        ctx = _ctx(is_data_loading=True, probe=lambda url: {"status": "unreachable", "httpStatus": 404,
                                                            "detail": "the endpoint answered 404"})
        verdict = sg.check_grounding('r = requests.get("https://x.gov/nope.json")\nreturn r', "python", ctx)
        assert verdict.ok is False
        assert "answered 404" in verdict.violations[0]

    def test_400_names_the_request_shape(self):
        ctx = _ctx(probe=lambda url: {"status": "unreachable", "httpStatus": 400})
        verdict = sg.check_grounding('r = requests.get("https://api.census.gov/data/2020/acs")', "python", ctx)
        assert "check the parameters" in verdict.violations[0]

    def test_401_is_grounded_as_credential_gated(self):
        ctx = _ctx(probe=lambda url: {"status": "unreachable", "httpStatus": 401})
        verdict = sg.check_grounding('r = requests.get("https://api.x.gov/v1/data")', "python", ctx)
        assert verdict.ok is True
        assert verdict.source["refs"][0]["requirement"] == "credential-gated"
        assert "credential-gated" in verdict.source["label"]

    def test_no_probe_available_refuses_honestly(self):
        verdict = sg.check_grounding('r = requests.get("https://a.gov/x")', "python", _ctx())
        assert not verdict.ok and "no probe is available" in verdict.violations[0]

    def test_probe_exception_is_a_refusal_never_a_claim(self):
        def _boom(url):
            raise RuntimeError("socket died")
        verdict = sg.check_grounding('r = requests.get("https://a.gov/x")', "python", _ctx(probe=_boom))
        assert not verdict.ok and "socket died" in verdict.violations[0]

    def test_url_in_user_text_is_not_evidence(self):
        # The DEC-047 handoff prompt is model-suggested text the user forwards.
        ctx = _ctx(user_paths=sg.user_paths(["fetch https://fake.example/data.json"]),
                   probe=lambda url: {"status": "unreachable", "httpStatus": 404})
        assert sg.check_grounding('r = requests.get("https://fake.example/data.json")', "python", ctx).ok is False

    def test_partial_path_prefix_is_refused(self):
        verdict = sg.check_grounding('p = f"{base}/data/file.csv"', "python", _ctx(user_paths={"/data/file.csv"}))
        assert not verdict.ok and "composed at run time" in verdict.violations[0]

    def test_data_loading_without_sources_needs_synthetic(self):
        code = 'import pandas as pd\ndf = pd.DataFrame({"tract": [1, 2], "pop": [10, 20]})\nreturn df'
        refused = sg.check_grounding(code, "python", _ctx(is_data_loading=True))
        assert not refused.ok and "no grounded source" in refused.violations[0]
        ok = sg.check_grounding(code, "python", _ctx(is_data_loading=True, synthetic_requested=True))
        assert ok.ok and ok.source["kind"] == "synthetic"
        assert "no external source" in ok.source["label"]

    def test_computation_node_without_sources_has_no_source_block(self):
        verdict = sg.check_grounding("df = arg[0]\nreturn df.describe()", "python", _ctx())
        assert verdict.ok and verdict.source is None

    def test_computation_node_opening_a_file_is_still_checked(self):
        verdict = sg.check_grounding('df = pd.read_csv("x.csv")\nreturn df', "python", _ctx())
        assert not verdict.ok

    def test_mixed_sources(self):
        ctx = _ctx(
            catalog_paths={CATALOG_PATH: sg.CatalogRef("d", "ACS", "parquet", CATALOG_PATH)},
            probe=lambda url: {"status": "verified", "httpStatus": 200},
        )
        code = f'a = pd.read_parquet("{CATALOG_PATH}")\nb = requests.get("https://a.gov/x.json")\nreturn a'
        verdict = sg.check_grounding(code, "python", ctx)
        assert verdict.ok and verdict.source["kind"] == "mixed"
        assert len(verdict.source["refs"]) == 2


class TestRefusalText:
    def test_names_every_literal_and_only_reachable_routes(self):
        ctx = _ctx(is_data_loading=True, hints=["a `path` from a catalog.search row"])
        verdict = sg.check_grounding(ISSUE_298, "python", ctx)
        text = sg.refusal_text(verdict, ctx)
        assert text.startswith("source grounding refused — 1 ungrounded source:")
        assert "'bras_ibge_data.csv' (line 2)" in text
        assert "a path the user typed" in text
        assert "catalog.search" in text
        assert "dataset.discover" not in text  # not offered → not named
        assert "Never invent a filename" in text

    def test_payload_bounds(self):
        refs = [{"kind": "user-path", "value": f"/p/{i}.csv"} for i in range(40)]
        payload = sg.source_payload(refs)
        assert len(payload["refs"]) == sg.MAX_REFS
        assert "…and 38 more" in payload["label"]
        assert len(payload["label"]) <= 200


class TestConnectionKeys:
    """dev/116: curio_secret("<name>") refs, credential literals, the
    credential-gated hint — pure, no store."""

    CENSUS = sg.SecretRef("census", "api.census.gov", "query:key")

    def test_secret_calls_and_hosts(self):
        code = 'a = 1\nk = curio_secret("census")\nt = curio_secret(\'noaa\')\nk2 = curio_secret("census")'
        assert sg.secret_calls(code) == [("census", 2), ("noaa", 3)]
        assert sg.secret_names(code) == ["census", "noaa"]
        ctx = _ctx(secrets={"census": self.CENSUS})
        assert sg.secret_for_host(ctx, "https://API.census.gov/data/2022?x=1") is self.CENSUS
        assert sg.secret_for_host(ctx, "https://other.gov/") is None
        assert sg.secret_for_host(ctx, "not a url") is None

    def test_known_name_is_a_grounded_ref_with_its_label(self):
        ctx = _ctx(is_data_loading=True, secrets={"census": self.CENSUS},
                   verified_urls={"https://api.census.gov/data": {"status": "verified"}})
        code = ('import requests\nr = requests.get("https://api.census.gov/data", '
                'params={"key": curio_secret("census")})\nreturn r.json()')
        verdict = sg.check_grounding(code, "python", ctx)
        assert verdict.ok, verdict.violations
        secret = next(r for r in verdict.source["refs"] if r["kind"] == "secret")
        assert secret == {"kind": "secret", "value": 'curio_secret("census")', "name": "census",
                          "host": "api.census.gov", "delivery": "query:key"}
        assert "Connection key · census · api.census.gov" in verdict.source["label"]

    def test_unknown_name_is_refused_with_the_saved_names(self):
        ctx = _ctx(is_data_loading=True, secrets={"census": self.CENSUS},
                   verified_urls={"https://api.census.gov/data": {"status": "verified"}})
        code = 'import requests\nreturn requests.get("https://api.census.gov/data", params={"key": curio_secret("noaa")}).json()'
        verdict = sg.check_grounding(code, "python", ctx)
        assert not verdict.ok
        assert "curio_secret('noaa') (line 2)" in verdict.violations[0]
        assert "saved: census" in verdict.violations[0]
        # No keys saved at all: said plainly.
        verdict = sg.check_grounding(code, "python", _ctx(is_data_loading=True,
                                     verified_urls={"https://api.census.gov/data": {"status": "verified"}}))
        assert "none saved" in verdict.violations[0]

    def test_credential_literals_are_found_by_shape_never_returned(self):
        value = "AbCdEf0123456789xyzXYZ-_"
        code = (f'api_key = "{value}"\n'
                f'params = {{"get": "NAME", "key": "{value}"}}\n'
                f'r = requests.get(u, headers={{"Authorization": "Bearer {value}"}}, token="{value}")\n'
                'short = "abc"\n'
                'key = "https://api.census.gov/data"\n'          # a URL is a source, not a credential
                'dataset = "imported.census-acs@1"\n')          # a catalog id is short and not credential-named
        found = sg.credential_literals(code, "python")
        assert sorted(found) == sorted([("api_key", 1), ("key", 2), ("Authorization", 3), ("token", 3)])
        assert value not in repr(found)
        # Regex fallback for non-python content / syntax errors.
        assert sg.credential_literals(f'const key = "{value}"', "javascript") == [("key", 1)]
        assert sg.credential_literals("", "python") == []

    def test_a_pasted_key_is_refused_and_the_route_named(self):
        ctx = _ctx(is_data_loading=True,
                   verified_urls={"https://api.census.gov/data": {"status": "verified"}})
        code = ('import requests\napi_key = "AbCdEf0123456789xyzXYZ-_"\n'
                'return requests.get("https://api.census.gov/data", params={"key": api_key}).json()')
        verdict = sg.check_grounding(code, "python", ctx)
        assert not verdict.ok
        assert "api_key (line 2): a credential literal" in verdict.violations[0]
        assert 'curio_secret("<name>")' in verdict.violations[0]
        assert "AbCdEf0123456789" not in verdict.violations[0]

    def test_credential_gated_endpoint_hints_at_the_saved_key(self):
        probe = lambda url: {"status": "unreachable", "httpStatus": 401, "detail": "the endpoint answered 401"}
        with_key = _ctx(is_data_loading=True, probe=probe, secrets={"census": self.CENSUS})
        verdict = sg.check_grounding('import requests\nreturn requests.get("https://api.census.gov/data").json()',
                                     "python", with_key)
        assert verdict.ok
        ref = verdict.source["refs"][0]
        assert ref["requirement"] == "credential-gated"
        assert ref["hint"] == "a connection key 'census' is saved for this host — use api_key = curio_secret(\"census\")"
        without = sg.check_grounding('import requests\nreturn requests.get("https://api.census.gov/data").json()',
                                     "python", _ctx(is_data_loading=True, probe=probe))
        assert "hint" not in without.source["refs"][0]
