import os
import shutil
import subprocess
import sys

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


def _reap_orphaned_chrome() -> None:
    """Best-effort kill of Chrome child processes left after ``close()``.

    Under Chrome's *new* headless on the GPU-less Linux CI runner (see the
    Linux WebGPU branch in the root conftest), software WebGPU runs in a
    separate **GPU process** that holds the SwiftShader render/compute
    buffers. ``browser.close()`` tears down the browser process but does
    not always reap that GPU process (nor the utility/crashpad helpers),
    so across the ~25 workflow classes their buffers accumulate and the
    runner OOM-kills the pytest process mid-suite. Reaping the orphans
    after each class returns the host to baseline.

    CI-only and Linux-only: gated on ``CI`` so it never touches a
    developer's desktop Chrome. Best-effort — failures are ignored.
    """
    if not sys.platform.startswith("linux"):
        return
    if not os.environ.get("CI"):
        return
    if not shutil.which("pkill"):
        return
    for pattern in (
        "--type=gpu-process",
        "--type=utility",
        "chrome_crashpad_handler",
    ):
        subprocess.run(
            ["pkill", "-9", "-f", pattern],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


@pytest.fixture(scope="class")
def browser(
    browser_type: "BrowserType",
    browser_type_launch_args: dict,
) -> "Browser":
    launched = browser_type.launch(**browser_type_launch_args)
    yield launched
    launched.close()
    _reap_orphaned_chrome()

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
            marks = []
            if basename.startswith("10-") and not external:
                marks = [pytest.mark.skip(reason=(
                    "example 10 (street-vision) needs external HuggingFace "
                    "inference + street-view APIs and the curio.streetvision "
                    "package; set CURIO_E2E_EXTERNAL=1 to run it"
                ))]
            params.append(pytest.param(f, marks=marks, id=basename))
        metafunc.parametrize("loaded_workflow", params, indirect=True)
