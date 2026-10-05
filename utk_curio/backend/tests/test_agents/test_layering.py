"""The agents package's layering, as a test (memo dev/142, B5, re-derived on
enh/agent-catalog; the rule engine is ``tests/_support/layering.py``, shared with
the packages suite).

Two rules differ from the memo's on this branch, both recorded in the port's
commit message: ``infrastructure/`` may import ``repositories/`` (provider
configuration reads the LLM-configuration store, as the packages runtime reads
the store paths — memo dev/143 §3.2 rule 2), and the 150-line bound on
``application/`` functions is not yet met: B3, the decomposition of the Solve,
turn and plan loops, was not re-derived on this branch's rewritten loops. That
test is an expected failure until it is.

- ``infrastructure → domain ← repositories ← application ← presentation``:
  ``domain/`` imports nothing from the other layers; ``repositories/`` and
  ``infrastructure/`` import only ``domain`` (and each other's own layer);
  ``application/`` may import every layer beneath it; ``routes/`` (with
  ``evaluation/`` as an application-level consumer) may import anything but is
  imported by nothing.
- No module under ``agents/`` imports the facade or an ``application`` module
  inside a function — the cycle-hiding pattern the monolith lived on. Outside
  the package, the three cross-feature boundaries (the app factory registering
  the blueprint, ``projects/services.py`` seeding a project, the monitor's LLM
  check) keep their lazy imports on purpose.
- ``service.py`` is a facade: it defines nothing, it re-exports.
- No function under ``application/`` exceeds 150 lines (the B3 bound).
- The B1 alias shims and the B2 ``services.py`` compatibility module are gone.
"""

from __future__ import annotations

from pathlib import Path


import utk_curio.backend.app.agents as agents_pkg
from utk_curio.backend.tests._support import layering

AGENTS = layering.LayeredPackage(
    root=Path(agents_pkg.__file__).resolve().parent,
    base="utk_curio.backend.app.agents",
    may_import={
        "domain": {"domain"},
        "repositories": {"domain", "repositories"},
        "infrastructure": {"domain", "repositories", "infrastructure"},
        "application": {"domain", "repositories", "infrastructure", "application"},
    },
    # the app factory, a project's seeding and the monitor's LLM check: the
    # three cross-feature boundaries that import agents lazily on purpose
    lazy_allowed_outside={"__init__.py", "projects/services.py", "monitor/routes.py"},
    lazy_allowed_inside={"utk_curio.backend.app.agents.domain", "utk_curio.backend.app.agents.repositories",
                         "utk_curio.backend.app.agents.infrastructure", 'utk_curio.backend.app.agents.routes.',
                         "utk_curio.backend.app.agents.schemas"},
)


def test_layers_only_import_downward():
    assert layering.downward_only_offenders(AGENTS) == []


def test_no_in_function_import_of_the_facade_or_application_inside_the_package():
    assert layering.lazy_inside_offenders(AGENTS) == []


def test_only_the_two_cross_feature_boundaries_import_agents_lazily_outside_the_package():
    assert layering.lazy_outside_offenders(AGENTS) == []


def test_the_facade_defines_nothing():
    assert layering.facade_defines_nothing(AGENTS)


def test_no_application_function_exceeds_150_lines():
    """B3: the Solve, turn and plan loops are decomposed — SolveBatch, VerifiedRounds,
    AttachmentTurn and the plan mint/apply steps; no application function is a screenful."""
    assert layering.oversize_functions(AGENTS) == []


def test_the_shims_and_the_compatibility_module_are_gone():
    assert layering.root_modules(AGENTS) == ["__init__.py", "service.py"]
    assert not (AGENTS.root / "routes.py").exists()
