## Functions node code calls

Curio gives a node's code these functions, which it calls by name, with no import. Each is listed by its call, then the engines whose code has it (`python` or `javascript`, as a node's template names its engine), what it does, and each of its arguments.

An argument that names an item of a catalog says which: a Data Catalog dataset or collection, a Model Catalog model, or a Node code key saved in API Settings. The item must be one the account that runs the node has, and the code writes it as a string in the call, such as `curio_load_data("<id>")`, since Curio reads it from the code before the node runs.

### curio_load_data(dataset_id, bounds=None, part=None)

Engines: python.

Reads a dataset the way its format is read: a CSV file as a DataFrame, a GeoJSON file or a shapefile as a GeoDataFrame, a Parquet file as a GeoDataFrame when it has geometry and a DataFrame otherwise, a JSON file as its document, a GeoTIFF as an open rasterio dataset, a NetCDF file as an xarray Dataset, an ONNX file as an onnxruntime session, a collection as its index, and the result of a node that returned several values as the tuple, list or dict it returned.

- `dataset_id` (a Data Catalog dataset): the dataset's id.
- `bounds`: `(west, south, east, north)` in a GeoTIFF's CRS: only the cells whose centres lie inside are read, at the raster's own cell size.
- `part`: the file name or label of one file of a dataset of several files, read as the dataset holds it; `bounds` then reads a window of it when it is a GeoTIFF.

### curio_data_path(dataset_id)

Engines: python.

Gives the path of a dataset's file, for code that reads the file its own way, such as `pd.read_csv(curio_data_path("<id>"), sep=";")`.

- `dataset_id` (a Data Catalog dataset): the dataset's id.

### curio_load_collection(dataset_id)

Engines: python.

Reads a collection's index, one row per file: where this node can open the file (`path`), the ids that name it (`dataset_id` and `file_id`), the links a Simple View shows (`thumbnail`, and `image_url` or `audio_url`), and what was read from the file.

- `dataset_id` (a Data Catalog collection): the collection's id.

### curio_derived_file(dataset_id, file_id, t_ms, ext=None, *, kind="video", tag=None)

Engines: python.

Gives where to write a file derived from one file of a collection, such as a video's frame, a recording's clip or a photo's overlay, as its row: its `file_id`, its `path`, whose folder exists, its `thumbnail`, and its `image_url`, or `audio_url` for a clip.

- `dataset_id`: the collection's id, as a row of `curio_load_collection` holds it.
- `file_id`: the file's id, as that row holds it.
- `t_ms`: the time in the file the derived file is taken at, in milliseconds; 0 for a photo.
- `ext`: the derived file's extension; when it is None, `jpg` for a frame, `wav` for a clip and `png` for an overlay.
- `kind`: what the derived file is: `"video"` for a frame, `"audio"` for a clip, `"image"` for an overlay.
- `tag`: 1 to 32 lowercase letters and digits that tell two derived files of one file and time apart, such as the model that drew an overlay.

### curio_output_file(name)

Engines: python.

Gives the path to write a file the node returns, such as a raster or a mosaic's VRT; a function that writes such files takes it whole, as `raster_calculate(..., output_file=curio_output_file)` does.

- `name`: one plain file name, such as `mosaic.vrt`.

### curio_load_model(model_id)

Engines: python.

Loads a Model Catalog model: `curio_segment` runs a segmentation model, and `model.run({input name: array})` runs an ONNX model's graph and returns its outputs in order.

- `model_id` (a Model Catalog model): the model's id.

### curio_segment(images, model, classes=None, *, overlays=True)

Engines: python.

Labels the pixels of each image with a segmentation model and returns the images' rows with the results as their first columns: `dominant_class`, `dominant_pct`, a `<class>_pct` per class, `overlay_url` and `segment_error`.

- `images`: rows with a `path`, as `curio_load_collection` gives them.
- `model`: a model `curio_load_model` loaded.
- `classes`: the classes to report; every class the model labels when it is None.
- `overlays`: whether to write each image's overlay, linked in `overlay_url`.

### curio_secret(name)

Engines: python.

Gives the value of a key saved for node code, which never appears in the code, the saved dataflow or the run's log: `api_key = curio_secret("<name>")`.

- `name` (a Node code key): the key's name.

### curio_edit_features(value, edits, key=None, layer=None, keys=None, new_layers=None, crs=None, by_input=False)

Engines: python.

Hands on its input with edits applied to the features of its layers: a Map Edits node's code is one such call, which the node writes from its edits.

- `value`: the input: an Autark node's layers, a table, or several tables.
- `edits`: the edits, in the order they were made, each a dict with an `op`, the features it applies to and, for an op that writes, a `column` and a `value`.
- `key`: the column whose values identify a feature, such as `osm_id` or `building_id`.
- `layer`: the layer an edit that names none applies to.
- `keys`: for each layer whose features another column identifies, that column, by the layer's name.
- `new_layers`: the layers the node makes, each with a `name`, a `geometry` and its `properties`.
- `crs`: the CRS the map drew the layers in, which a geometry drawn on it is in.
- `by_input`: whether `value` is the node's inputs, one per circle, rather than one input.

### curio_layer(value, layer, slot=0)

Engines: python, javascript.

Gives one layer of an input by its name, as a layer chip does: a GeoDataFrame in python and a GeoJSON FeatureCollection in javascript; an input that is one frame with no layer name is that layer.

- `value`: the input, such as `input_0`.
- `layer`: the layer's name, as the Autark node that hands it on names its table, such as `table_osm_roads`.
- `slot`: the input's circle, which the error names when the input has no such layer.
