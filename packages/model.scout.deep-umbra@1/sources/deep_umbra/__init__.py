"""SCOUT's Deep Umbra shadow model, as the Accumulated Shadow node runs it.

``accumulated_shadow`` (``node_outputs.py``) reads the node's height raster and
writes its shadow raster, around SCOUT's own functions (``deep_umbra.py``),
which run the package's weights. ``season_factor`` (``deep_umbra.py``) gives
the minutes of shadow a shadow of 1 stands for in a season.

``__all__`` names what node code imports from the package; its modules offer
nothing of their own.
"""

from .deep_umbra import season_factor
from .node_outputs import accumulated_shadow

__all__ = ["accumulated_shadow", "season_factor"]
