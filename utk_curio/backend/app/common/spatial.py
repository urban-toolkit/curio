"""Spatial Join: pair the rows of two GeoJSON inputs whose shapes meet (#576).

Backs the ``/spatial_join`` endpoint in ``app/api/routes.py``, which in turn
powers the Spatial Join node in ``curio.builtin@1``. Input 0 is the left side
of the join and input 1 the right, as geopandas names them: ``sjoin`` finds
the pairs for every operation but ``nearest``, which is ``sjoin_nearest``.

geopandas is imported inside the functions, so this module stays importable on
an install without it; the route answers that case with a 503.
"""

from collections import Counter
from typing import Any, Dict, List, Optional, Tuple

PREDICATES = ("intersects", "within", "contains", "touches", "overlaps", "crosses", "nearest")
OUTPUTS = ("pairs", "counts")
DEFAULT_PREDICATE = "intersects"
DEFAULT_OUTPUT = "pairs"

#: What a clashing input 1 column is renamed with, so no input 0 column is overwritten.
RIGHT_SUFFIX = "_right"
#: The column the counts output gives each input 1 row.
COUNT_COLUMN = "point_count"
#: The column ``nearest`` adds: the distance between the pair, in meters.
DISTANCE_COLUMN = "distance"

_KINDS = {0: "point", 1: "line", 2: "polygon"}


class JoinInputError(ValueError):
    """A request the join cannot run. The message says what to change."""


def spatial_join(
    left_fc: Any,
    right_fc: Any,
    predicate: str = DEFAULT_PREDICATE,
    output: str = DEFAULT_OUTPUT,
) -> Dict[str, Any]:
    """Join *left_fc* (input 0) to *right_fc* (input 1) by *predicate*.

    ``output="pairs"`` gives one feature per matching pair: input 0's row and
    geometry, with input 1's columns added (``<column>_right`` on a clash).
    ``output="counts"`` gives input 1's features, each with ``point_count``,
    the number of input 0 rows paired with it.

    A point on a polygon's edge follows shapely's rule for the operation: it
    intersects and touches the polygon, and is not within it.
    """
    if predicate not in PREDICATES:
        raise JoinInputError(f"The operation must be one of {', '.join(PREDICATES)}; got {predicate!r}.")
    if output not in OUTPUTS:
        raise JoinInputError(f"The output must be one of {', '.join(OUTPUTS)}; got {output!r}.")
    left_features = _features(left_fc, "Input 0")
    right_features = _features(right_fc, "Input 1")
    left = _frame(left_features, left_fc, "Input 0")
    right = _frame(right_features, right_fc, "Input 1")
    if right.crs != left.crs:
        right = right.to_crs(left.crs)

    pairs = _pairs(left, right, predicate)
    warnings: List[str] = []
    if not pairs and len(left) and len(right):
        hint = _never_matches_hint(predicate, _dimension(left), _dimension(right))
        if hint:
            warnings.append(hint)

    if output == "counts":
        counts = Counter(j for _, j, _ in pairs)
        features = []
        for j, feat in enumerate(right_features):
            props = dict(feat.get("properties") or {})
            props[COUNT_COLUMN] = counts.get(j, 0)
            features.append({"type": "Feature", "geometry": feat.get("geometry"), "properties": props})
        crs_member = right_fc.get("crs")
    else:
        features = _pair_features(left_features, right_features, pairs, predicate == "nearest")
        crs_member = left_fc.get("crs")

    metadata: Dict[str, Any] = {
        "name": "spatial_join_result",
        "output": output,
        "predicate": predicate,
        "pairs": len(pairs),
        "matched_left": len({i for i, _, _ in pairs}),
        "matched_right": len({j for _, j, _ in pairs}),
        "left_rows": len(left_features),
        "right_rows": len(right_features),
    }
    if warnings:
        metadata["warnings"] = warnings
    result: Dict[str, Any] = {"type": "FeatureCollection", "features": features, "metadata": metadata}
    if crs_member is not None:
        result["crs"] = crs_member
    return result


def _features(fc: Any, name: str) -> List[dict]:
    """The features of a GeoJSON FeatureCollection, or a message saying it is not one."""
    features = fc.get("features") if isinstance(fc, dict) else None
    if not isinstance(features, list):
        raise JoinInputError(
            f"{name} is not geodata: connect a node whose output has a geometry column "
            "(a GeoDataFrame) to its circle."
        )
    return [f if isinstance(f, dict) else {} for f in features]


