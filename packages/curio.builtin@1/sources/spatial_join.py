"""The Spatial Join node's join: the rows of two layers paired where their shapes meet.

The Spatial Join node of ``curio.builtin@1`` calls :func:`spatial_join` with
its two circles, input_0 as ``left`` and input_1 as ``right``, and its two
widgets, Operation and Output. ``sjoin`` of geopandas finds the pairs for
every operation but nearest, which is ``sjoin_nearest``.
"""

from collections import Counter

__all__ = ["spatial_join"]

#: The operations: how the shape of a row of ``left`` must meet one of ``right``.
OPERATIONS = ("intersects", "within", "contains", "touches", "overlaps", "crosses", "nearest")
#: What the join gives: one row per pair, or the rows of ``right`` with a count.
OUTPUTS = ("pairs", "counts")

#: What a clashing column of ``right`` is renamed with, so no column of ``left`` is overwritten.
RIGHT_SUFFIX = "_right"
#: The column the counts output gives each row of ``right``.
COUNT_COLUMN = "point_count"
#: The column nearest adds: the distance between the pair, in meters.
DISTANCE_COLUMN = "distance"

#: A layer with no coordinate system is read as longitude and latitude, as GeoJSON is.
_GEOGRAPHIC = "EPSG:4326"
_KINDS = {0: "point", 1: "line", 2: "polygon"}


def spatial_join(left, right, operation="intersects", output="pairs"):
    """Pair each row of ``left`` with the rows of ``right`` whose shapes meet
    by ``operation``: intersects, within, contains, touches, overlaps, crosses
    or nearest.

    With ``output="pairs"`` it gives one row per pair: the row and geometry of
    ``left``, with the columns of ``right`` added (``<column>_right`` when
    ``left`` has a column of that name), and for nearest the ``distance``
    between the two in meters, measured in the UTM zone of ``left``. With
    ``output="counts"`` it gives the rows of ``right``, each with
    ``point_count``, the number of rows of ``left`` it pairs with.

    ``right`` is joined in the coordinate system of ``left``. A point on a
    polygon's edge follows shapely's rule for the operation: it intersects and
    touches the polygon, and is not within it. It prints how many rows it
    paired, and when it finds no pair because the operation can never match
    these shapes, what to pick instead.
    """
    if operation not in OPERATIONS:
        raise ValueError(f"The operation must be one of {', '.join(OPERATIONS)}; got {operation!r}.")
    if output not in OUTPUTS:
        raise ValueError(f"The output must be one of {', '.join(OUTPUTS)}; got {output!r}.")
    left = _layer(left, "input_0").reset_index(drop=True)
    right = _layer(right, "input_1").reset_index(drop=True)
    left_shapes = _shapes(left)
    right_shapes = _shapes(right)
    if right_shapes.crs != left_shapes.crs:
        right_shapes = right_shapes.to_crs(left_shapes.crs)

    pairs = _pairs(left_shapes, right_shapes, operation)
    hint = None
    if not pairs and len(left) and len(right):
        hint = _never_matches_hint(operation, _dimension(left_shapes), _dimension(right_shapes))

    if output == "counts":
        counts = Counter(j for _, j, _ in pairs)
        result = right.copy()
        result[COUNT_COLUMN] = [counts.get(j, 0) for j in range(len(right))]
        print(f"{len({j for _, j, _ in pairs})} of {len(right)} input_1 rows have pairs "
              f"({len(pairs)} in all); each row carries {COUNT_COLUMN}.")
    else:
        result = _pair_rows(left, right, pairs, operation == "nearest")
        print(f"{_plural(len(pairs), 'pair')}: {len({i for i, _, _ in pairs})} of {len(left)} "
              "input_0 rows matched.")
    if hint:
        print(hint)
    return result


def _layer(value, name):
    """*value* when it is one layer, a GeoDataFrame; else a message saying what to connect."""
    import geopandas as gpd

    if isinstance(value, (list, tuple)):
        names = [layer for layer in (_layer_name(item) for item in value) if layer]
        if names:
            raise ValueError(
                f"{name} holds several layers ({', '.join(names)}): pick one with its layer chip, "
                f"such as [!! {name}:{names[0]} !!]."
            )
        raise ValueError(f"{name} holds several layers: pick one with its layer chip, [!! {name}:<table> !!].")
    if not isinstance(value, gpd.GeoDataFrame) or not isinstance(getattr(value, "geometry", None), gpd.GeoSeries):
        raise ValueError(
            f"{name} is not geodata: connect a node whose output has a geometry column "
            "(a GeoDataFrame) to its circle."
        )
    return value


