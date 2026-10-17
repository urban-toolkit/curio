/**
 * The code a Raster Calculator node starts with: one call to Curio's raster
 * algebra in the sandbox, `curio_raster_calculate`, with its other operations
 * listed above it, statistics among them (`curio_raster_statistics`,
 * `utk_curio/sandbox/util/raster_algebra.py`). The user edits it as any
 * Python node's code. The sandbox's `test_raster_nodes.py` runs it as it is
 * written here, and with its statistics call returned in place of its own.
 */

export const RASTER_CALCULATOR_CODE = `# Raster Calculator: one operation over rasters on one grid. Connect the
# rasters to the input circles, in order, and return one of its operations.
#
# Cell by cell, as a raster:
#   "add", "subtract", "multiply" or "divide": input_0 with input_1;
#   "choose": input_1 where input_0's class is one of codes, else input_2,
#   for example curio_raster_calculate("choose", [input_0, input_1, input_2], codes=[21, 31]).
# A cell that is nodata in an input the operation reads is nodata in the result.
#
# Statistics: the mean, median, minimum, maximum and count of a
# raster's cells, nodata left out, as a table of one row.
# A condition keeps only some cells: where=lambda value: value < 1.08 tests
# the raster's own values. With a mask raster on input_1, it tests the mask's
# values instead, and mask_values=[0] keeps the cells whose mask value is 0.
#   return curio_raster_statistics(input_0, mask=input_1)
return curio_raster_calculate("subtract", [input_0, input_1])
`;
