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
) -> Tuple[List[dict], List[dict], str]:
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
        ``(enriched_points, aggregates, tag_column)``. ``enriched_points``
        preserves input order and adds:

        * ``<tag_column>``: the containing polygon's value of ``name_property``,
          or None for a point outside every polygon. The column is named after
          the polygon column itself (``zip`` stays ``zip``); when the points
          already carry a column of that name the tag goes to
          ``<name_property>_polygon`` instead, so nothing is overwritten.
        * ``<tag_column>_point_count``: how many points fell in the same
          polygon (None for an untagged point).
        * ``<tag_column>_dominant_class`` / ``<tag_column>_dominant_pct``: only
          when the points carry a ``dominant_class`` (the street-vision case),
          the polygon's modal class and its mean confidence.

        ``aggregates`` is the per-polygon roll-up, one row per polygon that
        received at least one point, keyed by ``tag_column``. See
        :func:`polygons_with_counts` for the other output shape.

        The join was carved out of the street-vision pipeline, whose tag column
        was hard-coded to ``neighborhood_name`` and whose roll-ups were
        ``nbhd_*``; a roof tagged with a ZIP code deserves better names.
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
            name = polygon_tag(props, name_property, i)
            if name == f"polygon_{i}":
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
                f"No polygon has a '{name_property}' column, so tags fall back to "
                f"polygon_<index>. Available columns: {available or 'none'}."
            )
        else:
            warnings.append(
                f"{unnamed} of {len(polygons)} polygons lack a '{name_property}' "
                f"column and are tagged polygon_<index>."
            )

    # The tag column is the polygon column itself, unless the points already
    # have one of that name, in which case it is suffixed rather than clobbered.
    tag_column = name_property
    if any(name_property in p for p in points):
        tag_column = f"{name_property}_polygon"

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
        enriched.append({**p, tag_column: tag})
        if tag:
            groups.setdefault(tag, []).append(p)

    aggregates: List[dict] = []
    for name, group in groups.items():
        row: dict = {tag_column: name, "point_count": len(group)}
        classes = [g.get("dominant_class") for g in group if g.get("dominant_class")]
        if classes:
            counter = Counter(classes)
            top_class, _ = counter.most_common(1)[0]
            relevant_pcts = [
                g.get("dominant_pct", 0) for g in group if g.get("dominant_class") == top_class
            ]
            row["dominant_class"] = top_class
            row["dominant_pct"] = round(sum(relevant_pcts) / max(len(relevant_pcts), 1), 2)
            row["top3"] = [{"class": c, "count": cnt} for c, cnt in counter.most_common(3)]
        aggregates.append(row)

    # Project the roll-up back onto each member point so a Vega-Lite spec can
    # size or colour by it without a separate dataset. The count is always
    # there; the class fields only when some point carried a dominant class.
    any_class = any("dominant_class" in agg for agg in aggregates)
    agg_lookup = {agg[tag_column]: agg for agg in aggregates}
    for ep in enriched:
        agg = agg_lookup.get(ep.get(tag_column))
        ep[f"{tag_column}_point_count"] = agg["point_count"] if agg else None
        if any_class:
            ep[f"{tag_column}_dominant_class"] = agg.get("dominant_class") if agg else None
            ep[f"{tag_column}_dominant_pct"] = agg.get("dominant_pct") if agg else None

    return enriched, aggregates, tag_column


def polygon_tag(props: dict, name_property: str, index: int) -> str:
    """The tag a polygon contributes: its ``name_property``, else ``polygon_<index>``."""
    name = props.get(name_property) if isinstance(props, dict) else None
    if not isinstance(name, str) or not name:
        return f"polygon_{index}"
    return name


def polygons_with_counts(
    polygon_fc: dict,
    aggregates: List[dict],
    tag_column: str,
    name_property: str = "name",
) -> List[dict]:
    """The other output shape: the polygons, each with its roll-up.

    Every polygon feature comes back with ``point_count`` (0 when nothing fell
    inside) and, when the points carried a ``dominant_class``,
    ``dominant_class`` and ``dominant_pct``. Geometry and the polygon's own
    properties are untouched, so a choropleth is one ``geoshape`` away and a
    bar chart of counts is the same rows without the geometry.
    """
    by_tag = {agg[tag_column]: agg for agg in aggregates}
    any_class = any("dominant_class" in agg for agg in aggregates)
    out: List[dict] = []
    for i, feat in enumerate(polygon_fc.get("features") or []):
        props = dict(feat.get("properties") or {})
        agg = by_tag.get(polygon_tag(props, name_property, i))
        props["point_count"] = agg["point_count"] if agg else 0
        if any_class:
            props["dominant_class"] = agg.get("dominant_class") if agg else None
            props["dominant_pct"] = agg.get("dominant_pct") if agg else None
        out.append({"type": "Feature", "geometry": feat.get("geometry"), "properties": props})
    return out
