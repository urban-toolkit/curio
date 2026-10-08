"""The catalog's Recent activity order, case by case.

``catalog_recent_order.json`` lists each case's items in the order the listing
gives them. The listing runs them here, and the canvas's Data palette runs the
same cases in ``src/tests/parity/catalogRecentOrder.test.ts``, so the two read
dates the same way: as times, whether written to the second, the millisecond or
the microsecond, with ``Z`` or an offset, and a missing or unreadable date as
the oldest. A layer group takes the date of its latest layer, read the same way.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from utk_curio.backend.app.datasets.application.listing import _sort_catalog_items
from utk_curio.backend.app.datasets.domain.layer_group import build_layer_group_item

CASES = json.loads(Path(__file__).with_name("catalog_recent_order.json").read_text(encoding="utf-8"))

LAYERS = ("points", "lines", "multipolygons", "other_relations")


@pytest.mark.parametrize("case", CASES["recent"], ids=lambda case: case["case"])
def test_recent_activity_lists_each_case_in_its_order(case):
    expected = [row["id"] for row in case["items"]]
    for given in (list(reversed(case["items"])), list(case["items"])):
        items = [dict(row) for row in given]
        _sort_catalog_items(items, "recent")
        assert [item["id"] for item in items] == expected


@pytest.mark.parametrize("case", CASES["groups"], ids=lambda case: case["case"])
def test_a_layer_group_takes_the_date_of_its_latest_layer(case):
    members = [
        {
            "id": f"imported.xparity{layer}",
            "title": f"parity ({layer})",
            "format": "geojson",
            "layerName": layer,
            "groupId": "osm.xparity",
            "updatedAt": stamp,
        }
        for layer, stamp in zip(LAYERS, case["layers"])
    ]
    assert build_layer_group_item("osm.xparity", members)["updatedAt"] == case["updatedAt"]
