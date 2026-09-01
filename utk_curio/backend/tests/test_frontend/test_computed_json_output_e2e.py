"""Playwright E2E for #180: a non-tabular Python Computation output installs cleanly.

The report: with the per-node "save output to Data Catalog" toggle on, running a
Python Computation node whose return value is a scalar, a dict, a list or
``None`` pops

    Dataset for "Python Computation" couldn't be generated. Re-run that node.

and no dataset ever appears. Re-running never helped, because nothing was
missing: those kinds have no artifact FILE at all (their value lives in the
DuckDB ``artifacts`` row), and the single-output installer only knew how to
hard-link a file.

The chain is invisible from the canvas: ``applyNewOutput`` ->
``scheduleInstallSyncRef`` (500 ms debounce, ``FlowProvider.tsx``) ->
``persistDataflowForInstall`` -> a project PUT -> ``_auto_install_computed_outputs``
-> ``dataset_install_warnings`` in the response -> ``surfaceInstallWarnings`` ->
the toast. Every hop but the last is server-side or debounced, which is why the
suite worked around the symptom (``dismiss_toasts``' quiet-window sweep exists
for exactly this warning) instead of failing on it.

This test pins the chain from the only place it is observable end to end:

  * the save that carried the node's output ref answers with
    ``dataset_install_warnings: []`` - the deterministic signal, read off the
    response rather than the DOM;
  * no "couldn't be generated" toast is raised, recorded from a MutationObserver
    so a toast that appeared and auto-dismissed still counts as a failure;
  * the dataset genuinely exists, is ``format: "json"``, and **downloads as real
    JSON bytes**. That last one closes the adjacent defect: dict/list artifacts
    are written zlib-compressed, and an install that hard-linked them served a
    compressed body under a ``.json`` name that no client could parse.

Covered more cheaply elsewhere and not re-asserted here: the palette drag and
Monaco's ``setValue`` path (``test_canvas_authoring_e2e.py``); the installer's
format resolution and the warning payload
(``tests/test_datasets/test_computed_scalar_json_outputs.py``,
``test_play_all_install_warnings.py``); the drawer's rendering
(``test_data_catalog.py``).

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_computed_json_output_e2e.py -v
"""
from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

import pytest
from playwright.sync_api import expect

