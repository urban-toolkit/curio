#!/usr/bin/env python
"""Record the Data Lake Catalog's test fixtures from the real portals.

WHY
    The catalog is made of HTTP: five providers times search/describe/download,
    plus a federated fan-out. Testing that against live portals would make the
    suite need a network, five third parties to be up, and each of them to
    answer the same way twice - the definition of a flaky suite. So the tests
    run against a recorded corpus, and this is what records it.

    It is NOT the drift detector. ``test_provider_contracts.py`` is: those
    tests hit the real portals, assert only the response SHAPE, and skip
    whenever anything is unreachable, so they can tell you a portal changed
    without ever failing a PR for a reason outside our control. This script is
    how you FIX a drift once one is reported - in one command and a reviewable
    diff.

HOW
    Fixtures are recorded by driving the real providers through a recording
    transport, rather than by listing URLs here. That way the corpus is
    exactly what the providers ask for: a provider that changes how it builds
    a URL re-records against the new one instead of silently missing.

USAGE
    conda run -n curio python scripts/record_datalake_fixtures.py
    conda run -n curio python scripts/record_datalake_fixtures.py --only socrata

    Review the diff before committing. A fixture is test input: if a recorded
    body suddenly halves in size, that is a portal telling you something.

MEMORY
    Idempotent. Re-running overwrites the corpus in place, so a re-record is a
    git diff rather than an append.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from utk_curio.backend.app.datalakes.domain.manifest import load_source_manifest  # noqa: E402
from utk_curio.backend.app.datalakes.domain.resource import SearchQuery  # noqa: E402
from utk_curio.backend.app.datalakes.infrastructure.transport import (  # noqa: E402
    HttpLakeTransport,
)
from utk_curio.backend.app.datalakes.providers import build_provider  # noqa: E402
from utk_curio.backend.app.datalakes.service import DEFAULT_SEARCH_LIMIT  # noqa: E402

FIXTURES = REPO / "utk_curio" / "backend" / "tests" / "test_datalakes" / "fixtures"

#: One representative query per source, chosen to return rows that are stable
#: and recognisable rather than whatever is trending.
PLAN = {
    "lake.cityofchicago.data-portal@1": {"slug": "socrata", "q": "crimes"},
    "lake.uk.data-gov@1": {"slug": "ckan", "q": "cycling"},
    "lake.esri.hub-opendata@1": {"slug": "arcgis", "q": "bike lanes"},
    "lake.saopaulo.geosampa@1": {"slug": "wfs", "q": "ciclo"},
}


class RecordingTransport:
    """Wraps the real transport and writes what it sees."""

    def __init__(self, slug: str, index: dict) -> None:
        self.slug = slug
        self.index = index
        self.inner = HttpLakeTransport()
        self.seq = 0

    def json_get(self, url, *, credential=None, headers=None):
        body = self.inner.json_get(url, credential=credential, headers=headers)
        self.seq += 1
        suffix = "xml" if body.lstrip().startswith("<") else "json"
        name = f"{self.slug}/{self.seq:02d}.{suffix}"
        path = FIXTURES / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
        self.index[url] = {
            "file": name,
            "status": 200,
            "headers": {"Content-Type": "application/xml" if suffix == "xml" else "application/json"},
        }
        print(f"    {len(body):>8}B  {name}  <- {url[:96]}")
        return body

    def download(self, *a, **k):  # pragma: no cover - recording metadata only
        raise NotImplementedError("downloads are recorded by hand; see the index")


def record(slug_filter: str | None) -> None:
    index_path = FIXTURES / "index.json"
    index = json.loads(index_path.read_text(encoding="utf-8")) if index_path.is_file() else {}

    for dir_name, plan in PLAN.items():
        if slug_filter and plan["slug"] != slug_filter:
            continue
        source = REPO / "datalakes" / dir_name
        if not source.is_dir():
            print(f"!!  {dir_name} is not in datalakes/ - skipped")
            continue
        manifest = load_source_manifest(source)
        print(f"\n==  {manifest.name}  ({plan['slug']})")
        transport = RecordingTransport(plan["slug"], index)
        provider = build_provider(manifest, transport)
        try:
            # The app's own default, imported rather than restated. A corpus
            # recorded at any other limit answers a question the app never
            # asks: the limit is in the Socrata and CKAN request URLs, so a
            # recording at 5 is simply missing when the browser asks for 20,
            # and the only symptom is an empty result list in a browser test.
            page = provider.search(SearchQuery(text=plan["q"], limit=DEFAULT_SEARCH_LIMIT))
        except Exception as exc:  # noqa: BLE001 - a portal being down is not a crash
            print(f"    search failed: {type(exc).__name__}: {exc}")
            continue
        print(f"    -> {len(page.resources)} rows")
        if page.resources:
            first = page.resources[0]
            try:
                provider.describe(first.resource_id)
                print(f"    described {first.resource_id}")
            except Exception as exc:  # noqa: BLE001
                print(f"    describe failed: {type(exc).__name__}: {exc}")

    FIXTURES.mkdir(parents=True, exist_ok=True)
    index_path.write_text(json.dumps(index, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"\nwrote {index_path} ({len(index)} entries)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", help="record one provider slug (socrata, ckan, arcgis, wfs)")
    record(parser.parse_args().only)
