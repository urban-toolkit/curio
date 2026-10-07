"""What a layer group's card says (issue #586).

A ``.pbf`` upload lands as one dataset per layer under an ``osm.x<hex>`` group,
and its card says what the file was: an OSM import, tagged ``osm`` and ``pbf``.
A Discovery download that lands several layers forms an ``osm.`` group too, but
no ``.pbf`` was involved: its card says what each of its layers says, as a
single download's card does, including where they were downloaded from.

What a card loads (issue #724): the group id names no file, so its loader reads
each layer by its own id, and the card lists its layers.
"""

from __future__ import annotations

import pytest

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
    # The same layers uploaded give the same loader.
    same_layers_uploaded = build_layer_group_item(
        "osm.x1a2b3c4",
        [{**m, "format": "parquet", "tags": ["parquet", "imported"], "discoverySource": None} for m in downloaded],
    )
    assert group["loaderSnippet"] == same_layers_uploaded["loaderSnippet"]

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


@pytest.mark.parametrize("group_id", ["osm.x1a2b3c4", "gpkg.x1a2b3c4", "gtfs.x1a2b3c4"])
def test_a_group_card_loads_each_of_its_layers(group_id, tmp_path):
    """The Data Catalog drawer lists a layer group as one card, and a card
    dropped on the canvas becomes a Data Loading node (#724). Its loader reads
    each layer by its own id into one ``layers`` dict and returns it, as the
    palette's group drag does, and the card lists its layers, so the node can
    reference them rather than the group id."""
    pd = pytest.importorskip("pandas")
    from utk_curio.sandbox.util.catalog_helpers import install_catalog_helpers

    members, paths = [], {}
    for layer in ("routes", "stops"):
        path = tmp_path / f"{layer}.parquet"
        pd.DataFrame({"name": [f"{layer} 1", f"{layer} 2"]}).to_parquet(path)
        member = {
            **_member(layer, group_id=group_id, fmt="parquet", tags=["parquet", "imported"]),
            "uri": f"curio://datasets/imported.x{layer}@1",
            "path": path.as_posix(),
        }
        members.append(member)
        paths[member["id"]] = str(path)

    group = build_layer_group_item(group_id, members)

    snippet = group["loaderSnippet"]
    assert group_id not in snippet["code"], f"the card's loader reads the group id: {snippet['code']!r}"
    assert snippet["returnVariable"] == "layers", snippet
    # Run the loader the way a node runs it, against the sandbox's helpers.
    namespace: dict = {}
    install_catalog_helpers(
        namespace,
        data_path=paths.__getitem__,
        formats={dataset_id: {"format": "parquet"} for dataset_id in paths},
        collections=None,
        media_dir=None,
        models=None,
    )
    exec(snippet["code"], namespace)  # noqa: S102 - running the generated loader on purpose
    layers = namespace[snippet["returnVariable"]]
    assert {name: list(frame["name"]) for name, frame in layers.items()} == {
        "routes": ["routes 1", "routes 2"],
        "stops": ["stops 1", "stops 2"],
    }

    assert group["groupLayers"] == [
        {
            "id": m["id"],
            "title": m["title"],
            "uri": m["uri"],
            "path": m["path"],
            "format": "parquet",
            "layerName": m["layerName"],
        }
        for m in members
    ]
