"""Playwright E2E: every destructive catalog action asks first, and says what it will do.

Three of these confirmations did not exist, and the two that did understated
their reach. The audit that produced this list is in the session notes; each
test below states the specific defect it pins.

- **Data "Remove from project" had no dialog at all** and, for an upload no
  other dataflow used, permanently deleted the file from the account while the
  toast said only "Removed ... from this dataflow."
- **Node "Remove from project" confirmed, but understated.** The prune deletes
  the package from the user store, drops it from defaults, and `pip uninstall`s
  its Python libraries from the interpreter Curio itself runs on - shared by
  every dataflow and everyone on the instance. The dialog said none of that,
  and the response fields reporting it (`pruned`, `removedFromDefaults`) were
  discarded by the UI.
- **Publish had no dialog on any surface**, though it is the only write in the
  product that leaves the account, and its inverse (Unpublish) always confirmed.

The publish-ownership test is the one to read first: publishing only makes sense
for something the user made or brought. Everything in a default installation
came FROM the shared catalog, so offering to publish it back would write a
duplicate - and the backend has no guard, so the affordance is the guard.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_catalog_destructive_confirms_e2e.py -v
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

from playwright.sync_api import expect

from .utils import (
    accept_confirm_dialog,
    connect_nodes,
    drag_to_canvas,
    require_owner_view,
    require_project_page,
    require_user_auth,
    run_node_and_wait,
    save_workflow_test_screenshot,
    set_node_code,
    stub_login_and_enter_workflow,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

DATA_DRAWER = '[data-curio-dataset-catalog-drawer="true"]'
NODE_DRAWER = '[data-curio-node-catalog-drawer="true"]'
#: The catalog PAGES' detail drawer. Publishing lives here and nowhere else.
BROWSE_DRAWER = '[data-curio-browse-drawer="true"]'

LOADING_TILE = "#step-loading"
LOADING_TYPE = "curio.builtin/data-loading"

#: A node body that outputs a frame, so running it leaves a ``computed.`` dataset
#: behind. Shared by the two publish tests, which differ only in where they then
#: look for the Publish action.
OWN_DATASET_CODE = (
    "import pandas as pd\n"
    "df = pd.DataFrame({'a': [1, 2, 3], 'b': ['x', 'y', 'z']})\n"
    "return df\n"
)


def _modal(page, name):
    """The ConfirmDialog, by accessible name.

    The drawers are themselves ``role="dialog"``, so a bare role query matches
    two things whenever one is open.
    """
    dialog = page.get_by_role("dialog", name=name)
    dialog.wait_for(state="visible", timeout=15000)
    return dialog


def _open_data_drawer(page):
    page.get_by_role("button", name="Data ⏷", exact=True).click(force=True)
    page.get_by_role("button", name="Data Catalog", exact=True).click()
    root = page.locator(DATA_DRAWER)
    root.wait_for(state="attached", timeout=15000)
    expect(root).to_have_attribute("aria-hidden", "false", timeout=10000)
    return page.get_by_role("dialog").filter(
        has=page.get_by_role("heading", name="Data Catalog", exact=True)
    )


def _open_node_drawer(page):
    page.get_by_role("button", name="Data ⏷", exact=True).click(force=True)
    page.get_by_role("button", name="Node Catalog", exact=True).click()
    root = page.locator(NODE_DRAWER)
    root.wait_for(state="attached", timeout=15000)
    expect(root).to_have_attribute("aria-hidden", "false", timeout=10000)
    return page.get_by_role("dialog").filter(
        has=page.get_by_role("heading", name="Node Catalog", exact=True)
    )


def _enter(page, frontend, backend, username):
    page.emulate_media(reduced_motion="reduce")
    stub_login_and_enter_workflow(
        page,
        frontend_url=frontend,
        backend_url=backend,
        name="Confirm User",
        username=username,
        project_name="Destructive confirms",
    )
    require_owner_view(page)
    page.locator("#tools-menu").wait_for(state="visible", timeout=45000)


def test_removing_a_dataset_from_the_dataflow_asks_first(
    app_frontend: "FrontendPage", current_server: str, page
):
    """It had no confirmation at all - the one catalog of three without one."""
    require_project_page()
    require_user_auth()
    _enter(page, app_frontend.base_url, current_server, "confirm_data_remove")

    drawer = _open_data_drawer(page)
    # A catalog row, not "the first card". The drawer also lists the account's
    # own imported and computed datasets, and those are already in the dataflow
    # - so the first card can arrive offering "Remove from project" and the add
    # below never finds its button. Whether it does depends on leftover per-user
    # state, which is what made this fail intermittently rather than always.
    card = drawer.locator('article[data-dataset-id^="data."]').first
    card.wait_for(state="visible", timeout=30000)
    dataset_id = card.get_attribute("data-dataset-id")

    add = card.get_by_role("button", name="Add to project", exact=True)
    add.click()
    with page.expect_response(
        lambda r: "/datasets/install" in r.url and r.request.method == "POST" and r.ok,
        timeout=60000,
    ):
        accept_confirm_dialog(page, title=re.compile(r"^Add "), button="Add to project")

    row = drawer.locator(f'article[data-dataset-id="{dataset_id}"]')
    remove = row.get_by_role("button", name="Remove from project", exact=True)
    expect(remove).to_be_visible(timeout=30000)

    # THE POINT: a dialog, where there used to be none.
    remove.click()
    modal = _modal(page, re.compile(r"^Remove "))
    expect(modal).to_contain_text("from this project?")
    save_workflow_test_screenshot(
        page, "data-remove-confirm",
        test_name="test_removing_a_dataset_from_the_dataflow_asks_first",
        fit_reactflow=False,
    )

    # Cancel really cancels: still in the dataflow afterwards.
    modal.get_by_role("button", name="Cancel", exact=True).click()
    expect(modal).to_have_count(0, timeout=10000)
    expect(
        drawer.locator(f'article[data-dataset-id="{dataset_id}"]').get_by_role(
            "button", name="Remove from project", exact=True
        )
    ).to_be_visible(timeout=10000)

    # And confirming removes it.
    drawer.locator(f'article[data-dataset-id="{dataset_id}"]').get_by_role(
        "button", name="Remove from project", exact=True
    ).click()
    with page.expect_response(
        lambda r: "/datasets/" in r.url and r.request.method == "DELETE",
        timeout=60000,
    ):
        _modal(page, re.compile(r"^Remove ")).get_by_role(
            "button", name=re.compile(r"^Remove")
        ).click()

    expect(
        drawer.locator(f'article[data-dataset-id="{dataset_id}"]').get_by_role(
            "button", name="Add to project", exact=True
        )
    ).to_be_visible(timeout=30000)


def test_removing_a_package_says_it_reaches_the_shared_environment(
    app_frontend: "FrontendPage", current_server: str, page
):
    """The dialog existed but described a dataflow-scoped edit.

    `prune_unreferenced_packages` deletes the user's store copy, drops it from
    defaults, and pip-uninstalls its Python libraries from the interpreter
    Curio runs on. None of that was disclosed.
    """
    require_project_page()
    require_user_auth()
    _enter(page, app_frontend.base_url, current_server, "confirm_pkg_remove")

    drawer = _open_node_drawer(page)
    drawer.get_by_role("button", name=re.compile(r"^In project")).click()
    row = drawer.locator("[data-pkg-dir]").first
    if not row.count():
        # Nothing installed beyond the builtin, which is not removable; the
        # dialog's copy is still pinned by the source guard in
        # `noRepeatedChrome.test.ts`. Skip rather than assert on an empty tab.
        return

    remove = row.get_by_role("button", name=re.compile(r"^Remove")).first
    if not remove.count():
        return
    remove.click()

    modal = _modal(page, re.compile(r"^Remove "))
    # THE POINT: the second paragraph, which did not exist.
    expect(modal).to_contain_text("deleted from your account")
    expect(modal).to_contain_text("shared environment")
    save_workflow_test_screenshot(
        page, "node-remove-confirm",
        test_name="test_removing_a_package_says_it_reaches_the_shared_environment",
        fit_reactflow=False,
    )
    modal.get_by_role("button", name="Cancel", exact=True).click()
    expect(modal).to_have_count(0, timeout=10000)


def test_publishing_is_not_a_canvas_drawer_action(
    app_frontend: "FrontendPage", current_server: str, page
):
    """The canvas drawer offers no Publish at all - not even for your own data.

    It used to, and this test used to prove it there. ``29a4e902`` moved
    publishing onto the Data Catalog PAGE's detail drawer, on the reasoning that
    publishing is an account-level decision about an item rather than a decision
    about whichever dataflow you happen to have open. ``DatasetCard`` and
    ``DatasetDetailPanel`` both say so in comments, and ``InstalledDatasetsList``
    - which carried the pill - is now dead code.

    So the claim splits in two. This half pins the absence, which is the part
    that changed; the test below pins the presence, on the surface that owns it.
    """
    require_project_page()
    require_user_auth()
    _enter(page, app_frontend.base_url, current_server, "confirm_no_canvas_publish")

    # 1. A catalog dataset offers no Publish.
    drawer = _open_data_drawer(page)
    catalog_card = drawer.locator('article[data-dataset-id^="data."]').first
    catalog_card.wait_for(state="visible", timeout=30000)
    expect(
        catalog_card.get_by_role("button", name=re.compile(r"^Publish"))
    ).to_have_count(0)

    drawer.locator("header").get_by_role(
        "button", name="Close Data Catalog drawer"
    ).click()
    expect(page.locator(DATA_DRAWER)).to_have_count(0, timeout=10000)

    # 2. Produce a dataset of the user's own: run a node that outputs a frame.
    loading = drag_to_canvas(page, page.locator(LOADING_TILE), at=(220, 200))
    set_node_code(page, loading, OWN_DATASET_CODE)
    run_node_and_wait(page, loading, node_type=LOADING_TYPE)

    # 3. THE POINT: not even that one offers Publish here. Name the computed row
    #    explicitly - a first-card check would pass for the wrong reason - and
    #    then sweep the whole drawer, since the pill could have moved rather
    #    than gone.
    drawer = _open_data_drawer(page)
    drawer.get_by_role("button", name=re.compile(r"^Computed")).first.click()
    own = drawer.locator('article[data-dataset-id^="computed."]').first
    own.wait_for(state="visible", timeout=60000)
    expect(
        own.get_by_role("button", name=re.compile(r"^Publish"))
    ).to_have_count(0, timeout=30000)
    expect(
        drawer.get_by_role("button", name=re.compile(r"^(Publish|Unpublish)"))
    ).to_have_count(0)

    save_workflow_test_screenshot(
        page, "no-publish-in-the-canvas-drawer",
        test_name="test_publishing_is_not_a_canvas_drawer_action",
        fit_reactflow=False,
    )


def test_publish_is_offered_only_for_the_users_own_data_and_asks_first(
    app_frontend: "FrontendPage", current_server: str, page
):
    """Publish is for what the user made or brought, not for what shipped.

    Everything in a default installation came FROM the shared catalog, so
    republishing it writes a duplicate - and the backend has no guard, so the
    affordance is the guard. ``isUserOwnedDataset`` is what decides, and the Data
    Catalog page's detail drawer is the only surface that renders the control.
    """
    require_project_page()
    require_user_auth()
    _enter(page, app_frontend.base_url, current_server, "confirm_publish")

    # Something of the user's own, so there is a Publish to find.
    loading = drag_to_canvas(page, page.locator(LOADING_TILE), at=(220, 200))
    set_node_code(page, loading, OWN_DATASET_CODE)
    run_node_and_wait(page, loading, node_type=LOADING_TYPE)

    page.goto(f"{app_frontend.base_url}/catalog/data")
    page.wait_for_load_state("domcontentloaded")
    drawer = page.locator(BROWSE_DRAWER)

    # 1. A catalog dataset: no Publish in its details. Explicitly a ``data.`` row,
    #    because the page lists the user's own alongside it and those SHOULD
    #    offer it - a first-card assertion would fail for the right reason and
    #    look like the bug.
    catalog_card = page.locator('article[data-dataset-id^="data."]').first
    catalog_card.wait_for(state="visible", timeout=60000)
    catalog_card.click()
    drawer.wait_for(state="visible", timeout=30000)
    expect(
        drawer.get_by_role("button", name=re.compile(r"^Publish"))
    ).to_have_count(0, timeout=30000)

    # 2. THE POINT: the user's own does offer it.
    own_card = page.locator('article[data-dataset-id^="computed."]').first
    own_card.wait_for(state="visible", timeout=60000)
    own_card.scroll_into_view_if_needed()
    own_card.click()
    publish = drawer.get_by_role("button", name=re.compile(r"^Publish"))
    expect(publish).to_have_count(1, timeout=30000)

    save_workflow_test_screenshot(
        page, "publish-offered-for-own-dataset",
        test_name="test_publish_is_offered_only_for_the_users_own_data_and_asks_first",
        fit_reactflow=False,
    )

    # 3. And publishing asks first - it is the only deployment-wide write.
    publish.click()
    modal = _modal(page, re.compile(r"^Publish "))
    expect(modal).to_contain_text("Everyone using this Curio")
    modal.get_by_role("button", name="Cancel", exact=True).click()
    expect(modal).to_have_count(0, timeout=10000)
    # Cancelling published nothing, so the action is still on offer.
    expect(
        drawer.get_by_role("button", name=re.compile(r"^Publish"))
    ).to_have_count(1, timeout=10000)


def test_uploading_a_file_then_deleting_it_warns_about_every_dataflow(
    app_frontend: "FrontendPage", current_server: str, page, tmp_path
):
    """An uploaded file can be deleted on purpose, and says what that reaches.

    It used to have no Delete at all. The only way to be rid of an upload was to
    remove it from the last dataflow using it, at which point the backend
    deleted the account copy as a side effect of an action called "Remove from
    dataflow" - a deletion the user never asked for by name.

    So: upload one, delete it, and check the dialog is honest about the scope.
    Delete removes the dataset AND strips its references from every dataflow
    that holds one, archived projects included (``delete_dataset`` step 2).
    """
    require_project_page()
    require_user_auth()
    _enter(page, app_frontend.base_url, current_server, "confirm_upload_delete")

    source = tmp_path / "my-observations.csv"
    source.write_text("station,reading\nalpha,1\nbeta,2\n", encoding="utf-8")

    drawer = _open_data_drawer(page)
    import_button = drawer.get_by_role("button", name="Import dataset")
    expect(import_button).to_be_visible(timeout=30000)

    with page.expect_response(
        lambda r: r.url.endswith("/api/datasets/import")
        and r.request.method == "POST"
        and r.ok,
        timeout=120000,
    ) as imported:
        with page.expect_file_chooser() as chooser:
            import_button.click()
        chooser.value.set_files(str(source))
    dataset_id = imported.value.json()["id"]

    card = drawer.locator(f'article[data-dataset-id="{dataset_id}"]')
    expect(card).to_have_count(1, timeout=30000)

    # THE POINT, part one: an upload now offers Delete. It carries no producer
    # node, which is exactly why it used to fall outside the affordance.
    delete = card.get_by_role("button", name="Delete", exact=True)
    expect(delete).to_be_visible(timeout=20000)

    # No Publish beside it: that action left the canvas drawer entirely, for
    # every dataset including the user's own. See
    # ``test_publishing_is_not_a_canvas_drawer_action``.
    expect(card.get_by_role("button", name=re.compile(r"^Publish"))).to_have_count(0)

    # THE POINT, part two: the dialog states the every-dataflow scope.
    delete.click()
    modal = _modal(page, re.compile(r"^Delete "))
    expect(modal).to_contain_text("every dataflow that uses it")
    expect(modal).to_contain_text("not just this one")
    save_workflow_test_screenshot(
        page, "upload-delete-confirm",
        test_name="test_uploading_a_file_then_deleting_it_warns_about_every_dataflow",
        fit_reactflow=False,
    )

    # Cancelling leaves it alone.
    modal.get_by_role("button", name="Cancel", exact=True).click()
    expect(modal).to_have_count(0, timeout=10000)
    expect(
        drawer.locator(f'article[data-dataset-id="{dataset_id}"]')
    ).to_have_count(1, timeout=10000)

    # Confirming really deletes it, and the card goes.
    drawer.locator(f'article[data-dataset-id="{dataset_id}"]').get_by_role(
        "button", name="Delete", exact=True
    ).click()
    with page.expect_response(
        lambda r: "/api/datasets/" in r.url and r.request.method == "DELETE",
        timeout=60000,
    ):
        _modal(page, re.compile(r"^Delete ")).get_by_role(
            "button", name="Delete forever", exact=True
        ).click()

    expect(
        drawer.locator(f'article[data-dataset-id="{dataset_id}"]')
    ).to_have_count(0, timeout=30000)


def _button_fill(locator) -> str:
    return locator.evaluate("el => getComputedStyle(el).backgroundColor")


def test_the_catalog_pages_use_one_button_vocabulary(
    app_frontend: "FrontendPage", current_server: str, page
):
    """Black is an action, white is destructive, on the browse pages too.

    Publish used to be a small blue pill in its own size and colour, on every
    surface, which read as a status chip rather than as a button. The rule has
    to hold on `/catalog/*` as well as in the drawers, because those are the
    same cards with the same actions.
    """
    require_project_page()
    require_user_auth()
    _enter(page, app_frontend.base_url, current_server, "catalog_button_vocab")

    # Produce something of the user's own, so a Publish action exists to look at.
    loading = drag_to_canvas(page, page.locator(LOADING_TILE), at=(220, 200))
    set_node_code(page, loading, OWN_DATASET_CODE)
    run_node_and_wait(page, loading, node_type=LOADING_TYPE)

    page.goto(f"{app_frontend.base_url}/catalog/data")
    page.wait_for_load_state("domcontentloaded")
    card = page.locator('article[data-dataset-id^="computed."]').first
    card.wait_for(state="visible", timeout=60000)
    card.scroll_into_view_if_needed()

    # Publishing is not a card action on any surface any more, so the button to
    # inspect is in the detail drawer the card opens. The vocabulary rule is what
    # is under test, not the location - but the rule can only be read where the
    # button actually renders.
    card.click()
    drawer = page.locator(BROWSE_DRAWER)
    drawer.wait_for(state="visible", timeout=30000)
    publish = drawer.get_by_role("button", name=re.compile(r"^Publish"))
    expect(publish).to_have_count(1, timeout=30000)

    # The action fill, not a blue pill of its own. `--curio-top-bar-bg` is the
    # same token `.btnInstall` uses for "Add to project".
    fill = _button_fill(publish.first)
    assert fill not in ("rgba(0, 0, 0, 0)", "transparent"), (
        f"Publish renders unfilled ({fill}); it should carry the action fill"
    )
    channels = [int(n) for n in re.findall(r"\d+", fill)[:3]]
    assert channels and max(channels) < 90, (
        f"Publish is not the dark action fill: {fill}. Black is an action, "
        f"white with a border is destructive, and Publish is an action."
    )

    save_workflow_test_screenshot(
        page, "catalog-page-button-vocabulary",
        test_name="test_the_catalog_pages_use_one_button_vocabulary",
        fit_reactflow=False,
    )
