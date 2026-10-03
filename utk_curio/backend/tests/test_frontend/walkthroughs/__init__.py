"""Scripted user journeys through Curio, each consumed twice.

A walkthrough is one short scripted path through the app that ends on a state
worth pinning: a chart that renders, a drawer that opens, a graph you can pan.

``test_walkthrough_videos.py`` runs them with :class:`tour.Tour` narrating and a
recorder attached, producing one screencast each.
``test_walkthrough_baselines.py`` runs the SAME functions silently and diffs a
committed screenshot at the point each one holds.

Keeping one definition is the point: a journey that drifts from the behaviour it
documents would otherwise keep recording a green video while the baseline it was
written beside quietly stopped testing anything.

Narration goes through ``ctx.say`` / ``ctx.click`` rather than the raw locator so
the caption, cursor and spotlight stay in step with the browser during a
recording -- and vanish entirely during a baseline capture, where an overlay
would poison every pixel.

Walkthroughs added to close a bug carry its number in ``refs``; that is metadata
for the report, not identity. The slug names the behaviour, so a journey outlives
the ticket that prompted it.
"""

# The package holds one module per surface, plus ``framework`` (Narrator, Ctx,
# Walkthrough and the ``@walkthrough`` registry) and ``steps`` (the steps the
# scenes share). Each name other files import is imported here from the module
# that defines it, so ``from .walkthroughs import X`` keeps working. Patch a name
# in the module that looks it up when the code runs, not here.
from .framework import (  # noqa: F401
    SilentNarrator,
    Ctx,
    FULL_PAGE_DIFF_FLOOR,
    Walkthrough,
    WALKTHROUGHS,
)
from .steps import load_example_spec  # noqa: F401

# Importing a scene module registers its scenes in WALKTHROUGHS, in the order the
# module defines them. So the order of these imports is the order of the
# registry, and of the test ids and CI parts built from it.
from . import (  # noqa: F401
    provenance,
    agent_catalog,
    cross_catalog,
    account_examples,
    robustness,
    layout,
    visual_claims,
    dataflow_identity,
    catalog_chrome,
    column_filter,
    agent_chat,
    simple_view,
)

from .provenance import PROVENANCE_EXAMPLE  # noqa: F401
from .cross_catalog import TOAST_REGION  # noqa: F401
