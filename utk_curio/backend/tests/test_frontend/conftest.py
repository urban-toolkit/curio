import json
import os

import pytest
from playwright.sync_api import Browser, BrowserType

from .utils import REPO_ROOT
from .fixtures import _clean_db


# ------------------------------------------------------------------ #
# Class-scoped browser override
# ------------------------------------------------------------------ #
#
# pytest-playwright ships a session-scoped ``browser`` fixture, so one
# Chromium process handles the whole run.  Over the ~25 parametrized
# workflow classes in this suite, Chromium's V8/GPU/renderer heaps don't
# fully reclaim across closed contexts; on a 16 GiB GH-hosted runner the
# host has leaked >7 GiB by the heavy linked-view workflow (#09), pushing
# the runner into OOM and "lost communication with the server" failures.
# Re-launching Chromium between workflow classes drops it back to baseline
# at the cost of ~5 s × workflow_count of startup overhead.

class _BackendUrlBrowser:
    """A ``Browser`` whose every new context knows this worker's backend.

    The bundle resolves the backend address at runtime from
    ``window.__CURIO_BACKEND_URL__`` (src/utils/backendUrl.ts), falling back to
    the value baked at build time. Injecting it per context is what lets ONE
    frontend build serve several backend+sandbox pairs at once under xdist.

    Wrapped at the browser, not the ``context`` fixture: sixteen tests call
    ``browser.new_context(...)`` themselves (two-user flows, share links, the
    video tours), and pytest-playwright's own ``context`` fixture goes through
    the same method. A context that missed the script would talk to whatever
    backend the bundle was built for -- under xdist, some OTHER worker's -- and
    pass against a stack the test does not own. ``__getattr__`` forwards
    everything else; Playwright's ``Browser`` has no public constructor to
    subclass.
    """

    def __init__(self, inner: "Browser", backend_url: str):
        self._inner = inner
        self._init_script = f"window.__CURIO_BACKEND_URL__ = {json.dumps(backend_url)};"

    def new_context(self, **kwargs):
        context = self._inner.new_context(**kwargs)
        context.add_init_script(self._init_script)
        return context

    def __getattr__(self, name):
        return getattr(self._inner, name)


@pytest.fixture(scope="class")
def browser(
    browser_type: "BrowserType",
    browser_type_launch_args: dict,
    current_server: str,
) -> "Browser":
    launched = browser_type.launch(**browser_type_launch_args)
    yield _BackendUrlBrowser(launched, current_server)
    launched.close()

# ------------------------------------------------------------------ #
# Workflow scenario discovery
# ------------------------------------------------------------------ #

#: Master list of workflow JSON filenames to test.
#: Comment out / add entries here to control the full test matrix.
WORKFLOW_FILES = [
    "docs/examples/dataflows/DefaultWorkflow.json",

    "docs/examples/dataflows/DataPool_Dataframe.json",
    "docs/examples/dataflows/DataPool_Geodataframe.json",

    "docs/examples/dataflows/DataPool_Vega.json",
    "docs/examples/dataflows/DataPool_Vega_2.json",
    "docs/examples/dataflows/DataPool_AutkMap.json",

    "docs/examples/dataflows/Image.json",
    "docs/examples/dataflows/SimpleView.json",
    "docs/examples/dataflows/Merge.json",
    "docs/examples/dataflows/MergeFlowDataPool.json",

    "docs/examples/dataflows/JSComputation.json",

    "docs/examples/dataflows/Interaction_Vega.json",
    "docs/examples/dataflows/Interaction_Vega_Simple.json",
    "docs/examples/dataflows/Interaction_AutkMap.json",
    "docs/examples/dataflows/Interaction_Autark.json",
    "docs/examples/dataflows/Interaction_Vega_Autark.json",

    "docs/examples/dataflows/Widget.json",

    "docs/examples/dataflows/Vega.json",
    "docs/examples/dataflows/AutkMap.json",

    "docs/examples/dataflows/Regression.json",

    # Curated examples shown in docs/README.md. These are the showcase
    # workflows — including the modular autk-grammar GPU/compute chains — so
    # they belong in the browser matrix, not just the structural checks in
    # test_examples.py. The class-scoped ``browser`` fixture above re-launches
    # Chromium per workflow class to keep memory bounded across the suite.
    "docs/examples/01-vega-lite-chained-transforms.json",
    "docs/examples/02-vega-lite-spatial-density.json",
    "docs/examples/03-vega-lite-linked-temporal-charts.json",
    "docs/examples/04-vega-lite-multi-flow-dashboard.json",
    "docs/examples/05-vega-lite-multi-view-drilldown.json",
    "docs/examples/06-autark-what-if-shadow-study.json",
    "docs/examples/07-autark-gpu-shader.json",
    "docs/examples/08-autark-spatial-join-regression.json",
    "docs/examples/09-heterogeneous-data-linked-views.json",
    # Example 10 depends on external services (HuggingFace CV inference +
    # street-view APIs) and the non-builtin curio.streetvision package, so it
    # can't run offline/deterministically. It is listed here (so it stays
    # selectable via CURIO_E2E_WORKFLOWS) but the ``loaded_workflow`` fixture
    # skips it with a reason unless CURIO_E2E_EXTERNAL=1 — a visible, reasoned
    # skip rather than a silent omission.
    "docs/examples/10-street-vision-cv-analysis.json",
    "docs/examples/11-autark-pbf-loading.json",
]


