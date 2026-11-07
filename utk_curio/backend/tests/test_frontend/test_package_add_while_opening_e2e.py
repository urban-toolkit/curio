"""Playwright E2E: the package added while its dataflow opens is the one confirmed.

An Add in the Node Catalog drawer made while the dataflow is still opening
shows its review only once the open is in (#340), up to 15 s later
(``PROJECT_LOAD_WAIT_MS``). On main's run 42323207500 the dataflow's load took
7 s. The helper that adds ``test.ui-node@1`` (``_install_from_the_node_catalog``)
clicked the UI Node card's Add, then the Add button of the last dialog on the
page, which was the drawer itself: its last card's Add, Urban Heat
Vulnerability Index. When the load came, both reviews opened, the second over
the first, and nothing confirmed the UI Node.

This holds the dataflow's load in the page until 3 s after the first Add, so
the helper's every click comes while the dataflow opens, then lets the helper
add the UI Node.

Run::

    CURIO_E2E_USE_EXISTING=1 pytest \\
        utk_curio/backend/tests/test_frontend/test_package_add_while_opening_e2e.py -v
"""
from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from .test_package_refresh_e2e import _install_from_the_node_catalog
from .utils import (
    require_owner_view,
    require_project_page,
    require_user_auth,
    stub_login_and_enter_workflow,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

#: Holds the page's GET of its dataflow (``/api/projects/<id>?results=last``)
#: until 3 s after the first click on a card's "Add to project" (at most a
#: minute), and records whether that click came while the load was held.
_HOLD_THE_LOAD_PAST_AN_ADD = r"""(() => {
    const hold = { held: false, released: false, addedAt: null, addedWhileHeld: false };
    window.__curioLoadHold = hold;
    document.addEventListener('click', (event) => {
        const button = event.target instanceof Element ? event.target.closest('button') : null;
        if (!button || hold.addedAt !== null) return;
        if (!/^Add to project/.test((button.textContent || '').trim())) return;
        hold.addedAt = performance.now();
        hold.addedWhileHeld = hold.held && !hold.released;
    }, true);
    const fetchOf = window.fetch.bind(window);
    window.fetch = (input, init) => {
        const url = typeof input === 'string' ? input : (input && input.url) || '';
        const method = ((init && init.method) || (input && input.method) || 'GET').toUpperCase();
        if (method !== 'GET' || hold.released || !/\/api\/projects\/[^/?]+\?results=last/.test(url)) {
            return fetchOf(input, init);
        }
        hold.held = true;
        const started = performance.now();
        return new Promise((resolve) => {
            const tick = () => {
                const now = performance.now();
                if ((hold.addedAt !== null && now - hold.addedAt >= 3000) || now - started >= 60000) {
                    hold.released = true;
                    resolve(fetchOf(input, init));
                } else {
                    setTimeout(tick, 100);
                }
            };
            tick();
        });
    };
})();"""


def test_the_package_added_while_its_dataflow_opens_is_the_one_confirmed(
    app_frontend: "FrontendPage", current_server: str, page, ui_node_in_catalog,
):
    require_project_page()
    require_user_auth()
    page.emulate_media(reduced_motion="reduce")
    page.add_init_script(_HOLD_THE_LOAD_PAST_AN_ADD)
    stub_login_and_enter_workflow(
        page, frontend_url=app_frontend.base_url, backend_url=current_server,
        name="Early Add", username=f"early_add_{uuid.uuid4().hex[:8]}",
        project_name="Add while it opens",
    )
    require_owner_view(page)
    page.locator("#tools-menu").wait_for(state="visible", timeout=45000)

    _install_from_the_node_catalog(page)

    hold = page.evaluate("() => window.__curioLoadHold")
    assert hold["addedWhileHeld"], f"the Add came only after the dataflow's load: {hold}"
