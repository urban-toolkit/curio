"""SCOUT's Deep Umbra shadow model, as the Accumulated Shadow node runs it.

``accumulated_shadow`` (``node_outputs.py``) reads the node's height raster and
writes its shadow raster, around SCOUT's own functions (``deep_umbra.py``),
which run the package's weights.
"""

from .node_outputs import accumulated_shadow

__all__ = ["accumulated_shadow"]
