import rasterio

# Curio's raster contract (see utk_curio/sandbox/util/parsers.py):
#   - the output of a raster-producing box is a `rasterio.io.DatasetReader`
#     (an OPEN dataset handle);
#   - the sandbox persists it by storing the file's path, and downstream
#     boxes hydrate it via `rasterio.open(path)`.
# Returning a dict of numpy arrays here would crash `save_to_duckdb`
# because numpy.ndarray has no save-side branch. Do not wrap this in a
# `with` block either — the file must stay open until the worker reads
# `src.name` after the box finishes.
src = rasterio.open([!! src$INPUT_TEXT$./Milan_Tmrt_2022_203_1200D.tif !!])
return src
