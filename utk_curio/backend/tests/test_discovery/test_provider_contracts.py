"""Do the real portals still answer in the shape our parsers expect?

These are the ONLY tests in this package that touch the network, and they run
in ordinary CI. That is safe because of one rule, which every assertion here is
built around:

    **The only way to fail is a successful response whose SHAPE changed.**
    Everything else is a skip.

Unreachable, a non-2xx, a WAF challenge, a maintenance page, an empty result
set - all skips. A portal being down, slow, or behind a captive portal is not
our bug and must never fail a PR; that is precisely the flakiness this whole
package is arranged to avoid. What these DO catch is the thing fixtures cannot:
a portal quietly renaming a field, at which point the recorded corpus is a
museum piece and every other test in this directory is passing against history.

When one fails, the fix is usually:

    conda run -n curio python scripts/record_discovery_fixtures.py --only <slug>

then read the diff and adjust the provider.

**A note on reading the results.** A run where all of these SKIP is a run that
told you nothing. That is the correct behaviour on a machine with no egress,
but if CI shows five skips forever, the signal is off rather than green - the
skips print with their reasons under ``-v``/``-ra``.
"""

from __future__ import annotations

import json

import pytest

from utk_curio.backend.app.agents.infrastructure import egress
from utk_curio.backend.app.discovery.infrastructure import transport as T

pytestmark = pytest.mark.contract


def probe(url: str):
    """Fetch and parse, or skip. Never fails for a reason outside our control."""
    try:
        result = egress.fetch(url, max_bytes=T.MAX_METADATA_BYTES)
    except Exception as exc:  # DNS, TLS, timeout, refused, policy
        pytest.skip(f"{url} unreachable: {type(exc).__name__}: {exc}")
    if not (200 <= result.status < 300):
        pytest.skip(f"{url} answered {result.status}")
    return result


def probe_json(url: str):
    result = probe(url)
    try:
        return json.loads(result.body)
    except ValueError:
        # A WAF challenge, a maintenance page or a login wall all look exactly
        # like this. None of them is a contract change.
        pytest.skip(f"{url} did not answer JSON (content-type {result.content_type!r})")


def test_socrata_search_still_carries_resource_id_and_name():
    payload = probe_json(
        "https://data.cityofchicago.org/api/catalog/v1"
        "?search_context=data.cityofchicago.org&only=dataset&limit=1&q=crimes"
    )
    results = payload.get("results")
    if not isinstance(results, list) or not results:
        pytest.skip("the portal returned no results for this query today")
    resource = results[0].get("resource")
    assert isinstance(resource, dict), "results[].resource is no longer an object"
    assert "id" in resource, "results[].resource.id is gone - SocrataProvider._row reads it"
    assert "name" in resource, "results[].resource.name is gone"


def test_socrata_view_metadata_still_carries_columns():
    payload = probe_json("https://data.cityofchicago.org/api/views/ijzp-q8t2.json")
    if not isinstance(payload, dict) or payload.get("error"):
        pytest.skip("the view endpoint did not answer a view document")
    columns = payload.get("columns")
    assert isinstance(columns, list) and columns, "columns[] is gone - describe() reads it"
    assert "fieldName" in columns[0], "columns[].fieldName is gone"


def test_ckan_package_search_still_nests_results_under_result():
    payload = probe_json(
        "https://ckan.publishing.service.gov.uk/api/3/action/package_search?rows=1&q=cycling"
    )
    if not isinstance(payload, dict) or not payload.get("success"):
        pytest.skip("the action API did not report success")
    result = payload.get("result")
    assert isinstance(result, dict), "result is no longer an object"
    results = result.get("results")
    if not isinstance(results, list) or not results:
        pytest.skip("no packages matched today")
    package = results[0]
    assert "id" in package, "result.results[].id is gone"
    assert isinstance(package.get("resources"), list), (
        "result.results[].resources is gone - CkanProvider._rows_for reads it"
    )


def test_arcgis_hub_still_answers_json_api():
    payload = probe_json("https://hub.arcgis.com/api/v3/datasets?page[size]=1&q=bike")
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list) or not data:
        pytest.skip("Hub returned no datasets for this query today")
    entry = data[0]
    assert "id" in entry, "data[].id is gone - ArcgisProvider._row reads it"
    assert isinstance(entry.get("attributes"), dict), "data[].attributes is gone"
    assert "name" in entry["attributes"], "data[].attributes.name is gone"


def test_geosampa_wfs_still_publishes_feature_types():
    from utk_curio.backend.app.discovery.providers.wfs import _parse_capabilities

    result = probe(
        "https://wms.geosampa.prefeitura.sp.gov.br/geoserver/ows"
        "?service=WFS&request=GetCapabilities&version=2.0.0"
    )
    if not result.body.lstrip().startswith("<"):
        pytest.skip("the endpoint did not answer XML")
    if result.truncated:
        # The document outgrew our metadata bound. Worth knowing, but it is a
        # capacity question rather than a contract change.
        pytest.skip(
            f"the capabilities document exceeded {T.MAX_METADATA_BYTES} bytes"
        )
    try:
        types = _parse_capabilities(result.body)
    except Exception as exc:
        pytest.fail(f"the capabilities document no longer parses: {exc}")
    assert types, "no feature types published"
    assert types[0]["name"], "FeatureType/Name is gone - WfsProvider.search reads it"


