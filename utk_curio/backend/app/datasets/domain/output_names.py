"""The names a node run gives its outputs."""

from __future__ import annotations

import re

#: A node's output is named by the store's artifact id (``<ms>_<8 hex>``,
#: ``sandbox/util/parsers._make_id``), or, for a table saved with Save on, by
#: the dataset file written beside it (``<ms>_<8 hex>_output.parquet``).
_OUTPUT_NAME = re.compile(r"\d{13}_[0-9a-f]{8}(?:_output\.parquet)?")


def is_output_name(name: object) -> bool:
    """Whether *name* is a name a node run gives an output, whole: never a
    path, and never another file of the shared data directory."""
    return isinstance(name, str) and _OUTPUT_NAME.fullmatch(name) is not None
