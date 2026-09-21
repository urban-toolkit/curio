"""TEMPORARY debug probe. Not part of the suite; deleted before the PR."""
from __future__ import annotations

import json
import uuid

from .test_dashboard_page_e2e import _spec, CHART, POOL, PRODUCER
from .utils import (
    dismiss_toasts,
    node_locator,
    play_node,
    require_owner_view,
    stub_login_and_enter_workflow,
)


def _statuses(page):
    return page.evaluate(
        """() => (window.__curio_reactFlow?.getNodes() || []).map((n) => {
            const el = document.querySelector(
                `.react-flow__node[data-id="${n.id}"] [data-curio-node-status]`);
            return {
                id: n.id,
                status: el ? el.getAttribute('data-curio-node-status') : null,
                error: el ? el.getAttribute('data-curio-node-error') : null,
                outputCode: n.data?.output?.code ?? null,
                outputContent: String(n.data?.output?.content ?? '').slice(0, 300),
                input: JSON.stringify(n.data?.input ?? '').slice(0, 160),
                codeLen: (n.data?.code ?? '').length,
                defaultCodeLen: (n.data?.defaultCode ?? '').length,
                codeHead: String(n.data?.code ?? '').slice(0, 50),
            };
        })"""
    )


def test_debug_chain(app_frontend, current_server, page):
    logs = []
    page.on("console", lambda m: logs.append(f"{m.type}: {m.text[:300]}"))
    page.on("pageerror", lambda e: logs.append(f"pageerror: {e}"))

    stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Debug",
        username=f"dbg_{uuid.uuid4().hex[:8]}",
        project_name="Debug dashboard",
        project_spec=_spec(),
    )
    require_owner_view(page)
    page.wait_for_selector(".react-flow__node", timeout=45000)
    dismiss_toasts(page)

    print("\n--- before play ---")
    print(json.dumps(_statuses(page), indent=1))

    node_locator(page, CHART).wait_for(state="visible", timeout=45000)
    play_node(page, CHART)

    for i in range(12):
        page.wait_for_timeout(5000)
        st = _statuses(page)
        print(f"--- t+{(i + 1) * 5}s ---")
        print(json.dumps(st, indent=1))
        if all(n["status"] in ("done", "error") for n in st):
            break

    print("--- console ---")
    for line in logs[-60:]:
        print(line)


def test_debug_visitor(app_frontend, current_server, page, browser):
    """What a cookie-less visitor actually sees on a dashboard link."""
    import json as _json
    stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Debug Owner",
        username=f"dbgv_{uuid.uuid4().hex[:8]}",
        project_name="Debug visitor",
        project_spec=_spec(),
    )
    require_owner_view(page)
    page.wait_for_selector(".react-flow__node", timeout=45000)
    dismiss_toasts(page)
    play_node(page, CHART)
    page.wait_for_timeout(20000)
    # pin + save
    node = node_locator(page, CHART)
    from .utils import activate_header_icon
    activate_header_icon(node.locator('[title="Pin to dashboard"]').first)
    page.wait_for_timeout(1000)
    page.locator("[data-curio-save-state]").first.click(force=True)
    page.wait_for_function(
        "() => document.querySelector('[data-curio-save-state]')"
        "?.getAttribute('data-curio-save-state') === 'saved'",
        timeout=30000,
    )
    import re as _re
    project_id = _re.search(r"/dataflow/([0-9a-f-]{36})", page.url).group(1)

    ctx = browser.new_context()
    visitor = ctx.new_page()
    logs = []
    visitor.on("console", lambda m: logs.append(f"{m.type}: {m.text[:200]}"))
    visitor.on("pageerror", lambda e: logs.append(f"pageerror: {e}"))
    visitor.goto(f"{app_frontend.base_url}/dashboard/{project_id}")
    visitor.wait_for_timeout(12000)
    print("\n--- visitor url:", visitor.url)
    print("--- body text (first 600):")
    print((visitor.locator("body").inner_text() or "")[:600])
    print("--- testids present:", visitor.evaluate(
        "() => [...document.querySelectorAll('[data-testid]')].map(e => e.dataset.testid)"))
    print("--- nodes:", visitor.evaluate(
        "() => (window.__curio_reactFlow?.getNodes() || []).length"))
    print("--- console:")
    for line in logs[-40:]:
        print(line)
    ctx.close()