def test_the_contract_suite_is_marked_so_the_socket_guard_allows_it():
    """Meta, and load-bearing: without the marker every test above would fail
    with NetworkAccessDenied rather than reaching a portal, and the suite would
    look broken instead of informative."""
    from utk_curio.backend.tests import netguard

    assert netguard._allowed is True


def test_an_s3_listing_still_carries_keys_and_sizes():
    import xml.etree.ElementTree as ET

    url = (
        "https://sentinel-cogs.s3.us-west-2.amazonaws.com/?list-type=2&max-keys=5"
        "&prefix=sentinel-s2-l2a-cogs%2F16%2FT%2FDM%2F2024%2F7%2F"
    )
    result = probe(url)
    try:
        root = ET.fromstring(result.body)
    except ET.ParseError:
        pytest.skip("the bucket did not answer XML")
    ns = "{http://s3.amazonaws.com/doc/2006-03-01/}"
    contents = list(root.iter(f"{ns}Contents"))
    if not contents:
        pytest.skip("the prefix listed nothing today")
    assert contents[0].findtext(f"{ns}Key")
    assert contents[0].findtext(f"{ns}Size")


def test_a_hugging_face_tree_still_lists_files_with_paths_and_sizes():
    url = (
        "https://huggingface.co/api/datasets/huggingface/documentation-images/tree/main/"
        "transformers/tasks?recursive=true&expand=false"
    )
    payload = probe_json(url)
    files = [entry for entry in payload if isinstance(entry, dict) and entry.get("type") == "file"]
    if not files:
        pytest.skip("the folder listed no files today")
    assert "path" in files[0] and "size" in files[0]


# ── Keyed services: checked only with a key the person running them holds ──
#
# No key is in the repository or in CI, so these skip there. With your own key
# in the environment they check Mapillary's and Google's answers have the
# shape the providers read. The key goes in a header or a parameter of the
# request only; no message here prints it.


def _keyed_probe_json(url: str, *, key: str, **kwargs):
    try:
        result = egress.fetch(url, max_bytes=T.MAX_METADATA_BYTES, **kwargs)
    except Exception as exc:  # DNS, TLS, timeout, refused, policy
        pytest.skip(f"{url} unreachable: {type(exc).__name__}: {str(exc).replace(key, '<key>')}")
    if not (200 <= result.status < 300):
        pytest.skip(f"{url} answered {result.status}")
    try:
        return json.loads(result.body)
    except ValueError:
        pytest.skip(f"{url} did not answer JSON")


def _key(name: str) -> str:
    import os

    key = os.environ.get(name)
    if not key:
        pytest.skip(f"set {name} to your own key to check this service")
    return key


def test_a_mapillary_search_still_carries_what_the_rows_read():
    from utk_curio.backend.app.discovery.providers import mapillary

    token = _key("CURIO_MAPILLARY_TOKEN")
    payload = _keyed_probe_json(
        "https://graph.mapillary.com/images?bbox=-87.642,41.918,-87.639,41.92"
        f"&fields={mapillary.IMAGE_FIELDS}&limit=5",
        key=token, headers={"Authorization": f"OAuth {token}"},
    )
    data = payload.get("data")
    if not isinstance(data, list) or not data:
        pytest.skip("Mapillary answered no images for the box this time")
    image = data[0]
    assert "id" in image and isinstance(image.get("captured_at"), (int, float))
    assert mapillary._point(image) is not None, "neither computed_geometry nor geometry has coordinates"
    assert isinstance(image.get("creator"), dict) and "username" in image["creator"]
    thumbs = _keyed_probe_json(
        f"https://graph.mapillary.com/images?image_ids={image['id']}&fields=id,thumb_256_url",
        key=token, headers={"Authorization": f"OAuth {token}"},
    )
    url = (thumbs.get("data") or [{}])[0].get("thumb_256_url")
    assert url and mapillary.host_allowed(url, ("fbcdn.net",)), "thumbnails left the listed hosts"


def test_google_street_view_metadata_still_carries_what_the_rows_read():
    key = _key("CURIO_GOOGLE_MAPS_KEY")
    payload = _keyed_probe_json(
        "https://maps.googleapis.com/maps/api/streetview/metadata?location=41.8789,-87.6359&radius=50",
        key=key, params={"key": key},
    )
    status = payload.get("status")
    if status == "ZERO_RESULTS":
        pytest.skip("Google has no panorama at the point today")
    assert status == "OK", f"the metadata answered {status}: {payload.get('error_message')}"
    assert payload.get("pano_id")
    assert isinstance(payload.get("location"), dict) and {"lat", "lng"} <= set(payload["location"])
    assert "date" in payload
