import json
import os

import pytest
from playwright.sync_api import Browser, BrowserType

from . import comparisons, diagnostics, runner_split
from .utils import REPO_ROOT, start_catalog_calendar, stop_catalog_calendar
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
    "docs/examples/dataflows/MultiInput.json",
    "docs/examples/dataflows/MultiInputDataPool.json",

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

    # SCOUT's WRF forecast from the Data Catalog, one bundle of NetCDF files
    # read part by part by one loader; the
    # isolated stack runs it too (ISOLATED_WORKFLOWS in docker-compose.yml).
    "docs/examples/dataflows/NetCDF.json",

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
    "docs/examples/10-street-vision-cv-analysis.json",
    "docs/examples/11-autark-pbf-loading.json",
    "docs/examples/12-vega-lite-geodataframe-maps.json",
    "docs/examples/13-vega-lite-geometry-columns.json",
    "docs/examples/14-vega-lite-crs-and-geometry-types.json",
    "docs/examples/15-vega-lite-spec-forms-and-catalogs.json",
    "docs/examples/16-simple-view-tables-and-images.json",
    "docs/examples/17-autark-geodataframe-maps.json",
    # The storage examples read collections and tables added from the example
    # storage source, committed to datasets/ and resolved like any other.
    "docs/examples/18-storage-orthorectified-imagery.json",
    "docs/examples/19-storage-video-frames.json",
    "docs/examples/20-storage-folder-of-csv-files.json",
    "docs/examples/21-storage-photos-and-videos.json",
    "docs/examples/22-storage-audio-recordings.json",
    "docs/examples/23-storage-folder-of-different-files.json",
    # Package nodes: the stack installs scout.raster-conversion@1 and
    # scout.shadow@1 because the dataflow declares them (--with-examples).
    "docs/examples/24-scout-building-rasters.json",
    # One node fed by several others, in every kind that takes several inputs.
    "docs/examples/25-several-inputs.json",
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


@pytest.fixture(autouse=True)
def catalog_calendar(request, e2e_clean_db):
    """Run a test marked ``catalog_calendar`` on the fixed catalog date.

    Its captures show how long ago catalog items were made, so its browser
    context runs on ``CATALOG_CALENDAR`` and the backend stamps the records it
    makes on the same date (utils/catalog_clock.py), for this test only. Set up
    after ``e2e_clean_db``, whose reset puts the backend's clock back.
    """
    if request.node.get_closest_marker("catalog_calendar") is None:
        yield
        return
    backend = request.getfixturevalue("current_server")
    if "workflow_page" in request.fixturenames:
        context = request.getfixturevalue("workflow_page").context
    else:
        context = request.getfixturevalue("context")
    start_catalog_calendar(context, backend)
    yield
    stop_catalog_calendar(backend)


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
        params = []
        for f in files:
            basename = os.path.basename(f)
            # One xdist group per workflow. The four TestWorkflowCanvas
            # methods share a class-scoped browser, page and login, so they
            # must stay on one worker -- but different workflows are
            # independent, so ``--dist loadgroup`` can spread the ~30 groups
            # across workers instead of pinning the whole file to one.
            marks = [pytest.mark.xdist_group(f"wf-{basename}")]
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
        walk = getattr(getattr(item, "callspec", None), "params", {}).get("walk")
        if walk is not None:
            # One group per walkthrough scene. Each opens its own page and
            # user, so they are independent, and as one module group they were
            # the floor of the whole parallel run: 31 scenes, 8.8 minutes, on
            # one worker.
            item.add_marker(pytest.mark.xdist_group(f"walk-{walk.slug}"))
        elif module is not None:
            item.add_marker(pytest.mark.xdist_group(module.__name__.rsplit(".", 1)[-1]))


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "webgpu: the browser runs WebGPU, so CI runs it on the utk GPU runner "
        "(set automatically, see runner_split.py)",
    )
    config.addinivalue_line(
        "markers",
        "needs_parallel: needs the sibling backends of --parallel, which only "
        "the utk job runs (runner_split.py)",
    )
    config.addinivalue_line(
        "markers",
        "only_workflows(*basenames): a test_workflows test deselected for every "
        "other workflow",
    )
    config.addinivalue_line(
        "markers",
        "catalog_calendar: the test's captures show how long ago catalog items "
        "were made, so it runs on one fixed date (utils/catalog_clock.py)",
    )
    config.pluginmanager.register(_OnlyWorkflows(), "curio-only-workflows")


class _OnlyWorkflows:
    """Deselects an ``only_workflows`` test for every workflow it does not name.

    After pytest has put the items in order, never by parametrizing the test
    over fewer workflows: pytest orders a test with fewer parameters than its
    class's others ahead of them, so test_node_interaction ran its gestures
    before test_node_type_and_content looked at the nodes unrun (CI run
    36794470794). Selecting the test alone still loads only those workflows.
    """

    @pytest.hookimpl(trylast=True)
    def pytest_collection_modifyitems(self, config, items):
        kept, dropped = [], []
        for item in items:
            only = item.get_closest_marker("only_workflows")
            params = getattr(getattr(item, "callspec", None), "params", {}) or {}
            workflow = params.get("loaded_workflow")
            if only is not None and workflow is not None and os.path.basename(str(workflow)) not in only.args:
                dropped.append(item)
            else:
                kept.append(item)
        if dropped:
            config.hook.pytest_deselected(items=dropped)
            items[:] = kept


def pytest_collection_modifyitems(config, items):
    """Mark the WebGPU tests, and keep only this runner's share of the suite.

    Marking always happens, so ``-m webgpu`` / ``-m "not webgpu"`` work in any
    run. Deselection only happens when CI asks for it through
    ``CURIO_E2E_RUNNER`` / ``CURIO_E2E_PART`` (runner_split.py); a local run
    with neither set runs everything, as before.
    """
    for item in items:
        if runner_split.item_needs_webgpu(item):
            item.add_marker(pytest.mark.webgpu)
    runner, shard = runner_split.from_environment()
    if not runner and not shard:
        return
    kept, dropped = runner_split.select(items, runner, shard)
    if dropped:
        config.hook.pytest_deselected(items=dropped)
        items[:] = kept


# ------------------------------------------------------------------ #
# Failure diagnostics
# ------------------------------------------------------------------ #

@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_call(item):
    """Start the test's trace chunk, once its page exists (see diagnostics.py).

    Also names the test its screenshot comparisons are recorded under
    (comparisons.py), since the capture helper is not handed its item.
    """
    diagnostics.start_trace_chunk(item)
    comparisons.current_nodeid = item.nodeid
    yield
    comparisons.current_nodeid = None


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """Record screenshot, node states and browser log of a failed test.

    Here rather than in a fixture's teardown because the page is still open
    at this point; a function-scoped ``page`` is already closed by the time an
    autouse fixture tears down. A failed setup counts too: a class-scoped
    ``workflow_page`` may be up even though ``loaded_workflow`` failed.
    """
    outcome = yield
    report = outcome.get_result()
    if report.when == "call" or (report.when == "setup" and report.failed):
        diagnostics.finish(item, failed=report.failed)
