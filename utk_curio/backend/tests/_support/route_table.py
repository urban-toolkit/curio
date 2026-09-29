"""A blueprint's route table is a contract (memo dev/142 B4, shared by dev/143 §7).

``route_table`` lists every rule a blueprint registers — its URL rule, its
methods and its endpoint name — and ``assert_route_table_unchanged`` compares
that list against a JSON fixture recorded before a presentation refactor. A
refactor may move handlers between modules; it may not add, drop, rename or
re-method a route. To re-record after an INTENDED API change, run the test
with ``CURIO_ROUTE_TABLE_RECORD=1`` and commit the fixture with the change.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from flask import Blueprint, Flask


def route_table(blueprint: Blueprint, endpoint_prefix: str) -> list[dict]:
    app = Flask("route-table")
    app.register_blueprint(blueprint)
    rows = [
        {
            "rule": r.rule,
            "methods": sorted(m for m in r.methods if m not in ("HEAD", "OPTIONS")),
            "endpoint": r.endpoint,
        }
        for r in app.url_map.iter_rules()
        if r.endpoint.startswith(endpoint_prefix)
    ]
    return sorted(rows, key=lambda x: (x["rule"], x["methods"]))


def assert_route_table_unchanged(blueprint: Blueprint, endpoint_prefix: str, fixture: Path, *, what: str) -> None:
    actual = route_table(blueprint, endpoint_prefix)
    if os.environ.get("CURIO_ROUTE_TABLE_RECORD") == "1":
        fixture.write_text(json.dumps(actual, indent=1) + "\n")
    expected = json.loads(fixture.read_text())
    assert actual == expected, f"the {what} route table changed; see the module docstring"
