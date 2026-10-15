"""Template slugs: a ``TEMPLATE_ID_RE``-safe template id from a human label.

Application layer of the packages package (memo dev/143, B2): cut from ``services.py``
by responsibility; every function keeps its name and body. Sibling modules are reached
module-qualified (``packages_<module>.name``) so a test that patches the owner is seen by
every caller, and import order between siblings cannot matter.
"""

from __future__ import annotations

import re


_TEMPLATE_SLUG_MAX = 48


def template_slug(label: str) -> str:
    """A ``TEMPLATE_ID_RE``-safe slug from a human label (empty when nothing
    survives normalization)."""

    slug = re.sub(r"[^a-z0-9]+", "-", (label or "").lower()).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)[:_TEMPLATE_SLUG_MAX].strip("-")
    if slug and not slug[0].isalpha():
        slug = f"n-{slug}".rstrip("-")[:_TEMPLATE_SLUG_MAX]
    return slug
