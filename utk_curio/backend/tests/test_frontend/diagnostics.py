"""What a failing e2e test leaves behind: screenshot, node states, browser log, trace.

A test that timed out used to leave nothing but the timeout message. The
Allure report for a #248 failure (06-autark-what-if-shadow-study, where a Data
Pool never showed its table) had no screenshot, no console output and no
record of which node was stuck. ``conftest.py`` now calls :func:`finish` after
every test, and on failure this writes, per test, into
``$CURIO_E2E_FAILURE_DIR/<test id>/``:

- ``screenshot.png``   the whole page at the moment of failure
- ``nodes.txt``        every canvas node's id, ``data-curio-node-status``,
                      its ``data-curio-node-error`` when it failed, and
                       visible text, which is what shows *which* node was
                       stuck and what it displayed
- ``browser-log.txt``  console and pageerror events, when the page captured
                       them (``workflow_page`` does)
- ``trace.zip``        a Playwright trace of the test, with ``CURIO_E2E_TRACE``
                       set. ``1`` records DOM snapshots and the action log,
                       which is cheap enough to leave on in CI; ``full`` adds a
                       screenshot per action, for the manual repro job

Each file is also attached to the Allure report. Everything here is best
effort: a diagnostic that fails must never replace the test's own failure.
"""

import os
import re

try:
    import allure
except ImportError:  # pragma: no cover - the harness can run without it
    allure = None

TRACE_ENV = "CURIO_E2E_TRACE"
DIR_ENV = "CURIO_E2E_FAILURE_DIR"

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), *[os.pardir] * 4))
DEFAULT_DIR = os.path.join(_REPO_ROOT, ".curio", "playwright", "failures")

# Fixtures that hold a page, in the order to prefer them.
_PAGE_FIXTURES = ("workflow_page", "page")

_NODE_STATES_JS = """() => [...document.querySelectorAll('.react-flow__node')].map(el => {
    const status = el.querySelector('[data-curio-node-status]');
    return {
        id: el.getAttribute('data-id'),
        type: [...el.classList].find(c => c.startsWith('react-flow__node-')) || '',
        status: status ? status.getAttribute('data-curio-node-status') : null,
        error: status ? status.getAttribute('data-curio-node-error') : null,
        text: (el.innerText || '').replace(/\\s+/g, ' ').trim().slice(0, 800),
    };
})"""


def tracing_enabled(environ=os.environ):
    return (environ.get(TRACE_ENV) or "").strip().lower() in ("1", "full")


def tracing_screenshots(environ=os.environ):
    """Per-action screenshots: the expensive half of a trace, so ``full`` only."""
    return (environ.get(TRACE_ENV) or "").strip().lower() == "full"


def failure_dir(nodeid, environ=os.environ):
    """Where one test's evidence goes: its id, made safe for a file name."""
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", nodeid).strip("_")[:180]
    return os.path.join(environ.get(DIR_ENV) or DEFAULT_DIR, safe)


def start_tracing(context):
    """Record a trace on *context*; each test cuts its own chunk from it."""
    if not tracing_enabled():
        return
    try:
        context.tracing.start(screenshots=tracing_screenshots(), snapshots=True)
        context._curio_tracing = True
    except Exception as exc:
        print(f"[e2e-diagnostics] could not start tracing: {exc}")


def stop_tracing(context):
    if getattr(context, "_curio_tracing", False):
        context._curio_tracing = False
        try:
            context.tracing.stop()
        except Exception:
            pass


def page_for(item):
    """The live Playwright page this test used, if any."""
    funcargs = getattr(item, "funcargs", None) or {}
    for name in _PAGE_FIXTURES:
        page = funcargs.get(name)
        try:
            if page is not None and not page.is_closed():
                return page
        except Exception:
            continue
    return None


def start_trace_chunk(item):
    """Begin this test's trace chunk, when its page is being traced."""
    page = page_for(item)
    context = getattr(page, "context", None)
    if context is None or not getattr(context, "_curio_tracing", False):
        return
    try:
        context.tracing.start_chunk(title=item.nodeid)
        item._curio_trace_chunk = context
    except Exception as exc:
        print(f"[e2e-diagnostics] could not start a trace chunk: {exc}")


