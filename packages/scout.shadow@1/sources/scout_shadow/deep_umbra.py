"""SCOUT's Deep Umbra shadow model, ported from SCOUT
(https://github.com/urban-toolkit/scout),
``backend/compute/accumulated_shadow_simulation/scripts/deep_umbra.py``.

Deep Umbra is a generator network that SCOUT restores with TensorFlow from its
``tf_model/ckpt-44`` checkpoint. Curio runs the same generator as an ONNX file,
the Data Catalog dataset ``data.scout.deep-umbra@1`` that
``scripts/scout/export_deep_umbra.py`` exported, through onnxruntime. So every
function here takes the onnxruntime session where SCOUT's took the generator.

Every function keeps SCOUT's name and arithmetic. The changes:

- TensorFlow's tile reads and tensor writes are numpy and Pillow. The latitude
  is computed in float32, as SCOUT's TensorFlow operations compute it, so the
  three inputs are SCOUT's to the bit.
- ``predict_shadow`` runs the session on one tile at a time. The generator
  normalizes each layer by the statistics of the tile it is given, as SCOUT's
  ``training=True`` call does, so tiles cannot share a batch.
- ``run_shadow_model`` takes the session, and writes its tiles with Pillow
  instead of ``cv2.imwrite``: the same 8-bit gray pixels. Its per-tile work is
  ``predict_tiles`` and ``shadow_tile``, which the node also uses.
- SCOUT's training code (losses, the discriminator, the checkpoint restore),
  its print lines and its unused imports are left out.
"""

import os
from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image

#: The ONNX model's inputs, in SCOUT's order, and its output; each is
#: (1, 512, 512, 1) float32.
INPUTS = ("height", "latitude", "date")
OUTPUT = "shadow"


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


def load_input(path, zoom, i, j):
    """Tile (i, j)'s 8-bit heights, the PNG's first channel, as float32 (256, 256, 1)."""
    with Image.open(os.path.join(path, "%d_%d_%d.png" % (zoom, i, j))) as image:
        if image.mode == "P":
            image = image.convert("RGB")
        pixels = np.asarray(image)
    if pixels.ndim == 3:
        pixels = pixels[:, :, 0]
    return pixels.reshape(256, 256, 1).astype(np.float32)


def load_input_grid(path, date, zoom, i, j):
    """The generator's three inputs for tile (i, j), each (512, 512, 1).

    The tile and its eight neighbours fill a 768 by 768 grid (a neighbour with
    no file is ground), cut to its middle 512 by 512; the latitude of the
    tile's north-west corner and the season's number fill the other two.
    """
    all_input = np.zeros((256 * 3, 256 * 3, 1), dtype=np.float32)
    for x in range(-1, 2):
        for y in range(-1, 2):
            filepath = "%s/%d_%d_%d.png" % (path, zoom, i + y, j + x)
            if os.path.isfile(filepath):
                all_input[256 + 256 * x:256 + 256 * (x + 1), 256 + 256 * y:256 + 256 * (y + 1)] = load_input(
                    path, zoom, i + y, j + x
                )

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


def predict_shadow(generator, path, date, zoom, i, j):
    """Deep Umbra on tile (i, j): ``(input_height, prediction)``, each 256 by
    256: the tile's heights as gray levels, and the generator's output, from
    -1 (no shadow) to 1, for the middle of its 512 by 512 window."""
    input_height, input_lat, input_date = load_input_grid(path, date, zoom, i, j)
    input_height, input_lat, input_date = normalize_input(input_height, input_lat, input_date)

    input_height = input_height.reshape(1, 512, 512, 1)
    input_lat = input_lat.reshape(1, 512, 512, 1)
    input_date = input_date.reshape(1, 512, 512, 1)

    prediction = generator.run([OUTPUT], dict(zip(INPUTS, (input_height, input_lat, input_date))))[0]
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


def shadow_tile(prediction, input_height, season):
    """``run_shadow_model``'s work on one tile: ``(arr_norm, vals, gray_u8)``.

    *arr_norm* is the prediction from 0 to 1, *vals* the accumulated shadow in
    minutes on the tile's ground (its pixels with no building), and *gray_u8*
    the 8-bit tile SCOUT writes.
    """
    arr = prediction

    arr_min, arr_max = float(arr.min()), float(arr.max())
    if arr_max > arr_min:
        arr_norm = (arr - (-1.0)) / (1.0 - (-1.0))
    else:
        arr_norm = np.zeros_like(arr)

    factor = season_factor(season)
    vals = arr_norm[input_height == 0] * factor

    gray_u8 = (arr_norm * 255).astype("uint8")
    return arr_norm, vals.ravel(), gray_u8


def predict_tiles(rasters_in, season, generator):
    """Each tile ``run_shadow_model`` predicts, in its order:
    ``(stem, zoom, I, J, arr_norm, vals, gray_u8)``."""
    in_dir = Path(rasters_in)
    for png_path in sorted(in_dir.glob("*.png")):
        stem = png_path.stem  # "16_16813_24353"
        try:
            zoom_from_name, I_str, J_str = stem.split("_")
            zoom = int(zoom_from_name)
            I = int(I_str)
            J = int(J_str)
        except ValueError:
            continue

        input_height, prediction = predict_shadow(generator, str(in_dir), season, zoom, I, J)
        arr_norm, vals, gray_u8 = shadow_tile(prediction, input_height, season)
        yield stem, zoom, I, J, arr_norm, vals, gray_u8


def run_shadow_model(rasters_in: str, season: str, rasters_out: str, metrics_out: str, generator):
    """SCOUT's accumulated shadow: one 8-bit tile per height tile in
    *rasters_in*, written to *rasters_out*, and the mean and median shadow in
    minutes over every tile's ground, written to ``<metrics_out>.csv``.
    *generator* is the onnxruntime session of ``data.scout.deep-umbra``."""
    out_dir = Path(rasters_out)
    out_dir.mkdir(parents=True, exist_ok=True)

    if out_dir.exists():
        for file in out_dir.iterdir():
            file.unlink()

    all_vals = []
    for stem, _zoom, _I, _J, _arr_norm, vals, gray_u8 in predict_tiles(rasters_in, season, generator):
        all_vals.append(vals)
        Image.fromarray(gray_u8).save(str(out_dir / f"{stem}.png"))

    metric_path = f"{metrics_out}.csv"

    if all_vals:
        all_vals = np.concatenate(all_vals)
        mean_val = np.mean(all_vals)
        median_val = np.median(all_vals)

        if os.path.dirname(metric_path):
            os.makedirs(os.path.dirname(metric_path), exist_ok=True)

        df = pd.DataFrame([{
            'Mean Acc shadow': mean_val,
            'Median Acc shadow': median_val,
        }])

        df.to_csv(metric_path, index=False)
