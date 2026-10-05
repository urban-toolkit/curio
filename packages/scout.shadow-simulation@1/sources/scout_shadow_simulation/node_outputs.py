"""The Simulate Shadows node's three outputs, made from Deep Umbra's answer
for each of Rasterize Buildings' tiles. Curio's own code, beside the port of
SCOUT's ``deep_umbra.py``.

- **mosaic**: the shadow of every tile side by side, on the grid of
  Rasterize Buildings' mosaic (EPSG:3395), one float32 band of the minutes
  of the day each cell is in shadow, for an Autark map: a tile's gray level
  times the day's minutes over 255, so in SCOUT's steps (2.8 minutes in
  summer). A cell of a tile with no building near it is 0.
- **tiles**: one row per tile, ``zoom``, ``x``, ``y`` and ``png``, the 8-bit
  gray PNG (base64) SCOUT writes for it, where 255 is shadow all day, and
  ``mean_shadow_min``, the mean over its ground (the pixels with no
  building).

Deep Umbra answers for every pixel of a tile, those under a building too,
where it gives next to nothing. SCOUT's PNG rounds most of those to 0 and
its metrics read the ground alone; here a building's pixels are 0 in the PNG
and the mosaic, so a map shows the shadow on the ground and nothing on the
buildings that cast it. The metrics are SCOUT's, on the ground, unrounded.
- **summary**: one row, SCOUT's metrics: ``Mean Acc shadow`` and
  ``Median Acc shadow`` over the ground of every tile, in minutes, and the
  season.
"""

import base64
import hashlib
import io

import numpy as np
import pandas as pd
import rasterio
from PIL import Image
from rasterio.windows import Window

from .deep_umbra import TILE, predict_shadow, season_minutes, shadow_tile

SEASONS = ("spring", "summer", "winter")
#: What Deep Umbra was trained on: zoom-16 tiles where gray 255 is 550 m.
MODEL_ZOOM = 16
MODEL_MAX_HEIGHT = 550.0


def rasterized(arg):
    """Rasterize Buildings' ``(mosaic, tiles)`` from *arg*, checked."""
    if not isinstance(arg, (tuple, list)) or len(arg) != 2:
        raise ValueError(
            "Simulate Shadows reads Rasterize Buildings' output, (mosaic, tiles): "
            "connect a Rasterize Buildings node to it."
        )
    mosaic, tiles = arg
    if not hasattr(mosaic, "tags") or not isinstance(tiles, pd.DataFrame):
        raise ValueError("Simulate Shadows reads (mosaic, tiles): a raster and a table of tiles, in that order.")
    missing = [c for c in ("zoom", "x", "y", "png") if c not in tiles.columns]
    if missing:
        raise ValueError(f"The tiles table has no column {', '.join(missing)}; it comes from Rasterize Buildings.")
    if tiles.empty:
        raise ValueError("Rasterize Buildings made no tiles, so there is nothing to shade.")
    tags = mosaic.tags()
    zoom, max_height = int(tags.get("zoom", -1)), float(tags.get("max_height", -1))
    if zoom != MODEL_ZOOM or max_height != MODEL_MAX_HEIGHT:
        raise ValueError(
            f"Deep Umbra reads zoom-{MODEL_ZOOM} tiles where 255 is {MODEL_MAX_HEIGHT:g} m; these are "
            f"zoom {zoom} with 255 at {max_height:g} m. Set Rasterize Buildings' zoom level to "
            f"{MODEL_ZOOM} and its maximum height to {MODEL_MAX_HEIGHT:g}."
        )
    return mosaic, tiles


def gray_levels(png):
    """A tile's 256 by 256 gray levels from its base64 PNG; the first
    channel of a colour one, as SCOUT reads it."""
    with Image.open(io.BytesIO(base64.b64decode(png))) as image:
        pixels = np.asarray(image)
    return pixels[:, :, 0] if pixels.ndim == 3 else pixels


def png_base64(gray):
    buffer = io.BytesIO()
    Image.fromarray(gray, mode="L").save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def mosaic_name(tiles, season, model_id):
    """A file name that follows the tiles, the season and the model."""
    digest = hashlib.sha1(f"{season}:{model_id}".encode("ascii"))
    for row in tiles.itertuples(index=False):
        digest.update(f"{row.zoom}_{row.x}_{row.y}:{row.png}\n".encode("ascii"))
    return f"shadows-{digest.hexdigest()[:16]}.tif"


def simulate_shadows(arg, model, season, output_file):
    """``(mosaic, tiles, summary)``: Deep Umbra (*model*, from
    ``curio_load_model``) on every tile of Rasterize Buildings' output *arg*,
    for *season*. *output_file(name)* names where the mosaic is written."""
    if season not in SEASONS:
        raise ValueError(f"The season is one of {', '.join(SEASONS)}, not {season!r}.")
    heights, tiles = rasterized(arg)
    zoom = int(tiles["zoom"].iloc[0])
    grid = {(int(row.x), int(row.y)): gray_levels(row.png) for row in tiles.itertuples(index=False)}

    rows, minutes_by_tile, ground_minutes = [], {}, []
    for (x, y) in sorted(grid):
        input_height, prediction = predict_shadow(model, grid, season, zoom, x, y)
        gray, minutes, ground = shadow_tile(input_height, prediction, season)
        gray = np.where(ground, gray, 0).astype("uint8")
        minutes_by_tile[(x, y)] = gray.astype("float32") * np.float32(season_minutes(season) / 255.0)
        ground_minutes.append(minutes[ground].ravel())
        rows.append({
            "zoom": zoom, "x": x, "y": y, "png": png_base64(gray),
            "mean_shadow_min": round(float(minutes[ground].mean()), 1) if ground.any() else None,
        })
    shadows = pd.DataFrame(rows, columns=["zoom", "x", "y", "png", "mean_shadow_min"])

    everything = np.concatenate(ground_minutes)
    summary = pd.DataFrame([{
        "season": season,
        "Mean Acc shadow": round(float(everything.mean()), 1) if everything.size else None,
        "Median Acc shadow": round(float(np.median(everything)), 1) if everything.size else None,
    }])

    tags = heights.tags()
    first_x, first_y = int(tags["tile_x"]), int(tags["tile_y"])
    profile = dict(heights.profile)
    profile.update(dtype="float32", count=1, nodata=None)
    path = output_file(mosaic_name(shadows, season, model.id))
    with rasterio.open(path, "w", **profile) as mosaic:
        mosaic.write(np.zeros((profile["height"], profile["width"]), dtype="float32"), 1)
        for (x, y), minutes in minutes_by_tile.items():
            window = Window((x - first_x) * TILE, (y - first_y) * TILE, TILE, TILE)
            mosaic.write(minutes, 1, window=window)
        mosaic.set_band_description(1, "shadow (minutes)")
        mosaic.update_tags(
            zoom=zoom, tile_x=first_x, tile_y=first_y, tile_size=TILE, season=season,
            day_minutes=season_minutes(season), model=model.id,
        )
    return rasterio.open(path), shadows, summary