def finish(item, *, failed):
    """Close the test's trace chunk; on failure, record what the page showed.

    Returns the paths written, which is nothing for a passing test.
    """
    out_dir = failure_dir(item.nodeid)
    written = []

    context = getattr(item, "_curio_trace_chunk", None)
    if context is not None:
        item._curio_trace_chunk = None
        path = os.path.join(out_dir, "trace.zip") if failed else None
        try:
            if path:
                os.makedirs(out_dir, exist_ok=True)
            context.tracing.stop_chunk(path=path)  # no path: discarded
            if path:
                written.append(path)
        except Exception as exc:
            print(f"[e2e-diagnostics] could not save the trace: {exc}")

    if failed:
        page = page_for(item)
        if page is not None:
            written = capture(page, out_dir, title=item.nodeid) + written

    for path in written:
        _attach(path)
    if written:
        print(f"\n[e2e-diagnostics] {item.nodeid}: "
              f"{', '.join(os.path.basename(p) for p in written)} in {out_dir}")
    return written


def capture(page, out_dir, *, title=""):
    """Write the screenshot, node states and browser log for *page*."""
    os.makedirs(out_dir, exist_ok=True)
    written = []

    path = os.path.join(out_dir, "screenshot.png")
    responsive = True
    try:
        page.screenshot(path=path, full_page=True, timeout=15000)
        written.append(path)
    except Exception as exc:
        # A page that cannot take a screenshot in 15s is hung, and evaluate()
        # has no timeout of its own, so asking it for node states could hang
        # the whole run.
        responsive = type(exc).__name__ != "TimeoutError"
        _note(out_dir, f"screenshot failed: {exc}")

    if responsive:
        try:
            nodes = page.evaluate(_NODE_STATES_JS)
        except Exception as exc:
            nodes = None
            _note(out_dir, f"reading node states failed: {exc}")
        if nodes:
            path = os.path.join(out_dir, "nodes.txt")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(format_nodes(nodes, url=_url(page), title=title))
            written.append(path)
    else:
        _note(out_dir, "skipped reading node states: the page did not respond")

    entries = getattr(page, "_curio_browser_log", None)
    if entries:
        path = os.path.join(out_dir, "browser-log.txt")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(format_browser_log(entries))
        written.append(path)
    return written


def format_nodes(nodes, *, url="", title=""):
    lines = [f"# {title}", f"# {url}", f"# {len(nodes)} canvas nodes", ""]
    for node in nodes:
        lines.append(f"{node.get('id') or '?'}  status={node.get('status') or '-'}  "
                     f"{node.get('type') or ''}")
        # An Autark node shows its failure nowhere on screen, so the attribute
        # is the only account of it in this dump (#318).
        if node.get("error"):
            lines.append(f"    error: {node['error']}")
        lines.append(f"    {node.get('text') or '(no visible text)'}")
    return "\n".join(lines) + "\n"


def format_browser_log(entries):
    lines = [f"# {len(entries)} console/pageerror events, oldest first", ""]
    for entry in entries:
        if entry.get("kind") == "pageerror":
            lines.append(f"[pageerror] {entry.get('message', '')}")
        else:
            location = entry.get("location") or {}
            lines.append(f"[{entry.get('type', 'log')}] {entry.get('text', '')}"
                         f"  ({location.get('url', '')}:{location.get('lineNumber', '')})")
    return "\n".join(lines) + "\n"


def _url(page):
    try:
        return page.url
    except Exception:
        return ""


def _note(out_dir, message):
    with open(os.path.join(out_dir, "diagnostics-errors.txt"), "a",
              encoding="utf-8") as handle:
        handle.write(message + "\n")


def _attach(path):
    if allure is None:
        return
    name = os.path.basename(path)
    kind = {
        ".png": allure.attachment_type.PNG,
        ".txt": allure.attachment_type.TEXT,
    }.get(os.path.splitext(name)[1])
    try:
        if kind is None:
            allure.attach.file(path, name=name, extension=name.rsplit(".", 1)[-1])
        else:
            allure.attach.file(path, name=name, attachment_type=kind)
    except Exception:
        pass
