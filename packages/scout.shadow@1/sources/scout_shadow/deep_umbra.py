import onnxruntime as ort  # Curio: tensorflow; Deep Umbra runs as its exported ONNX graph
import os
import numpy as np
import pandas as pd
import cv2
from pathlib import Path
# Curio: LAMBDA and loss_object, for training, left out with TensorFlow

def rad2deg(rad):
    pi_on_180 = 0.017453292519943295
    return rad / pi_on_180

def num2deg(xtile, ytile, zoom):
    n = np.power(2, zoom)  # Curio: tf.math.pow
    lon_deg = float(xtile) / float(n) * 360.0 - 180.0
    lat_rad = np.arctan(np.sinh(np.float32(  # Curio: tf.math.atan, tf.math.sinh, in float32 as TensorFlow's
        3.14159265359 * (1.0 - 2.0 * float(ytile) / float(n)))))
    lat_deg = rad2deg(lat_rad)
    return (lat_deg, lon_deg)

def load_input(path, zoom, i, j):

    # Read and decode an image file to a uint8 tensor
    filename = '{}/{}_{}_{}.png'.format(path, zoom, i, j)  # Curio: tf.strings.format
    filename = filename.replace('\"', "")  # Curio: tf.strings.regex_replace
    input_image = cv2.imread(filename, cv2.IMREAD_UNCHANGED)  # Curio: tf.io.read_file
    input_image = input_image.reshape(256, 256, -1)[:, :, 0]  # Curio: tf.io.decode_png(input_image)[:, :, 0]

    input_image = np.reshape(input_image, (256, 256, 1))  # Curio: tf.reshape
    input_image = input_image.astype(np.float32)  # Curio: tf.cast

    return input_image

def load_input_grid(path, date, zoom, i, j):
    all_input = np.zeros((256*3, 256*3, 1), dtype=np.float32)  # Curio: tf.zeros

    for x in range(-1, 2):
        for y in range(-1, 2):
            filepath = '%s/%d_%d_%d.png' % (path, zoom, i+y, j+x)
            print(f"Loading file: {filepath}")
            if os.path.isfile(filepath):
                iinput = load_input(path, zoom, i+y, j+x)
                indices = [(xx, yy) for xx in range(256+256*x, 256+256*(x+1))
                           for yy in range(256+256*y, 256+256*(y+1))]
                indices = np.array(indices).reshape(256, 256, -1)
                all_input[indices[..., 0], indices[..., 1]] = iinput  # Curio: tf.tensor_scatter_nd_update

    (latitude, longitude) = num2deg(i, j, zoom)

    all_input = all_input[128:-128, 128:-128]
    all_lat = np.ones((512, 512), dtype=np.float32)  # Curio: tf.ones
    all_lat = float(latitude) * all_lat  # Curio: tf.math.scalar_mul
    all_lat = np.reshape(all_lat, (512, 512, 1))  # Curio: tf.reshape

    if date == 'winter':
        value = 0
    elif date == 'spring' or date == 'fall':
        value = 1
    else:
        value = 2

    all_date = np.ones((512, 512), dtype=np.float32)  # Curio: tf.ones
    all_date = float(value) * all_date  # Curio: tf.math.scalar_mul
    all_date = np.reshape(all_date, (512, 512, 1))  # Curio: tf.reshape

    return all_input, all_lat, all_date

def normalize_input(input_image, lat_image, date_image):
    input_image = (input_image / 127.5) - 1
    lat_image = ((lat_image + 90) / 90.0) - 1
    date_image = date_image - 1

    return input_image, lat_image, date_image