def _frame(features: List[dict], fc: dict, name: str):
    """A GeoDataFrame of the features' geometries alone, in the collection's CRS.

    The sandbox writes a GeoDataFrame's CRS as the collection's ``crs`` member
    (``sandbox/util/parsers.py``); without one, GeoJSON means longitude and
    latitude. A geometry that cannot be read is left empty and pairs with
    nothing, as a row without a geometry does.
    """
    import geopandas as gpd
    from pyproj import CRS
    from shapely.geometry import shape

    geometries = []
    for feat in features:
        raw = feat.get("geometry")
        try:
            geometries.append(shape(raw) if raw else None)
        except Exception:
            geometries.append(None)
    crs_name = None
    member = fc.get("crs")
    if isinstance(member, dict):
        crs_name = (member.get("properties") or {}).get("name")
    try:
        crs = CRS.from_user_input(crs_name or "EPSG:4326")
    except Exception:
        raise JoinInputError(f"{name} has a coordinate system Curio cannot read: {crs_name!r}.") from None
    return gpd.GeoDataFrame(geometry=geometries, crs=crs)


def _pairs(left, right, predicate: str) -> List[Tuple[int, int, Optional[float]]]:
    """``(input 0 row, input 1 row, distance)`` for every matching pair, in input 0's order."""
    import geopandas as gpd

    left = left[left.geometry.notna() & ~left.geometry.is_empty]
    right = right[right.geometry.notna() & ~right.geometry.is_empty]
    if left.empty or right.empty:
        return []
    if predicate == "nearest":
        # In degrees the nearest polygon is the wrong one away from the
        # equator, and a distance in degrees means nothing to anyone: measure
        # in the UTM zone of input 0, in meters.
        metric = left.estimate_utm_crs()
        joined = gpd.sjoin_nearest(
            left.to_crs(metric), right.to_crs(metric), how="inner", distance_col=DISTANCE_COLUMN,
        )
        rows = [
            (int(i), int(j), round(float(d), 2))
            for i, j, d in zip(joined.index, joined["index_right"], joined[DISTANCE_COLUMN])
        ]
    else:
        joined = gpd.sjoin(left, right, how="inner", predicate=predicate)
        rows = [(int(i), int(j), None) for i, j in zip(joined.index, joined["index_right"])]
    return sorted(rows)


def _pair_features(
    left_features: List[dict],
    right_features: List[dict],
    pairs: List[Tuple[int, int, Optional[float]]],
    with_distance: bool,
) -> List[dict]:
    """One feature per pair: input 0's row and geometry, input 1's columns added.

    Built from the features as they came, so every value keeps its JSON form.
    """
    left_columns = {k for f in left_features for k in (f.get("properties") or {})}
    right_columns = {k for f in right_features for k in (f.get("properties") or {})}
    taken = set(left_columns)
    renamed: Dict[str, str] = {}
    for column in sorted(right_columns):
        name = column
        while name in taken:
            name = f"{name}{RIGHT_SUFFIX}"
        renamed[column] = name
        taken.add(name)
    distance_column = DISTANCE_COLUMN
    while distance_column in taken:
        distance_column = f"{distance_column}{RIGHT_SUFFIX}"

    out: List[dict] = []
    for i, j, distance in pairs:
        left_feat = left_features[i]
        props = dict(left_feat.get("properties") or {})
        for column, value in (right_features[j].get("properties") or {}).items():
            props[renamed[column]] = value
        if with_distance:
            props[distance_column] = distance
        out.append({"type": "Feature", "geometry": left_feat.get("geometry"), "properties": props})
    return out


def _dimension(frame) -> Optional[int]:
    """0, 1 or 2 when every geometry of *frame* is points, lines or polygons; else None."""
    import shapely

    geometries = frame.geometry[frame.geometry.notna() & ~frame.geometry.is_empty]
    dims = {int(d) for d in shapely.get_dimensions(geometries.to_numpy())}
    return dims.pop() if len(dims) == 1 else None


def _never_matches_hint(predicate: str, left_dim: Optional[int], right_dim: Optional[int]) -> Optional[str]:
    """Why an operation found no pairs when it never can for these shapes, and what to pick."""
    if left_dim is None or right_dim is None:
        return None
    left_kind, right_kind = _KINDS[left_dim], _KINDS[right_dim]
    if predicate == "within" and left_dim > right_dim:
        return (f"No pairs: a {left_kind} is never within a {right_kind}. "
                "Pick contains, or swap the two inputs.")
    if predicate == "contains" and left_dim < right_dim:
        return (f"No pairs: a {left_kind} never contains a {right_kind}. "
                "Pick within, or swap the two inputs.")
    if predicate == "overlaps" and left_dim != right_dim:
        return (f"No pairs: overlaps pairs shapes of one kind, and these are {left_kind}s "
                f"and {right_kind}s. Pick intersects.")
    if predicate == "crosses" and left_dim == right_dim == 2:
        return "No pairs: two polygons never cross. Pick overlaps or intersects."
    if predicate == "crosses" and 0 in (left_dim, right_dim):
        return "No pairs: a point never crosses another shape. Pick intersects."
    if predicate == "touches" and left_dim == right_dim == 0:
        return "No pairs: points never touch. Pick intersects or nearest."
    return None
