"""A count and its noun, agreeing (#508): ``1 node``, ``2 nodes``.

The backend's twin of the frontend's ``src/utils/countLabel.ts``. The plan
summaries and the Solve result card both read it, so it lives in the domain
layer, where every application module may reach it.
"""

from __future__ import annotations


def count_label(n: int, noun: str) -> str:
    """``1 node``, ``2 nodes``: a count and its noun, agreeing (#508)."""
    return f"{n} {noun}{'' if n == 1 else 's'}"
