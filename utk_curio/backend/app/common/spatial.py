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
    warnings: Optional[List[str]] = None,
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
        warnings: optional list the function appends human-readable warnings
            to - today, that polygons lacked ``name_property`` (#262). The
            fallback to ``polygon_<index>`` used to be silent, so a wrong
            property name looked like a successful join.

    Returns:
        ``(enriched_points, aggregates)``. ``enriched_points`` preserves
        input order and adds one column, ``joined``: the containing polygon's
        tag, or None for a point outside every polygon. When the points carry
        a ``dominant_class`` (the street-vision case) three more columns are
        projected onto every point: ``joined_dominant_class``,
        ``joined_dominant_pct`` and ``joined_count``, the roll-up of the
        polygon the point fell in. Points without a dominant class get no
        roll-up columns at all, rather than three empty ones. ``aggregates``
        is that per-polygon roll-up, keyed by ``joined``.

        The names are deliberately generic. The join was carved out of the
        street-vision pipeline, whose tag column was ``neighborhood_name``
        and whose roll-ups were ``nbhd_*``, which read as nonsense on a roof
        tagged with a ZIP code.
    """
    # shapely is a heavy-ish geospatial dep; keep it lazy so a Curio install
    # without the spatial extras can still import this module.
    from shapely.geometry import Point, shape
    from shapely.strtree import STRtree

    polygons = []
    names = []
    unnamed = 0
    seen_props: set = set()
    for i, feat in enumerate(polygon_fc.get("features", [])):
        try:
            polygons.append(shape(feat["geometry"]))
            props = feat.get("properties") or {}
            seen_props.update(k for k in props.keys() if isinstance(k, str))
            name = props.get(name_property)
            if not isinstance(name, str) or not name:
                name = f"polygon_{i}"
                unnamed += 1
            names.append(name)
        except Exception:
            # Skip malformed features; one bad polygon shouldn't abort the join.
            continue
    tree = STRtree(polygons) if polygons else None

    if warnings is not None and polygons and unnamed:
        if unnamed == len(polygons):
            available = ", ".join(sorted(k for k in seen_props if k != "geometry")[:12])
            warnings.append(
                f"No polygon has a '{name_property}' property, so tags fall back to "
                f"polygon_<index>. Available properties: {available or 'none'}."
            )
        else:
            warnings.append(
                f"{unnamed} of {len(polygons)} polygons lack a '{name_property}' "
                f"property and are tagged polygon_<index>."
            )

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
        enriched.append({**p, "joined": tag})
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
            "joined": name,
            "image_count": len(group),
            "dominant_class": top_class,
            "dominant_pct": round(avg_pct, 2),
            "top3": top3,
        })

    # Project per-polygon aggregates back onto each member point so a Vega-Lite
    # spec can colour by the rolled-up class/pct/count without us shipping a
    # separate dataset. Only when there is a roll-up at all: a join over points
    # with no dominant class adds nothing here.
    if aggregates:
        agg_lookup = {agg["joined"]: agg for agg in aggregates}
        for ep in enriched:
            agg = agg_lookup.get(ep.get("joined"))
            ep["joined_dominant_class"] = agg["dominant_class"] if agg else None
            ep["joined_dominant_pct"] = agg["dominant_pct"] if agg else None
            ep["joined_count"] = agg["image_count"] if agg else None

    return enriched, aggregates