from .utils import (
    _wait_for_reactflow_ready,
    api_json,
    canvas_node_type,
    dismiss_toasts,
    drag_to_canvas,
    node_locator,
    require_project_page,
    require_user_auth,
    run_node_and_wait,
    save_workflow_test_screenshot,
    set_node_code,
    require_owner_view,
    stub_login_and_enter_workflow,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

ANALYSIS_TILE = "#step-analysis"  # curio.builtin/computation-analysis's tutorialId
ANALYSIS_TYPE = "curio.builtin/computation-analysis"

DRAWER_ROOT = '[data-curio-dataset-catalog-drawer="true"]'

# Nodes are 525x350 at zoom 1 in a 1280x720 viewport, so drops closer than
# ~600px apart horizontally overlap and the later body covers the earlier one.
POS_LEFT = (150, 150)
POS_RIGHT = (760, 150)

# Nested and multi-key on purpose: a computed JSON dataset must round-trip the
# whole structure, not just survive as some flattened shape.
DICT_PAYLOAD = {"city": "Chicago", "pm25": 12.5, "zones": [1, 2, 3]}
DICT_CODE = "return " + json.dumps(DICT_PAYLOAD) + "\n"

SCALAR_PAYLOAD = 42
SCALAR_CODE = "return {}\n".format(SCALAR_PAYLOAD)

WARNING_FRAGMENT = "couldn't be generated"

# Records every toast text the page ever shows, from a MutationObserver on the
# portal container. A DOM snapshot is not enough: ToastProvider removes a toast
# after 5000 ms, so a "couldn't be generated" warning can raise and vanish
# between two assertions and look like a pass. Deduped by text, which is fine
# for an absence check.
_TOAST_RECORDER_JS = r"""() => {
    if (window.__curioToastLog) return "already";
    const region = document.querySelector('[aria-label="Notifications"]');
    if (!region) return "no toast region";
    window.__curioToastLog = [];
    const record = () => {
        region.querySelectorAll('.toast').forEach((t) => {
            const text = (t.textContent || '').trim();
            if (text && !window.__curioToastLog.includes(text)) {
                window.__curioToastLog.push(text);
            }
        });
    };
    new MutationObserver(record).observe(region, { childList: true, subtree: true });
    record();
    return "ok";
}"""


def _record_toasts(page) -> None:
    """Start capturing toasts.

    ToastProvider portals an empty container into <body>, so this only needs the
    app shell, not a canvas node.
    """
    page.wait_for_selector('[aria-label="Notifications"]', state="attached", timeout=20000)
    status = page.evaluate(_TOAST_RECORDER_JS)
    assert status in ("ok", "already"), "toast recorder did not attach: {}".format(status)


def _assert_no_install_warning_toast(page, context: str) -> None:
    recorded = page.evaluate("() => window.__curioToastLog || []")
    offenders = [t for t in recorded if WARNING_FRAGMENT in t]
    assert not offenders, (
        "{}: the debounced dataset install raised a couldn't-be-generated "
        "warning (#180): {}".format(context, offenders)
    )


def _install_save_response(project_id: str, node_id: str):
    """Predicate for the project save that carried *node_id*'s output ref.

    Not "any PUT to this project", deliberately. A dirty canvas autosaves every
    30 s through the same ``saveCurrentProject``, answered with the same
    ``dataset_install_warnings`` field, so a URL-only waiter can be satisfied by
    a save that fired BEFORE the node produced anything and then assert an empty
    warning list that means nothing. ``outputs`` is populated only from
    ``outputsRef``, which ``applyNewOutput`` writes, so requiring the node's own
    ref in the request body is exactly "the save that tried to install this node".
    """

    def _match(response) -> bool:
        request = response.request
        if request.method != "PUT":
            return False
        if not response.url.endswith("/api/projects/{}".format(project_id)):
            return False
        try:
            body = json.loads(request.post_data or "{}")
        except (TypeError, ValueError):
            return False
        return any(
            isinstance(ref, dict) and ref.get("node_id") == node_id
            for ref in (body.get("outputs") or [])
        )

    return _match


def _parse_json_bytes(raw: bytes, label: str):
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise AssertionError(
            "{} did not download as JSON ({}); first bytes {!r}. A zlib stream "
            "starts 0x78 - a computed JSON dataset installed straight from the "
            "sandbox's compressed .json.zlib artifact is served compressed under "
            "a .json name, which no client can read (#180).".format(label, exc, raw[:8])
        ) from None


def _computed_id(node_id: str, project_id: str) -> str:
    """Built with the production helper, never hand-rolled: the un-namespaced
    ``computed.<node>`` form is lookup-only and the installers refuse it."""
    from utk_curio.backend.app.datasets.install.installer import computed_dataset_id

    return computed_dataset_id(node_id, project_id)


def _purge_existing_computed(server: str, token: str) -> int:
    """Delete every computed dataset already in this user's store.

    ``/api/testing/reset-db`` truncates SQL only, and ``user.id`` is a bare
    sqlite rowid alias that recycles from 1, so ``.curio/users/1/datasets/``
    carries computed datasets left by earlier tests and earlier pytest runs
    (``test_dataset_palette.py`` mints one and does not remove it). Without this
    the Computed tab shows those too, which would make both the count assertion
    and the drawer baseline depend on run history.
    """
    catalog = api_json(
        "{}/api/datasets/catalog?includeHub=false".format(server), token
    )
    stale = [i["id"] for i in catalog["items"] if i.get("origin") == "computed"]
    for dataset_id in stale:
        try:
            api_json("{}/api/datasets/{}".format(server, dataset_id), token, method="DELETE")
        except Exception as exc:  # noqa: BLE001 - best effort, asserted below
            print("[setup] could not purge {}: {}".format(dataset_id, exc))
    return len(stale)


def _catalog_item(server: str, token: str, project_id: str, dataset_id: str) -> dict:
    catalog = api_json(
        "{}/api/datasets/catalog?includeHub=false&dataflowId={}".format(server, project_id),
        token,
    )
    item = next((i for i in catalog["items"] if i["id"] == dataset_id), None)
    assert item is not None, (
        "the run produced no computed dataset {}; the catalog holds {}. A "
        "scalar/dict output whose install is skipped leaves exactly this state "
        "(#180).".format(dataset_id, [(i["id"], i["origin"]) for i in catalog["items"]])
    )
    return item


@pytest.fixture
def delete_computed_datasets(current_server):
    """Remove the computed datasets a test installed, through the real DELETE route.

    ``/api/testing/reset-db`` truncates SQL only: ``.curio/users/<id>/datasets/``
    survives, and ``user.id`` is a bare sqlite rowid alias that recycles from 1,
    so without this the next run's "fresh" user sees a phantom dataset.
    Non-autouse and requested explicitly, because the autouse ``e2e_clean_db``
    finalizes last and this needs a live stub user to authenticate its DELETEs.
    """
    registered: list[tuple[str, str]] = []

    def register(token: str, dataset_id: str) -> None:
        registered.append((token, dataset_id))

    yield register

    for token, dataset_id in registered:
        try:
            api_json(
                "{}/api/datasets/{}".format(current_server, dataset_id),
                token,
                method="DELETE",
            )
        except Exception as exc:  # noqa: BLE001 - teardown must not mask failures
            print("[teardown] DELETE dataset {} failed: {}".format(dataset_id, exc))


def _author_analysis_node(page, at, code: str) -> str:
    """Drop a Python Computation node, set its code, and turn its save toggle on.

    No upstream edge: ``#step-analysis`` runs standalone as long as the code does
    not reference ``arg`` (see worker.py's "received no input" guard), which is
    what ``test_global_imports_e2e.py`` relies on too.
    """
    node_id = drag_to_canvas(page, page.locator(ANALYSIS_TILE), at=at)
    actual = (canvas_node_type(page, node_id) or "").split("@", 1)[0]
    assert actual == ANALYSIS_TYPE, (
        "#step-analysis did not drop a Python Computation node: {!r}".format(actual)
    )
    # Through Monaco's setValue: autoClosingBrackets + formatOnType mean typed
    # Python does not round-trip, and setValue fires the same onChange chain.
    set_node_code(page, node_id, code)
    _enable_save_toggle(page, node_id)
    return node_id


def _enable_save_toggle(page, node_id: str) -> None:
    """Flip the node's save-output toggle on through the UI.

    Deliberately not left to the deployment default, which is off: "the user
    enabled the toggle" is the scenario #180 reports. Keying on the aria-label
    makes the click double as an assertion that the toggle actually flipped.
    """
    toggle = node_locator(page, node_id).locator("label:has(input#save-output-{})".format(node_id))
    toggle.wait_for(state="visible", timeout=15000)
    if "enabled" in (toggle.get_attribute("aria-label") or ""):
        return
    toggle.click()
    expect(toggle).to_have_attribute(
        "aria-label", "Save output to Data Catalog enabled", timeout=10000
    )


def _run_and_capture_save(page, project_id: str, node_id: str) -> tuple[str, dict]:
    """Run one node and return ``(output text, parsed save response)``.

    The waiter is armed BEFORE the run on purpose. ``wait_for_node_done`` only
    watches ``data-curio-node-status``, which flips in the same synchronous block
    that calls ``applyNewOutput``, while the install-save is 500 ms debounced
    after that plus a round trip. Asserting anything the moment the node says
    Done is asserting against a state that has not happened yet.
    """
    with page.expect_response(
        _install_save_response(project_id, node_id), timeout=180000
    ) as save_info:
        output = run_node_and_wait(page, node_id, node_type=ANALYSIS_TYPE)
    response = save_info.value
    assert response.ok, "install-save failed: {} {}".format(response.status, response.url)
    return output, response.json()


def test_a_dict_and_a_scalar_output_install_without_a_warning(
    app_frontend: "FrontendPage",
    current_server: str,
    page,
    delete_computed_datasets,
):
    require_project_page()
    require_user_auth()

    # Before navigating: the toast/drawer providers read prefers-reduced-motion
    # through useSyncExternalStore, and doing this after login races
    # ProjectLoader into the shared-guest fallback.
    page.emulate_media(reduced_motion="reduce")
    session = stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Json Output",
        username="json_output",
        project_name="Computed JSON Output",
    )
    # A shared-guest session can never see the owner's computed datasets, so the
    # catalog half of this test would be meaningless there.
    require_owner_view(page)
    token = session["token"]
    project_id = session["project"]["id"]

    # Start from a known store, so "the Computed tab holds exactly this test's
    # two datasets" is a statement about this run and not about run history.
    _purge_existing_computed(current_server, token)

    _record_toasts(page)

    dict_node = _author_analysis_node(page, POS_LEFT, DICT_CODE)
    scalar_node = _author_analysis_node(page, POS_RIGHT, SCALAR_CODE)
    # ReactFlow's initial fitView animates the viewport; a visible-but-moving
    # node makes every interaction on it time out with no useful message.
    _wait_for_reactflow_ready(page)

    computed_ids = [_computed_id(node_id, project_id) for node_id in (dict_node, scalar_node)]
    for dataset_id in computed_ids:
        delete_computed_datasets(token, dataset_id)

    # 1. The dict node.
    dict_output, dict_save = _run_and_capture_save(page, project_id, dict_node)
    assert "Saved to file:" in dict_output, dict_output
    assert dict_save.get("dataset_install_warnings") == [], (
        "the save that carried {}'s output reported install warnings {!r}; a dict "
        "return value must install as a json computed dataset, not be skipped "
        "(#180)".format(dict_node, dict_save.get("dataset_install_warnings"))
    )

    # 2. The scalar node. Run second and assert separately rather than relying on
    #    the 500 ms debounce to collapse both: the two runs are seconds apart, so
    #    which save covers which node is not something to guess at.
    scalar_output, scalar_save = _run_and_capture_save(page, project_id, scalar_node)
    assert "Saved to file:" in scalar_output, scalar_output
    assert scalar_save.get("dataset_install_warnings") == [], (
        "the save that carried {}'s output reported install warnings {!r}; a "
        "scalar return value has no parquet and no artifact file, and used to be "
        "skipped outright (#180)".format(
            scalar_node, scalar_save.get("dataset_install_warnings")
        )
    )
    # This save re-sent the dict node's ref too (buildOutputRefs rebuilds refs for
    # every toggle-enabled node), so an empty list here also shows the first
    # node's dataset stayed installable across a second save.

    # 3. The datasets are real and usable.
    for node_id, expected in ((dict_node, DICT_PAYLOAD), (scalar_node, SCALAR_PAYLOAD)):
        dataset_id = _computed_id(node_id, project_id)
        item = _catalog_item(current_server, token, project_id, dataset_id)
        assert item["format"] == "json", (
            "{} installed as {!r}; a dict/scalar output maps to json via "
            "SANDBOX_DATATYPE_TO_FORMAT".format(dataset_id, item["format"])
        )
        assert item["producerNodeId"] == node_id, item
        # A computed output is an account-level asset: the save must NOT write a
        # project spec ref, because attaching one is an explicit user action.
        assert item.get("installed") is False, item

        detail = api_json("{}/api/datasets/{}".format(current_server, dataset_id), token)
        assert detail["format"] == "json", detail

        # The bytes, not just the metadata. This closes the adjacent defect: a
        # hard-linked .json.zlib answers this endpoint with a zlib stream under a
        # .json name.
        raw = api_json(
            "{}/api/datasets/{}/download?dataflowId={}".format(
                current_server, dataset_id, project_id
            ),
            token,
            raw=True,
        )
        # Exact equality, no unwrapping: a single-file computed dataset stores
        # the producer's value bare, so what a Dataset node reloads is what the
        # node returned. (Bundles keep a {"value": ...} envelope, which their
        # own loader unwraps by part kind.)
        assert _parse_json_bytes(raw, dataset_id) == expected, (
            "{} downloaded {!r}, expected the node's return value {!r}".format(
                dataset_id, raw[:200], expected
            )
        )

        # Preview is what the drawer renders; a 200 proves the dataset is
        # browsable, not merely present. api_json raises on any non-2xx.
        preview = api_json(
            "{}/api/datasets/{}/preview?dataflowId={}".format(
                current_server, dataset_id, project_id
            ),
            token,
        )
        assert "rows" in preview, preview

    # 4. Nothing was toasted at the user, at any point. Secondary to the response
    #    assertions above, and deliberately BEFORE any dismiss_toasts: a sweep
    #    would erase the very evidence. The recorder has been running since
    #    before the first node existed.
    _assert_no_install_warning_toast(page, "after two clean Python Computation runs")

    # 5. Baselines. Only now is it safe to sweep toasts, which the helper
    #    requires: they are bottom-right, up to 360px wide, and land exactly
    #    where canvas content usually is.
    dismiss_toasts(page)
    save_workflow_test_screenshot(
        page,
        "computed-json-output",
        test_name="test_a_dict_and_a_scalar_output_install_without_a_warning",
    )

    _open_computed_tab(page, computed_ids)
    dismiss_toasts(page)
    save_workflow_test_screenshot(
        page,
        "computed-json-output",
        test_name="test_a_dict_and_a_scalar_output_install_without_a_warning_computed_tab",
    )


