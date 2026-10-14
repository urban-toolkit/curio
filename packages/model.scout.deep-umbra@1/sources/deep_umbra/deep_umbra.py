"""SCOUT's Deep Umbra shadow model, ported from SCOUT
(https://github.com/urban-toolkit/scout),
``backend/compute/accumulated_shadow_simulation/scripts/deep_umbra.py``.

Only the model: what SCOUT feeds its generator, the generator, and what SCOUT
makes of its output. Deep Umbra is a generator network that SCOUT restores with
TensorFlow from its ``tf_model/ckpt-44`` checkpoint. Curio runs the same
generator as an ONNX file, the Model Catalog model ``model.scout.deep-umbra@1``
that ``scripts/scout/export_deep_umbra.py`` exported, through onnxruntime. So
every function here takes the loaded model (``curio_load_model``, whose
``run`` feeds the graph by input name) where SCOUT's took the generator.

Every function keeps SCOUT's name and arithmetic. The changes:

- SCOUT reads each zoom-16 height tile and its eight neighbours from PNG files.
  Here ``load_input_grid`` is given that 768 by 768 neighbourhood, cut from one
  height raster on the same tile grid (``node_outputs.py``), and does the rest
  as SCOUT does. The latitude is computed in float32, as SCOUT's TensorFlow
  operations compute it, so the three inputs are SCOUT's to the bit.
- ``predict_shadow`` runs the model on one tile at a time. The generator
  normalizes each layer by the statistics of the tile it is given, as SCOUT's
  ``training=True`` call does, so tiles cannot share a batch.
- ``shadow_fraction`` and ``season_factor`` are ``run_shadow_model``'s scaling
  of the output: from 0 to 1, and the minutes of shadow 1 stands for.
- SCOUT's file reading and writing (``load_input``, and ``run_shadow_model``'s
  tile PNGs and metrics CSV), its training code (losses, the discriminator, the
  checkpoint restore), its print lines and its unused imports are left out.
"""

import numpy as np

#: The ONNX model's inputs, in SCOUT's order, and its output; each is
#: (1, 512, 512, 1) float32.
INPUTS = ("height", "latitude", "date")
OUTPUT = "shadow"

#: A tile's side, in pixels.
TILE = 256


def rad2deg(rad):
    pi_on_180 = 0.017453292519943295
    return rad / np.float32(pi_on_180)


def num2deg(xtile, ytile, zoom):
    """The north-west corner of tile (xtile, ytile): ``(latitude, longitude)``.
    The latitude is float32, as SCOUT's TensorFlow operations compute it."""
    n = float(2 ** zoom)
    lon_deg = float(xtile) / n * 360.0 - 180.0
    lat_rad = np.arctan(np.sinh(np.float32(3.14159265359 * (1.0 - 2.0 * float(ytile) / n))))
    lat_deg = rad2deg(lat_rad)
    return (lat_deg, lon_deg)


def load_input_grid(neighbourhood, date, zoom, i, j):
    """The generator's three inputs for tile (i, j), each (512, 512, 1).

    *neighbourhood* is the 8-bit heights (255 is 550 m) of the tile and its
    eight neighbours, 768 by 768 with tile (i, j) in the middle and ground
    where there is no tile, as SCOUT's loop over the neighbours' files fills
    it. It is cut to its middle 512 by 512; the latitude of the tile's
    north-west corner and the season's number fill the other two.
    """
    all_input = np.asarray(neighbourhood, dtype=np.float32).reshape(TILE * 3, TILE * 3, 1)

    (latitude, longitude) = num2deg(i, j, zoom)

    all_input = all_input[128:-128, 128:-128]
    all_lat = np.full((512, 512, 1), latitude, dtype=np.float32)

    if date == "winter":
        value = 0
    elif date == "spring" or date == "fall":
        value = 1
    else:
        value = 2

    all_date = np.full((512, 512, 1), value, dtype=np.float32)

    return all_input, all_lat, all_date


def normalize_input(input_image, lat_image, date_image):
    input_image = (input_image / 127.5) - 1
    lat_image = ((lat_image + 90) / 90.0) - 1
    date_image = date_image - 1

    return input_image, lat_image, date_image


def predict_shadow(generator, neighbourhood, date, zoom, i, j):
    """Deep Umbra on tile (i, j): ``(input_height, prediction)``, each 256 by
    256: the tile's heights as gray levels, and the generator's output, from
    -1 (no shadow) to 1, for the middle of its 512 by 512 window."""
    input_height, input_lat, input_date = load_input_grid(neighbourhood, date, zoom, i, j)
    input_height, input_lat, input_date = normalize_input(input_height, input_lat, input_date)

    input_height = input_height.reshape(1, 512, 512, 1)
    input_lat = input_lat.reshape(1, 512, 512, 1)
    input_date = input_date.reshape(1, 512, 512, 1)

    (prediction,) = generator.run(dict(zip(INPUTS, (input_height, input_lat, input_date))))
    prediction = prediction[:, 128:-128, 128:-128, :]
    prediction = prediction.reshape(256, 256)

    input_height = input_height[:, 128:-128, 128:-128, :]
    input_height = input_height.reshape(256, 256)
    input_height = (input_height + 1) * 127.5

    return input_height, prediction


def season_factor(season):
    """Minutes of shadow a pixel at 1 stands for, in *season* (SCOUT's
    ``run_shadow_model``). SCOUT gives fall 720, though its date input reads
    fall as it reads spring."""
    return 360 if season == "winter" else 540 if season == "spring" else 720


def shadow_fraction(prediction):
    """``run_shadow_model``'s scaling of one tile's prediction: from 0 (no
    shadow) to 1 (shadow all day), or 0 everywhere for a flat prediction."""
    arr = prediction

    arr_min, arr_max = float(arr.min()), float(arr.max())
    if arr_max > arr_min:
        arr_norm = (arr - (-1.0)) / (1.0 - (-1.0))
    else:
        arr_norm = np.zeros_like(arr)
    return arr_norm
