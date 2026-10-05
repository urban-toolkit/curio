"""How SCOUT feeds Deep Umbra a tile and reads its answer.

Ported from SCOUT (https://github.com/urban-toolkit/scout), file
backend/models/shadow/scripts/deep_umbra.py: ``num2deg``,
``load_input_grid``, ``normalize_input`` and ``predict_shadow``, and the
per-tile arithmetic of ``run_shadow_model``. The functions keep SCOUT's
names and arithmetic. Changes from SCOUT's file:

- numpy instead of TensorFlow: the generator is the Model Catalog's
  ``model.scout.deep-umbra``, an ONNX export of SCOUT's checkpoint that
  keeps SCOUT's ``training=True`` call (each tile's BatchNorm uses the tile's
  own statistics), run through ``CurioModel.run``.
- Tiles are read from a ``{(x, y): gray levels}`` dict, Rasterize Buildings'
  tiles table, instead of ``<zoom>_<x>_<y>.png`` files in a folder.
- ``num2deg`` computes the latitude in float64; SCOUT's ``tf.math`` calls
  compute it in float32, a difference of about a millionth of a degree.
- The training code (losses, discriminator, optimizers) is left out: Curio
  only runs the trained generator.
"""

import math

import numpy as np

TILE = 256
WINDOW = 512

#: The season planes Deep Umbra was trained with.
SEASON_VALUE = {"winter": 0, "spring": 1, "fall": 1, "summer": 2}


def num2deg(xtile, ytile, zoom):
    n = 2 ** zoom
    lon_deg = float(xtile) / float(n) * 360.0 - 180.0
    lat_rad = math.atan(math.sinh(3.14159265359 * (1.0 - 2.0 * float(ytile) / float(n))))
    lat_deg = lat_rad / 0.017453292519943295
    return (lat_deg, lon_deg)


def load_input_grid(tiles, date, zoom, i, j):
    """The 512 by 512 window around tile (*i*, *j*): the tile and half of
    each neighbour (a missing one is ground), with its latitude and season
    planes. *tiles* maps ``(x, y)`` to a tile's 256 by 256 gray levels."""
    all_input = np.zeros((TILE * 3, TILE * 3), dtype=np.float32)
    for x in range(-1, 2):
        for y in range(-1, 2):
            tile = tiles.get((i + y, j + x))
            if tile is not None:
                all_input[TILE + TILE * x:TILE * 2 + TILE * x, TILE + TILE * y:TILE * 2 + TILE * y] = tile

    (latitude, longitude) = num2deg(i, j, zoom)

    all_input = all_input[128:-128, 128:-128].reshape(WINDOW, WINDOW, 1)
    all_lat = np.full((WINDOW, WINDOW, 1), float(latitude), dtype=np.float32)
    all_date = np.full((WINDOW, WINDOW, 1), float(SEASON_VALUE.get(date, 2)), dtype=np.float32)
    return all_input, all_lat, all_date


def normalize_input(input_image, lat_image, date_image):
    input_image = (input_image / 127.5) - 1
    lat_image = ((lat_image + 90) / 90.0) - 1
    date_image = date_image - 1
    return input_image, lat_image, date_image


def predict_shadow(model, tiles, date, zoom, i, j):
    """``(input_height, prediction)`` for tile (*i*, *j*): its gray levels,
    and Deep Umbra's 256 by 256 answer in -1..1."""
    input_height, input_lat, input_date = load_input_grid(tiles, date, zoom, i, j)
    input_height, input_lat, input_date = normalize_input(input_height, input_lat, input_date)

    feeds = {
        "height": input_height.reshape(1, WINDOW, WINDOW, 1).astype(np.float32),
        "latitude": input_lat.reshape(1, WINDOW, WINDOW, 1).astype(np.float32),
        "season": input_date.reshape(1, WINDOW, WINDOW, 1).astype(np.float32),
    }
    prediction = model.run(feeds)[0]
    prediction = prediction[:, 128:-128, 128:-128, :].reshape(TILE, TILE)

    input_height = feeds["height"][:, 128:-128, 128:-128, :].reshape(TILE, TILE)
    input_height = (input_height + 1) * 127.5
    return input_height, prediction


def season_minutes(season):
    """The minutes of a day the shadow accumulates over, as SCOUT counts
    them: 360 in winter, 540 in spring, 720 otherwise."""
    return 360 if season == "winter" else 540 if season == "spring" else 720


def shadow_tile(input_height, prediction, season):
    """SCOUT's ``run_shadow_model`` for one tile: ``(gray, minutes,
    ground)``, the 8-bit PNG it writes, the shadow in minutes, and the
    pixels with no building, which its metrics read."""
    arr = prediction
    if float(arr.max()) > float(arr.min()):
        arr_norm = (arr - (-1.0)) / (1.0 - (-1.0))
    else:
        arr_norm = np.zeros_like(arr)
    minutes = (arr_norm * season_minutes(season)).astype(np.float32)
    gray = (arr_norm * 255).astype("uint8")
    return gray, minutes, input_height == 0