def _open_computed_tab(page, dataset_ids) -> None:
    """Open the Data Catalog drawer on its Computed tab.

    The visual counterpart to the API assertions: nothing else in the suite pins
    that a JSON computed dataset renders as a card at all.
    """
    page.get_by_role("button", name="Data ⏷", exact=True).click(force=True)
    page.get_by_role("button", name="Data Catalog", exact=True).click(force=True)

    root = page.locator(DRAWER_ROOT)
    root.wait_for(state="attached", timeout=15000)
    # aria-hidden IS the presented signal: the drawer slides in via translate3d,
    # which keeps a full bounding box off-screen, so to_be_visible is not a gate.
    expect(root).to_have_attribute("aria-hidden", "false", timeout=10000)

    tab = page.get_by_role("button", name=re.compile(r"^Computed"))
    tab.click()
    # Key on the two dataset ids rather than the badge count: the count also
    # counts anything left in the user store by an earlier run, so it says
    # nothing about THIS test and fails with "Computed3" instead of naming what
    # is missing. The setup purge keeps the drawer at exactly these two, which is
    # what makes the baseline below deterministic.
    for dataset_id in dataset_ids:
        card = root.locator(
            'article:not([role="status"])[data-dataset-id="{}"]'.format(dataset_id)
        )
        expect(card).to_have_count(1, timeout=20000)
