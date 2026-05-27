"""Generic spatial-join helper: tag each point with the polygon it falls in.

Backs the ``/spatial_join`` endpoint in ``app/api/routes.py`` which in turn
powers the Spatial Join node in ``curio.builtin@1``. Lazy-imports
``shapely`` so this module remains importable even on installs without
geospatial extras; the route layer surfaces an ImportError as a 503 response.

Originally adapted from the per-neighborhood enrichment helper in
github.com/ManeeshJupalle/Street-Level-Vision-Analytics-Node-for-Curio,
generalized here to accept caller-supplied polygons (instead of bundling a
hardcoded Chicago basemap) and made reusable beyond CV pipelines.
"""

from collections import Counter
from typing import List, Optional, Tuple


def enrich_points_with_polygons(
    points: List[dict],
    polygon_fc: dict,
    name_property: str = "name",
) -> Tuple[List[dict], List[dict]]:
    """Tag each point with the containing polygon + compute per-polygon aggregates.

    Args:
        points: list of dicts with at least ``latitude``, ``longitude``.
            May also carry ``dominant_class``, ``dominant_pct`` (used to roll
            up a "modal class per polygon"), or any other keys (preserved
            in the output).
        polygon_fc: GeoJSON FeatureCollection of Polygon / MultiPolygon
            features. Each feature should have ``properties.<name_property>``
            as a string; missing names fall back to ``polygon_<index>``.
        name_property: which property field is used as the polygon's tag.

    Returns:
        ``(enriched_points, aggregates)``. ``enriched_points`` preserves
        input order and adds ``neighborhood_name`` plus the rolled-up
        ``nbhd_*`` fields (any may be None if a point fell outside every
        polygon). ``aggregates`` is a per-polygon roll-up keyed by name.
    """
    # shapely is a heavy-ish geospatial dep; keep it lazy so a Curio install
    # without the spatial extras can still import this module.
    from shapely.geometry import Point, shape
    from shapely.strtree import STRtree

    polygons = []
    names = []
    for i, feat in enumerate(polygon_fc.get("features", [])):
        try:
            polygons.append(shape(feat["geometry"]))
            props = feat.get("properties") or {}
            name = props.get(name_property)
            if not isinstance(name, str) or not name:
                name = f"polygon_{i}"
            names.append(name)
        except Exception:
            # Skip malformed features; one bad polygon shouldn't abort the join.
            continue
    tree = STRtree(polygons) if polygons else None

    enriched: List[dict] = []
    groups: dict = {}

    for p in points:
        lat, lon = p.get("latitude"), p.get("longitude")
        tag: Optional[str] = None
        if lat is not None and lon is not None and tree is not None:
            pt = Point(lon, lat)
            for idx in tree.query(pt):
                if polygons[idx].contains(pt):
                    tag = names[idx]
                    break
        enriched.append({**p, "neighborhood_name": tag})
        if tag:
            groups.setdefault(tag, []).append(p)

    aggregates: List[dict] = []
    for name, group in groups.items():
        classes = [g.get("dominant_class") for g in group if g.get("dominant_class")]
        if not classes:
            continue
        counter = Counter(classes)
        top_class, _ = counter.most_common(1)[0]
        relevant_pcts = [
            g.get("dominant_pct", 0) for g in group if g.get("dominant_class") == top_class
        ]
        avg_pct = sum(relevant_pcts) / max(len(relevant_pcts), 1)
        top3 = [{"class": c, "count": cnt} for c, cnt in counter.most_common(3)]
        aggregates.append({
            "neighborhood_name": name,
            "image_count": len(group),
            "dominant_class": top_class,
            "dominant_pct": round(avg_pct, 2),
            "top3": top3,
        })

    # Project per-polygon aggregates back onto each member point so a Vega-Lite
    # `lookup` (basemap.name → point.neighborhood_name) can pick up the
    # rolled-up class/pct/count without us shipping a separate dataset.
    agg_lookup = {a["neighborhood_name"]: a for a in aggregates}
    for ep in enriched:
        nm = ep.get("neighborhood_name")
        if nm and nm in agg_lookup:
            a = agg_lookup[nm]
            ep["nbhd_dominant_class"] = a["dominant_class"]
            ep["nbhd_dominant_pct"] = a["dominant_pct"]
            ep["nbhd_image_count"] = a["image_count"]
        else:
            ep["nbhd_dominant_class"] = None
            ep["nbhd_dominant_pct"] = None
            ep["nbhd_image_count"] = None

    return enriched, aggregates
