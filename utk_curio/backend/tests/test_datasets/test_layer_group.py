"""What a layer group's card says (issue #586).

A ``.pbf`` upload lands as one dataset per layer under an ``osm.x<hex>`` group,
and its card says what the file was: an OSM import, tagged ``osm`` and ``pbf``.
A Discovery download that lands several layers forms an ``osm.`` group too, but
no ``.pbf`` was involved: its card says what each of its layers says, as a
single download's card does, including where they were downloaded from.
"""

from __future__ import annotations

from utk_curio.backend.app.datasets.domain.layer_group import build_layer_group_item

PROVENANCE = {
    "sourceId": "source.openstreetmap.autark@1",
    "sourceName": "OpenStreetMap",
    "resourceId": "pois",
    "fetchedAt": "2026-10-02T00:00:00Z",
    "parameters": {"area": {"box": [-87.64, 41.87, -87.61, 41.89]}},
    "parametersHash": "abc123",
}


def _member(layer: str, *, group_id: str, fmt: str, tags: list[str], discovery_source=None) -> dict:
    return {
        "id": f"imported.x{layer}",
        "title": f"Points of interest, Loop ({layer})",
        "format": fmt,
        "layerName": layer,
        "groupId": group_id,
        "featureCount": 10,
        "sizeBytes": 100,
        "updatedAt": "2026-10-02T00:00:00Z",
        "sourceLabel": "Imported",
        "tags": tags,
        "installed": False,
        "discoverySource": discovery_source,
    }


def test_a_discovery_download_group_says_what_its_layers_say():
    downloaded = [
        _member(layer, group_id="osm.x1a2b3c4", fmt="geojson", tags=["geojson", "imported"], discovery_source=PROVENANCE)
        for layer in ("points", "polygons")
    ]
    group = build_layer_group_item("osm.x1a2b3c4", downloaded)

    # As a single download of one of these layers reads.
    assert group["format"] == "geojson"
    assert group["sourceLabel"] == "Imported"
    assert group["tags"] == ["geojson", "imported"]
    assert group["discoverySource"] == PROVENANCE
    assert "pbf" not in group["tags"]

    # Still the group: its id, its uri, its layers and its loader do not change.
    uploaded = build_layer_group_item(
        "osm.x1a2b3c4",
        [_member(layer, group_id="osm.x1a2b3c4", fmt="parquet", tags=["parquet", "imported"]) for layer in ("points", "lines")],
    )
    assert group["id"] == "osm.x1a2b3c4"
    assert group["uri"] == uploaded["uri"] == "curio://osm/osm.x1a2b3c4"
    assert group["groupLayerIds"] == ["imported.xpoints", "imported.xpolygons"]
    assert group["loaderSnippet"] == uploaded["loaderSnippet"]

    # A .pbf upload keeps saying what its file was.
    assert uploaded["format"] == "osm"
    assert uploaded["sourceLabel"] == "OSM Import"
    assert uploaded["tags"] == ["osm", "pbf"]
    assert uploaded["discoverySource"] is None

    # Only when every layer was downloaded.
    mixed = build_layer_group_item("osm.x1a2b3c4", [downloaded[0], {**downloaded[1], "discoverySource": None}])
    assert mixed["sourceLabel"] == "OSM Import"
    assert mixed["discoverySource"] is None


def test_a_shipped_group_says_what_its_layers_say_and_keeps_its_kind():
    """Layers that ship in the catalog every account shares, as a hub row or
    its installed ``data.*`` copy: the group takes their source label and tags
    and is a hub entry, but it keeps its kind's format, which is what the
    canvas palette shows for it (``layerGroupFormat``)."""
    shipped = [
        {
            **_member(layer, group_id="osm.x1a2b3c4", fmt="parquet", tags=["osm", "chicago"]),
            "id": f"data.utk.loop-{layer}",
            "origin": "hub",
            "sourceLabel": "Curio",
        }
        for layer in ("points", "lines")
    ]
    installed = [{**shipped[0], "origin": "imported", "dirName": "data.utk.loop-points@1"}, shipped[1]]
    for members in (shipped, installed):
        group = build_layer_group_item("osm.x1a2b3c4", members)
        assert group["format"] == "osm"
        assert (group["sourceLabel"], group["tags"], group["origin"]) == ("Curio", ["osm", "chicago"], "hub")

    # One layer of the user's own keeps the group an import.
    own = build_layer_group_item("osm.x1a2b3c4", [shipped[0], {**shipped[1], "origin": "imported"}])
    assert (own["sourceLabel"], own["origin"]) == ("OSM Import", "imported")
