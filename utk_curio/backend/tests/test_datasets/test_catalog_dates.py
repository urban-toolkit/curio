"""The catalog's **Recent activity** order, and the date of a layer group.

Both sides run the cases in ``catalogDates.cases.json`` beside
``services/datasetCatalog/catalogDates.ts``
(``src/tests/services/catalogDatesCases.test.tsx`` is the other half: the
canvas's Data palette shows the listing in its order). Dates read as times: to
the second, the millisecond or the microsecond, with ``Z`` or an offset, and a
missing or unreadable date is the oldest. Here the cases run through the
listing's order (``updatedAt``, then title, then id; never the import or the
install time) and through the date a layer group takes from its layers.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from utk_curio.backend.app.datasets.application.listing import _sort_catalog_items
from utk_curio.backend.app.datasets.domain.layer_group import build_layer_group_item

CASES_FILE = (
    Path(__file__).resolve().parents[3]
    / "frontend" / "urban-workflows" / "src" / "services" / "datasetCatalog" / "catalogDates.cases.json"
)

LAYERS = ("points", "lines", "multipolygons", "other_relations")


def _cases(key: str):
    if not CASES_FILE.is_file():
        return [pytest.param(None, id="cases-file-missing")]
    cases = json.loads(CASES_FILE.read_text(encoding="utf-8"))[key]
    return [pytest.param(case, id=case["name"]) for case in cases]


@pytest.mark.parametrize("case", _cases("cases"))
def test_recent_activity_lists_the_items_in_order(case):
    assert case is not None, f"{CASES_FILE} is missing"
    expected = [row["id"] for row in case["items"]]
    for given in (list(reversed(case["items"])), list(case["items"])):
        items = [dict(row) for row in given]
        _sort_catalog_items(items, "recent")
        assert [item["id"] for item in items] == expected


@pytest.mark.parametrize("case", _cases("groups"))
def test_a_layer_group_takes_the_date_of_its_latest_layer(case):
    assert case is not None, f"{CASES_FILE} is missing"
    members = [
        {
            "id": f"imported.xdates{layer}",
            "title": f"dates ({layer})",
            "format": "geojson",
            "layerName": layer,
            "groupId": "osm.xdates",
            "updatedAt": stamp,
        }
        for layer, stamp in zip(LAYERS, case["layers"])
    ]
    assert build_layer_group_item("osm.xdates", members)["updatedAt"] == case["updatedAt"]
