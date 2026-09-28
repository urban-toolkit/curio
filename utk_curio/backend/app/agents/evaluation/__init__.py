"""Example-derived agent validation harness (memo dev/121, ``DEC-077``).

Measures whether the Dataflow Builder and its delegates can RECONSTRUCT one of
Curio's shipped example dataflows from a natural-language prompt, by scoring
the graph the production path actually produced (plan -> review/apply ->
background Solve -> persisted ``spec.trill.json``) against the example, and by
naming what the agent contract cannot express instead of lowering the bar.

Purity, deliberately (the ``source_grounding.py`` discipline): nothing in this
package imports Flask, a provider, the package store or the project store. It
takes specs, roster snapshots and catalog listings as VALUES and returns
values. The transports live outside it -- ``tests/test_agents``'s in-process
driver and ``utk_curio/tools/agent_eval.py`` -- so the ``app/agents`` boundary
holds and every comparison is unit-testable without a stack.

Nothing here re-implements a production path. Canonical node types come from
``packages.services.canonical_template_id``, executability from
``execution.workflow_spec.is_executable_kind``, the dataset-reference scan from
``agents.source_grounding``'s regexes, package dirNames from
``packages.spec_packages`` -- the harness is a reader, never a second
vocabulary (``DEC-062``).
"""

from utk_curio.backend.app.agents.evaluation.attempt import (  # noqa: F401
    UNEXPRESSIBLE_EDGE_KINDS,
    AttemptScore,
    score_attempt,
)
from utk_curio.backend.app.agents.evaluation.canonical import (  # noqa: F401
    CanonicalGraph,
    CEdge,
    CNode,
    Sources,
    canonical_graph_from_spec,
    role_for_template,
)
from utk_curio.backend.app.agents.evaluation.dependencies import (  # noqa: F401
    declared_dependencies,
    referenced_sources,
)
from utk_curio.backend.app.agents.evaluation.fixtures import (  # noqa: F401
    FIXTURE_SCHEMA_PATH,
    Fixture,
    FixtureError,
    fixture_paths,
    load_fixture,
    load_fixtures,
    sha256_of_file,
    validate_fixture_dict,
)

__all__ = [
    "UNEXPRESSIBLE_EDGE_KINDS",
    "AttemptScore",
    "CEdge",
    "CNode",
    "CanonicalGraph",
    "FIXTURE_SCHEMA_PATH",
    "Fixture",
    "FixtureError",
    "Sources",
    "canonical_graph_from_spec",
    "declared_dependencies",
    "fixture_paths",
    "load_fixture",
    "load_fixtures",
    "referenced_sources",
    "role_for_template",
    "score_attempt",
    "sha256_of_file",
    "validate_fixture_dict",
]
