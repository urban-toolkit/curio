# Raster Calculator: one operation over rasters on one grid. Connect the
# rasters to the input circles, in order, and return one of its operations.
# An input may be a layer instead, which the code reads as zones or a mask,
# for example with rasterio.features.rasterize on a raster's grid.
#
# Cell by cell, as a raster:
#   "add", "subtract", "multiply" or "divide": input_0 with input_1;
#   "choose": input_1 where input_0's class is one of codes, else input_2,
#   for example raster_calculate("choose", [input_0, input_1, input_2], codes=[21, 31], output_file=curio_output_file).
# A cell that is nodata in an input the operation reads is nodata in the result.
#
# Statistics: the mean, median, minimum, maximum and count of a
# raster's cells, nodata left out, as a table of one row.
# A condition keeps only some cells: where=lambda value: value < 1.08 tests
# the raster's own values. With a mask raster on input_1, it tests the mask's
# values instead, and mask_values=[0] keeps the cells whose mask value is 0.
#   return raster_statistics(input_0, mask=input_1)
from scout_rasters.raster_algebra import raster_calculate, raster_statistics

return raster_calculate("subtract", [input_0, input_1], output_file=curio_output_file)