def predict_shadow(generator, path, date, zoom, i, j, lat=True, dat=True):
    input_height, input_lat, input_date = load_input_grid(
        path, date, zoom, i, j)
    input_height, input_lat, input_date = normalize_input(
        input_height, input_lat, input_date)

    input_height = np.array(input_height).reshape(1, 512, 512, 1)
    input_lat = np.array(input_lat).reshape(1, 512, 512, 1)
    input_date = np.array(input_date).reshape(1, 512, 512, 1)

    concat = [input_height]
    if lat:
        concat.append(input_lat)
    if dat:
        concat.append(input_date)

    prediction = generator.run(None, dict(zip(("height", "latitude", "date"), concat)))[0]  # Curio: generator(concat, training=True); the graph keeps training=True's batch norm
    prediction = prediction[:, 128:-128, 128:-128, :]  # Curio: prediction.numpy()
    prediction = prediction.reshape(256, 256)

    input_height = input_height[:, 128:-128, 128:-128, :]
    input_height = input_height.reshape(256, 256)
    input_height = (input_height+1)*127.5

    return input_height, prediction

# Curio: the training code (the losses, downsample, upsample, get_generator_arch, resblock, Self_Attention, Generator, Discriminator and DeepShadow) left out with TensorFlow: the exported ONNX graph is the restored generator

_DEEP_SHADOW = None

def get_deep_shadow(model_path):  # Curio: model_path, the exported ONNX file
    """Return a singleton DeepShadow instance, creating it on first use."""
    global _DEEP_SHADOW
    if _DEEP_SHADOW is None:
        print("[DeepShadow] Loading model...")
        _DEEP_SHADOW = ort.InferenceSession(model_path)  # Curio: the generator SCOUT builds and restores from tf_model/ckpt-44
    return _DEEP_SHADOW

def run_shadow_model(rasters_in: str,
                     season: str,
                     rasters_out: str,
                     model_path: str):  # Curio: model_path; no metrics_out, the metrics are returned

    deep_shadow = get_deep_shadow(model_path)  # Curio: model_path

    in_dir = Path(rasters_in)
    out_dir = Path(rasters_out)
    # Curio: no mkdir or emptying of out_dir here: curio_save_folder gives an empty folder
    date = season
    zoom = 16

    all_vals = []
    for png_path in sorted(in_dir.glob("*.png")):
        stem = png_path.stem  # "16813_24353"
        try:
            zoom_from_name, I_str, J_str = stem.split("_")
            zoom = int(zoom_from_name)
            I = int(I_str)
            J = int(J_str)
        except ValueError:
            continue

        print(f"[Predicting] I={I}, J={J}")

        input_height, prediction = predict_shadow(
            deep_shadow,  # Curio: deep_shadow.generator
            str(in_dir),     # the dir path where rasters live
            date,
            zoom,
            I,
            J,
            lat=True,
            dat=True
        )

        # Extract [0, :, :, 0]
        arr = prediction

        # Normalize if needed (OpenCV requires 0–255 uint8)
        arr_min, arr_max = float(arr.min()), float(arr.max())
        if arr_max > arr_min:
            arr_norm = (arr - (-1.0)) / (1.0 - (-1.0))
        else:
            arr_norm = np.zeros_like(arr)

        # if winter: 360, if spring: 540, if summer: 720
        factor = 360 if season == 'winter' else 540 if season == 'spring' else 720
        vals = arr_norm[input_height == 0] * factor  # 1D view into arr_norm
        all_vals.append(vals.ravel())

        gray_u8 = (arr_norm * 255).astype("uint8")
        out_path = str(out_dir / f"{stem}.png")
        cv2.imwrite(out_path, gray_u8)
        print(f"Saved (grayscale): {out_path}")

    # Curio: no metric_path = f"{metrics_out}.csv"; the metrics are returned

    if all_vals:
        all_vals = np.concatenate(all_vals)
        mean_val = np.mean(all_vals)
        median_val = np.median(all_vals)
        max_val = np.max(all_vals)
        min_val = np.min(all_vals)
        stddev_val = np.std(all_vals)

        df = pd.DataFrame([{
            'Mean Acc shadow': mean_val,
            'Median Acc shadow': median_val,
            # 'max': max_val,
            # 'min': min_val,
            # 'stddev': stddev_val
        }])

        return df  # Curio: df.to_csv(metric_path, index=False) and print(f"Saved metrics to: {metric_path}")