def load_workflow_files_from_folder():
    """Return absolute paths for every workflow in WORKFLOW_FILES.

    Respects the ``CURIO_E2E_WORKFLOWS`` environment variable: when set
    to a comma-separated list of basenames (e.g.
    ``CURIO_E2E_WORKFLOWS=Vega.json,AutkMap.json``) only those workflows
    are included.  Basenames are resolved against ``WORKFLOW_FILES`` so
    callers don't need to know the ``docs/examples/dataflows/`` prefix.
    This makes it easy to run a quick subset during development or in CI
    smoke tests.
    """
    subset = os.environ.get("CURIO_E2E_WORKFLOWS")
    if not subset:
        return [os.path.join(REPO_ROOT, name) for name in WORKFLOW_FILES]
    requested = [n.strip() for n in subset.split(",") if n.strip()]
    by_basename = {os.path.basename(p): p for p in WORKFLOW_FILES}
    resolved: list[str] = []
    for name in requested:
        # Already a relative path that exists in WORKFLOW_FILES — use as-is.
        if name in WORKFLOW_FILES:
            resolved.append(name)
            continue
        # Bare basename — look it up in the master list.
        match = by_basename.get(os.path.basename(name))
        if match is None:
            raise ValueError(
                f"CURIO_E2E_WORKFLOWS entry {name!r} is not in WORKFLOW_FILES; "
                f"valid basenames: {sorted(by_basename)}"
            )
        resolved.append(match)
    return [os.path.join(REPO_ROOT, name) for name in resolved]


# ------------------------------------------------------------------ #
# Dynamic parametrization hook
# ------------------------------------------------------------------ #

@pytest.fixture(autouse=True)
def e2e_clean_db(request, test_db_paths):
    """Truncate mutable SQLAlchemy tables before and after each frontend test.

    Scoped to ``test_frontend/`` via this conftest so ``test_projects`` /
    ``test_users`` (their own ``app`` fixture) are not affected.  Uses HTTP
    ``/api/testing/reset-db`` when ``CURIO_E2E_USE_EXISTING=1`` so the
    running backend wipes its own sqlite file.
    """
    _clean_db(request, test_db_paths)
    yield
    _clean_db(request, test_db_paths)


def pytest_generate_tests(metafunc):
    """Parametrize any test / fixture that requests ``loaded_workflow``.
    Ref: https://docs.pytest.org/en/stable/example/parametrize.html#a-quick-port-of-testscenarios
    This replaces the previous
    ``@pytest.mark.parametrize("loaded_workflow", ..., indirect=True)``
    on ``TestWorkflowCanvas``.  Because it lives in conftest.py, it
    applies to every module collected under ``test_frontend/``.
    """
    if "loaded_workflow" in metafunc.fixturenames:
        files = load_workflow_files_from_folder()
        # Example 10 (street-vision) drives external services — HuggingFace CV
        # inference + street-view APIs via the non-builtin curio.streetvision
        # package — so it can't run offline/deterministically. Skip it at
        # collection time (before any browser/server fixture setup) with a
        # visible reason unless CURIO_E2E_EXTERNAL=1, rather than silently
        # dropping it from the matrix.
        external = os.environ.get("CURIO_E2E_EXTERNAL") == "1"
        params = []
        for f in files:
            basename = os.path.basename(f)
            # One xdist group per workflow. The four TestWorkflowCanvas
            # methods share a class-scoped browser, page and login, so they
            # must stay on one worker -- but different workflows are
            # independent, so ``--dist loadgroup`` can spread the ~30 groups
            # across workers instead of pinning the whole file to one.
            marks = [pytest.mark.xdist_group(f"wf-{basename}")]
            if basename.startswith("10-") and not external:
                marks.append(pytest.mark.skip(reason=(
                    "example 10 (street-vision) needs external HuggingFace "
                    "inference + street-view APIs and the curio.streetvision "
                    "package; set CURIO_E2E_EXTERNAL=1 to run it"
                )))
            params.append(pytest.param(f, marks=marks, id=basename))
        metafunc.parametrize("loaded_workflow", params, indirect=True)


def pytest_itemcollected(item):
    """Default every item without an explicit xdist group to its module.

    Under ``--dist loadgroup`` a group runs on one worker in collection order,
    so a per-file group preserves every module-scoped fixture and every
    within-file ordering assumption a test may rely on. Only the workflow
    matrix above is split finer (see ``pytest_generate_tests``).

    This hook fires during collection, strictly before xdist's own
    ``pytest_collection_modifyitems`` appends the ``@group`` suffix to node
    ids -- doing it in that hook instead would race xdist's ``tryfirst``.
    """
    if item.get_closest_marker("xdist_group") is None:
        module = getattr(item, "module", None)
        if module is not None:
            item.add_marker(pytest.mark.xdist_group(module.__name__.rsplit(".", 1)[-1]))
