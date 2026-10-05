"""Simulate Flood: SCOUT's flood projection, with and without nature-based solutions.

Input: (classes, nbs, no_nbs) from the Data Loading node: the nature-based
solution (NbS) classes and one period's flood depth with NbS and without,
three rasters of data.scout.quad-cities-flood read over one area.
Output: one raster on their grid, the projected flood depth in
metres: the depth with nature-based solutions (NbS) where a cell's class is
one of the solutions chosen, the depth without them elsewhere. NaN where the
projection gives no depth. An Autark map draws it as input_0, band band_1.
The Widgets tab chooses the solutions; none chosen is the projection without NbS.
Ported from SCOUT, https://github.com/urban-toolkit/scout.
"""
from scout_flood_simulation.node_outputs import simulate_flood

return simulate_flood(
    arg,
    nbs=[!! nbs !!],
    output_file=curio_output_file,
)
