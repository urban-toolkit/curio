"""The names a node run gives its outputs."""

from __future__ import annotations

import re

#: A node's output is named by the store's artifact id (``<ms>_<8 hex>``,
#: ``sandbox/util/parsers._make_id``). A table saved with Save on is that
#: artifact's own file, which the Data Catalog links: a run writes no other.
_OUTPUT_NAME = re.compile(r"\d{13}_[0-9a-f]{8}")


def is_output_name(name: object) -> bool:
    """Whether *name* is a name a node run gives an output, whole: never a
    path, and never another file of the shared data directory."""
    return isinstance(name, str) and _OUTPUT_NAME.fullmatch(name) is not None