def _layer_name(item):
    """The name a layer of a list carries: a frame's in its ``metadata``, a layer record's ``name``."""
    if isinstance(item, dict):
        name = item.get("name") if "geojson" in item else item.get("layerName")
    else:
        meta = getattr(item, "__dict__", {}).get("metadata")
        name = meta.get("name") if isinstance(meta, dict) else None
    return name if isinstance(name, str) and name else None


def _shapes(frame):
    """The geometries of *frame* alone, by row position, in its coordinate system or longitude and latitude."""
    import geopandas as gpd

    shapes = frame.geometry.reset_index(drop=True)
    if shapes.crs is None:
        shapes = shapes.set_crs(_GEOGRAPHIC)
    return gpd.GeoDataFrame(geometry=shapes)


def _pairs(left, right, operation):
    """``(row of left, row of right, distance)`` for every matching pair, in the order of ``left``."""
    import geopandas as gpd

    left = left[left.geometry.notna() & ~left.geometry.is_empty]
    right = right[right.geometry.notna() & ~right.geometry.is_empty]
    if left.empty or right.empty:
        return []
    if operation == "nearest":
        # In degrees the nearest polygon is the wrong one away from the
        # equator, and a distance in degrees means nothing to anyone: measure
        # in the UTM zone of left, in meters.
        metric = left.estimate_utm_crs()
        joined = gpd.sjoin_nearest(
            left.to_crs(metric), right.to_crs(metric), how="inner", distance_col=DISTANCE_COLUMN,
        )
        rows = [
            (int(i), int(j), round(float(d), 2))
            for i, j, d in zip(joined.index, joined["index_right"], joined[DISTANCE_COLUMN])
        ]
    else:
        joined = gpd.sjoin(left, right, how="inner", predicate=operation)
        rows = [(int(i), int(j), None) for i, j in zip(joined.index, joined["index_right"])]
    return sorted(rows)


def _pair_rows(left, right, pairs, with_distance):
    """One row per pair: the row and geometry of ``left``, the columns of ``right`` added."""
    import geopandas as gpd
    import pandas as pd

    geometry = left.geometry.name
    taken = set(left.columns)
    columns = [column for column in right.columns if column != right.geometry.name]
    renamed = {}
    for column in sorted(columns, key=str):
        name = column
        while name in taken:
            name = f"{name}{RIGHT_SUFFIX}"
        renamed[column] = name
        taken.add(name)
    distance_column = DISTANCE_COLUMN
    while distance_column in taken:
        distance_column = f"{distance_column}{RIGHT_SUFFIX}"

    rows = left.iloc[[i for i, _, _ in pairs]].reset_index(drop=True)
    added = right[columns].iloc[[j for _, j, _ in pairs]].reset_index(drop=True).rename(columns=renamed)
    if with_distance:
        added[distance_column] = [distance for _, _, distance in pairs]
    return gpd.GeoDataFrame(pd.concat([pd.DataFrame(rows), added], axis=1), geometry=geometry, crs=left.crs)


def _plural(count, word):
    return f"{count} {word}{'' if count == 1 else 's'}"


def _dimension(frame):
    """0, 1 or 2 when every geometry of *frame* is points, lines or polygons; else None."""
    import shapely

    geometries = frame.geometry[frame.geometry.notna() & ~frame.geometry.is_empty]
    dims = {int(d) for d in shapely.get_dimensions(geometries.to_numpy())}
    return dims.pop() if len(dims) == 1 else None


def _never_matches_hint(operation, left_dim, right_dim):
    """Why an operation found no pairs when it never can for these shapes, and what to pick."""
    if left_dim is None or right_dim is None:
        return None
    left_kind, right_kind = _KINDS[left_dim], _KINDS[right_dim]
    if operation == "within" and left_dim > right_dim:
        return (f"No pairs: a {left_kind} is never within a {right_kind}. "
                "Pick contains, or swap the two inputs.")
    if operation == "contains" and left_dim < right_dim:
        return (f"No pairs: a {left_kind} never contains a {right_kind}. "
                "Pick within, or swap the two inputs.")
    if operation == "overlaps" and left_dim != right_dim:
        return (f"No pairs: overlaps pairs shapes of one kind, and these are {left_kind}s "
                f"and {right_kind}s. Pick intersects.")
    if operation == "crosses" and left_dim == right_dim == 2:
        return "No pairs: two polygons never cross. Pick overlaps or intersects."
    if operation == "crosses" and 0 in (left_dim, right_dim):
        return "No pairs: a point never crosses another shape. Pick intersects."
    if operation == "touches" and left_dim == right_dim == 0:
        return "No pairs: points never touch. Pick intersects or nearest."
    return None
