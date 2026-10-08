"""Local Relief: how many metres each cell stands above the cells around it.

Input: a raster of building heights in metres, one band (a Mosaic Tiles
node's, or any GeoTIFF a node hands on).
Output: a raster on the same grid, band_1 the cell's height minus the mean
height of the 5 by 5 cells around it. An Autark map draws it.
The model is the Model Catalog's Local Relief, model.example.local-relief.
"""
from local_relief.run import local_relief

model = curio_load_model("model.example.local-relief")
return local_relief(input_0, model, output_file=curio_output_file)
