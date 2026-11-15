"""Project gt_65 column.

Input: the census polygons, as Reproject census to EPSG:3395 returns them.
Returns their `gt_65` column alone, for a chart of the residents over 65.
"""

from weather_census import gt65_column

return gt65_column(input_0)
