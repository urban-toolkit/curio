import os
import re
import json
import time
# import zlib
import shutil
import textwrap
from pathlib import Path
from io import BytesIO
from urllib.request import urlopen, Request
from urllib.error import URLError

import allure
import pytest
from playwright.sync_api import Error as PlaywrightError, Page, expect

# Repo root is 4 levels up: test_frontend -> tests -> backend -> utk_curio -> curio-main
REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "..")
)

# PNGs from workflow E2E tests: ``screenshot_{workflow_stem}_{test_name}.png``
WORKFLOW_SCREENSHOT_EXPECTED_DIR = os.path.join(
    REPO_ROOT, "docs", "examples", "dataflows", "expected_outputs"
)



def get_shared_data_dir() -> str:
    """Directory where Curio writes its DuckDB artifact store.

    Matches ``utk_curio/sandbox/util/db.py`` (``CURIO_LAUNCH_CWD`` +
    ``CURIO_SHARED_DATA``). Defaults ``CURIO_LAUNCH_CWD`` to the repo root
    so host-side Playwright resolves the same path as ``curio start`` when the
    subprocess uses ``cwd`` = repo root (and matches Docker once ``./.curio`` is
    bind-mounted to ``/app/.curio``).

    The directory holds ``curio_data.duckdb``;
    """
    launch_dir = Path(
        os.environ.get("CURIO_LAUNCH_CWD", REPO_ROOT)
    ).resolve()
    shared_disk_path = os.environ.get("CURIO_SHARED_DATA", "./.curio/data/")
    lod_dir = (launch_dir / Path(shared_disk_path)).resolve()
    return str(lod_dir)


# ---------------------------------------------------------------------------
# .data file helpers (zlib-compressed JSON, same format as parsers.py)
# ---------------------------------------------------------------------------

# def load_dot_data(path: str) -> dict:
#     """Read a ``.data`` file (zlib-compressed JSON) and return the parsed dict."""
#     with open(path, "rb") as f:
#         return json.loads(zlib.decompress(f.read()).decode("utf-8"))


# def save_dot_data(path: str, data: dict) -> None:
#     """Write *data* as zlib-compressed JSON to *path*."""
#     os.makedirs(os.path.dirname(path), exist_ok=True)
#     compressed = zlib.compress(json.dumps(data, ensure_ascii=False).encode("utf-8"))
#     with open(path, "wb") as f:
#         f.write(compressed)


# def strip_volatile_keys(data: dict) -> dict:
#     """Return a shallow copy of *data* without per-run metadata (``filename``)."""
#     stripped = {**data}
#     stripped.pop("filename", None)
#     return stripped

# ---------------------------------------------------------------------------
# DuckDB artifact helpers
# ---------------------------------------------------------------------------

def load_artifact_as_dict(artifact_id: str) -> dict:
    """Fetch a stored artifact from the sandbox and return its parsed representation."""
    import requests as _req
    sandbox_host = os.environ.get('FLASK_SANDBOX_HOST', '127.0.0.1')
    sandbox_port = int(os.environ.get('FLASK_SANDBOX_PORT', '2000'))
    resp = _req.get(
        f'http://{sandbox_host}:{sandbox_port}/get',
        params={'fileName': artifact_id},
        timeout=30,
    )
    if not resp.ok:
        # Surface the sandbox's structured error body (added in api.py /get)
        # so pytest shows *why* the load failed.
        raise AssertionError(
            f"sandbox /get fileName={artifact_id} -> {resp.status_code}\n"
            f"{resp.text[:2000]}"
        )
    parsed = resp.json()
    result = json.loads(json.dumps(parsed, default=str))
    result.pop('filename', None)  # artifact ID varies per execution run
    return result


# ---------------------------------------------------------------------------
# Deterministic seeding for reproducible programmatic execution
# ---------------------------------------------------------------------------

_SEED_PREFIX = (
    "import numpy as _np; _np.random.seed({seed}); "
    "import random as _rnd; _rnd.seed({seed})\n"
)


def seed_node_code(code: str, seed: int = 42) -> str:
    """Prepend deterministic random-seed lines to *code*.

    Uses underscore-prefixed aliases (``_np``, ``_rnd``) so the seed
    imports never shadow the user's own ``import numpy as np``.
    """
    return _SEED_PREFIX.format(seed=seed) + code


_WIDGET_RE = re.compile(r"\[!!\s*(.*?)\s*!!\]")


def resolve_widget_placeholders(code: str) -> str:
    """Replace ``[!! name$type$default !!]`` widget markers with defaults.

    The frontend resolves these before sending code to the sandbox; the
    programmatic executor must do the same.
    """
    def _replace(m):
        parts = m.group(1).split("$")
        if len(parts) >= 3:
            return parts[2]
        return m.group(0)
    return _WIDGET_RE.sub(_replace, code)


PLAYWRIGHT_EXPECTED_DIR = os.path.join(
    REPO_ROOT, ".curio", "playwright", "expected"
)

_TRUE_VALUES = {"1", "true", "yes", "on"}
_FALSE_VALUES = {"0", "false", "no", "off"}


def env_flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in _TRUE_VALUES:
        return True
    if value in _FALSE_VALUES:
        return False
    return default


def _backend_base_url_for_config() -> str:
    """Resolve the backend URL for fetching ``/api/config/public``.

    When attaching to an already-running stack (``CURIO_E2E_USE_EXISTING=1``)
    or running the fixture-spawned subprocess, the backend's actual state
    is the single source of truth for the auth/guest/project flags — the
    pytest process env alone cannot reproduce it, because the ``curio start``
    subprocess overrides these vars from its CLI flags.
    """
    host = os.environ.get("CURIO_E2E_HOST", "localhost")
    port = os.environ.get("CURIO_E2E_BACKEND_PORT") or os.environ.get(
        "BACKEND_PORT", "5002"
    )
    return f"http://{host}:{port}"


_PUBLIC_CONFIG_CACHE: dict | None = None


def _fetch_public_config() -> dict | None:
    """Return the cached ``/api/config/public`` body, or ``None`` if offline.

    Result is memoised for the pytest session because a Curio backend does
    not change its auth flags at runtime (they're read from the process env
    at import time). Callers treat ``None`` as "backend unreachable, fall
    back to env inspection".
    """
    global _PUBLIC_CONFIG_CACHE
    if _PUBLIC_CONFIG_CACHE is not None:
        return _PUBLIC_CONFIG_CACHE
    url = f"{_backend_base_url_for_config()}/api/config/public"
    try:
        req = Request(url, method="GET")
        with urlopen(req, timeout=5) as resp:
            if resp.getcode() != 200:
                return None
            body = resp.read().decode("utf-8") or "{}"
            _PUBLIC_CONFIG_CACHE = json.loads(body)
            return _PUBLIC_CONFIG_CACHE
    except (URLError, OSError, ValueError):
        return None


def auth_enabled_env() -> bool:
    """True when the running backend has user auth enabled.

    Prefers the live backend's ``/api/config/public`` response so the pytest
    process never disagrees with the backend subprocess (whose ``CURIO_NO_AUTH``
    is set by ``curio.py start`` CLI flags, not inherited from pytest env).
    Falls back to env vars when the backend is not yet reachable (e.g. fixture
    setup phase before the port is bound).
    """
    cfg = _fetch_public_config()
    if cfg is not None:
        if cfg.get("curio_no_project") or cfg.get("skip_project_page"):
            return False
        return not bool(cfg.get("curio_no_auth"))
    if env_flag("CURIO_NO_PROJECT", False):
        return False
    return not env_flag("CURIO_NO_AUTH", False)


def allow_guest_login_env() -> bool:
    """True when guest login is enabled on the running backend.

    Like :func:`auth_enabled_env`, prefers the live ``/api/config/public``
    response and only falls back to pytest-process env vars when the backend
    is unreachable.
    """
    cfg = _fetch_public_config()
    if cfg is not None:
        return bool(cfg.get("allow_guest_login"))
    if "ALLOW_GUEST_LOGIN" in os.environ:
        return env_flag("ALLOW_GUEST_LOGIN", False)
    return os.environ.get("CURIO_ENV", "dev") != "prod"


def skip_project_page_env() -> bool:
    """True when the running backend hides the ``/projects`` page.

    Mirrors :func:`auth_enabled_env`: prefer the live backend's view (via
    ``/api/config/public``) over pytest-process env inspection, since the
    ``curio start`` subprocess sets ``CURIO_NO_PROJECT`` from its CLI flags
    and pytest does not inherit that.
    """
    cfg = _fetch_public_config()
    if cfg is not None:
        return bool(cfg.get("skip_project_page") or cfg.get("curio_no_project"))
    return env_flag("CURIO_NO_PROJECT", False)


def require_user_auth() -> None:
    if not auth_enabled_env():
        pytest.skip("This test requires CURIO_NO_AUTH=0")


def require_project_page() -> None:
    """Skip the current test when Curio is running in ``--no-project`` mode.

    Tests that drive the ``/projects`` list page or the per-user save/load
    File-menu entries should call this so they're skipped (rather than
    timing out on missing UI) when the backend reports
    ``curio_no_project=true``.
    """
    if skip_project_page_env():
        pytest.skip("This test requires CURIO_NO_PROJECT=0")


def require_no_project_mode() -> None:
    """Skip the current test unless Curio is running in ``--no-project`` mode.

    Inverse of :func:`require_project_page`: tests that specifically assert
    the no-project UI (e.g. that the File menu hides project-backed entries)
    only make sense when the backend reports ``curio_no_project=true``.
    """
    if not skip_project_page_env():
        pytest.skip("This test requires CURIO_NO_PROJECT=1")


# ---------------------------------------------------------------------------
# Vega-Lite SVG helpers
# ---------------------------------------------------------------------------

def dot_data_to_vega_values(data: dict) -> list[dict]:
    """Convert a ``.data`` dict to the row-oriented list that Vega expects.

    Mirrors the frontend ``parseDataframe`` / ``parseGeoDataframe`` functions
    in ``src/utils/parsing.ts``.

    The ``dataframe`` format can be either dict-of-dicts (``to_dict()``)
    or dict-of-lists (``to_dict(orient='list')``); both are handled.
    """
    dtype = data.get("dataType")
    raw = data.get("data", {})
    if dtype == "dataframe":
        columns = list(raw.keys())
        first_col = raw[columns[0]]
        if isinstance(first_col, dict):
            keys = list(first_col.keys())
        else:
            keys = list(range(len(first_col)))
        return [
            {col: raw[col][k] for col in columns}
            for k in keys
        ]
    elif dtype == "geodataframe":
        return [f["properties"] for f in raw.get("features", [])]
    return []


def save_expected_svg(dataflow_name: str, node_id: str, svg_content: str) -> str:
    """Save a programmatically generated expected SVG to
    ``.curio/playwright/expected/<dataflow_name>/<node_id>.svg``.

    Returns the absolute path of the saved file.
    """
    dest_dir = os.path.join(PLAYWRIGHT_EXPECTED_DIR, dataflow_name)
    os.makedirs(dest_dir, exist_ok=True)
    path = os.path.join(dest_dir, f"{node_id}.svg")
    with open(path, "w", encoding="utf-8") as f:
        f.write(svg_content)
    return path


def load_expected_svg(dataflow_name: str, node_id: str) -> str | None:
    """Load a previously saved expected SVG, or return ``None``."""
    path = os.path.join(PLAYWRIGHT_EXPECTED_DIR, dataflow_name, f"{node_id}.svg")
    if not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def compare_svg_structure(
    actual_svg: str,
    expected_svg: str,
) -> list[str]:
    """Structurally compare two Vega-rendered SVG strings.

    Returns an empty list when the two SVGs are structurally equivalent.

    The comparison walks the ``<g>`` element tree and checks that both
    SVGs share the same hierarchy of ``class``, ``role``, and
    ``aria-roledescription`` attributes at every level.
    """
    import xml.etree.ElementTree as ET

    SVG_NS = "http://www.w3.org/2000/svg"

    _STRUCTURAL_ATTRS = ("class", "role", "aria-roledescription")

    def _parse(svg_str: str, label: str):
        try:
            return ET.fromstring(svg_str), []
        except ET.ParseError as e:
            return None, [f"{label} SVG is not valid XML: {e}"]

    def _sig(el) -> str:
        """Structural signature of an element: tag + key attributes."""
        tag = el.tag.split("}")[-1] if "}" in el.tag else el.tag
        parts = [tag]
        for attr in _STRUCTURAL_ATTRS:
            val = el.get(attr)
            if val:
                parts.append(f"{attr}={val}")
        return "|".join(parts)

    def _g_children(el):
        """Return direct ``<g>`` children of *el*."""
        return [
            ch for ch in el
            if ch.tag == f"{{{SVG_NS}}}g" or ch.tag == "g"
        ]

    def _compare_g_tree(actual_el, expected_el, path: str, diffs: list):
        """Recursively compare ``<g>`` sub-trees by structural signature."""
        actual_gs = _g_children(actual_el)
        expected_gs = _g_children(expected_el)

        if len(actual_gs) != len(expected_gs):
            diffs.append(
                f"At {path}: <g> child count differs — "
                f"actual={len(actual_gs)}, expected={len(expected_gs)}"
            )
            return

        for i, (a_g, e_g) in enumerate(zip(actual_gs, expected_gs)):
            a_sig = _sig(a_g)
            e_sig = _sig(e_g)
            child_path = f"{path}/g[{i}]"
            if a_sig != e_sig:
                diffs.append(
                    f"At {child_path}: signature mismatch — "
                    f"actual=({a_sig}), expected=({e_sig})"
                )
            else:
                _compare_g_tree(a_g, e_g, child_path, diffs)

    diffs: list[str] = []

    actual_root, errs = _parse(actual_svg, "Actual")
    if errs:
        return errs
    expected_root, errs = _parse(expected_svg, "Expected")
    if errs:
        return errs

    _compare_g_tree(actual_root, expected_root, "svg", diffs)

    return diffs


def _ensure_parsers_env():
    """Ensure ``CURIO_LAUNCH_CWD`` and ``CURIO_SHARED_DATA`` are set.

    ``get_db_path`` in ``utk_curio/sandbox/util/db.py`` reads these to
    resolve the path to ``curio_data.duckdb``.  When the test process is
    *not* started via ``curio start`` (e.g. ``CURIO_E2E_USE_EXISTING`` in
    CI) these variables may be absent, so we default them here.
    """
    if "CURIO_LAUNCH_CWD" not in os.environ:
        os.environ["CURIO_LAUNCH_CWD"] = REPO_ROOT
    if "CURIO_SHARED_DATA" not in os.environ:
        os.environ["CURIO_SHARED_DATA"] = str(
            Path(os.path.join(REPO_ROOT, ".curio", "data")).resolve()
        )

"""
def execute_workflow_programmatically(spec, seed: int = 42) -> dict[str, str]:
    #Execute every code node in-process and return *{node_id: expected_path}*.

    # Mirrors the sandbox ``python_wrapper.txt`` flow — load upstream data,
    # call user code, serialise via ``parseOutput`` / ``save_memory_mapped_file``
    # — but runs entirely inside the test process.  Results are copied to
    # ``.curio/playwright/expected/<workflow>/`` for later comparison with the
    # browser-produced ``.data`` files.
    #
    _ensure_parsers_env()

    from utk_curio.sandbox.util.parsers import (
        parseInput,
        parseOutput,
        save_memory_mapped_file,
        load_memory_mapped_file,
        checkIOType,
    )

    outputs: dict[str, dict] = {}   # node_id → {"path": ..., "dataType": ...}
    expected: dict[str, str] = {}   # node_id → absolute path in expected dir

    dataflow_name = os.path.splitext(os.path.basename(spec.filepath))[0]
    dest_dir = os.path.join(PLAYWRIGHT_EXPECTED_DIR, dataflow_name)
    os.makedirs(dest_dir, exist_ok=True)

    # User code uses relative paths (e.g. "docs/examples/data/…") that are
    # resolved from the repo root — the same CWD the sandbox uses via
    # CURIO_LAUNCH_CWD.  Switch CWD for the duration of execution.
    original_cwd = os.getcwd()
    os.chdir(REPO_ROOT)
    try:
        for node in spec.topo_sorted_nodes():
            # Non-code nodes: propagate upstream output without execution
            if node.category != "code":
                upstreams = spec.upstream_nodes(node.id)
                if len(upstreams) == 1 and upstreams[0] in outputs:
                    outputs[node.id] = outputs[upstreams[0]]
                elif len(upstreams) > 1:
                    outputs[node.id] = {
                        "path": [outputs[uid] for uid in upstreams if uid in outputs],
                        "dataType": "outputs",
                    }
                continue

            # --- resolve input (mirrors python_wrapper.txt lines 30-49) ---
            upstreams = spec.upstream_nodes(node.id)
            if not upstreams:
                incoming = ""
            elif len(upstreams) == 1:
                up = outputs[upstreams[0]]
                if up.get("dataType") == "outputs":
                    incoming = []
                    for elem in up["path"]:
                        raw = load_memory_mapped_file(elem["path"])
                        incoming.append(parseInput(raw))
                else:
                    raw = load_memory_mapped_file(up["path"])
                    incoming = parseInput(raw)
            else:
                incoming = []
                for uid in upstreams:
                    raw = load_memory_mapped_file(outputs[uid]["path"])
                    incoming.append(parseInput(raw))

            # --- exec seeded user code ---
            resolved = resolve_widget_placeholders(node.content)
            seeded = seed_node_code(resolved, seed)

            # Provide the same top-level imports as python_wrapper.txt
            import warnings as _w; _w.filterwarnings("ignore")
            import rasterio, geopandas, pandas, mmap, hashlib, ast  # noqa: F811
            ns: dict = {
                "warnings": _w, "rasterio": rasterio,
                "gpd": geopandas, "geopandas": geopandas,
                "pd": pandas, "pandas": pandas,
                "json": json, "mmap": mmap, "zlib": zlib, "os": os,
                "time": time, "hashlib": hashlib, "ast": ast,
            }
            exec(
                "def userCode(arg):\n" + textwrap.indent(seeded, "    "),
                ns,
            )
            result = ns["userCode"](incoming)

            # --- serialise exactly like the sandbox ---
            parsed = parseOutput(result)
            checkIOType(parsed, node.type, False)
            rel_path = save_memory_mapped_file(parsed)

            outputs[node.id] = {"path": rel_path, "dataType": parsed["dataType"]}

            gt_path = os.path.join(dest_dir, f"{dataflow_name}_{node.id}.data")
            shutil.copy2(
                os.path.join(get_shared_data_dir(), rel_path),
                gt_path,
            )
            expected[node.id] = gt_path
    finally:
        os.chdir(original_cwd)

    return expected
"""

def execute_workflow_programmatically(spec, seed: int = 42) -> dict[str, str]:
    """Execute every code node via the sandbox HTTP API and return {node_id: artifact_id}.

    Routes all execution through the sandbox's /exec endpoint so the sandbox's
    persistent DuckDB connection remains the sole writer throughout the test.
    The returned artifact IDs are used by Playwright tests to compare
    sandbox-produced outputs with browser-produced ones.
    """
    import requests as _req

    sandbox_host = os.environ.get('FLASK_SANDBOX_HOST', '127.0.0.1')
    sandbox_port = int(os.environ.get('FLASK_SANDBOX_PORT', '2000'))
    sandbox_url = f'http://{sandbox_host}:{sandbox_port}'

    from .workflow_spec import JS_CODE_TYPES

    outputs: dict[str, dict] = {}   # node_id → {"path": artifact_id, "dataType": ...}
    expected: dict[str, str] = {}   # node_id → duckdb artifact id

    for node in spec.topo_sorted_nodes():
        # Non-code nodes — and JS-code nodes whose source the Python sandbox
        # cannot parse — propagate upstream output without execution.
        if node.category != "code" or node.type in JS_CODE_TYPES:
            upstreams = spec.upstream_nodes(node.id)
            if len(upstreams) == 1 and upstreams[0] in outputs:
                outputs[node.id] = outputs[upstreams[0]]
            elif len(upstreams) > 1:
                outputs[node.id] = {
                    "path": [outputs[uid] for uid in upstreams if uid in outputs],
                    "dataType": "outputs",
                }
            continue

        # Resolve input (mirrors process_python_code in backend routes.py)
        upstreams = spec.upstream_nodes(node.id)
        if not upstreams:
            file_path = ""
            data_type = ""
        elif len(upstreams) == 1:
            up = outputs[upstreams[0]]
            if up.get("dataType") == "outputs":
                # Pass as stringified list; worker.py eval()s it back
                file_path = str(up["path"])
                data_type = "outputs"
            else:
                file_path = up["path"]
                data_type = up["dataType"]
        else:
            file_path = str([outputs[uid] for uid in upstreams])
            data_type = "outputs"

        # Sandbox /exec expects code already indented as a function body
        resolved = resolve_widget_placeholders(node.content)
        seeded = seed_node_code(resolved, seed)
        indented_code = textwrap.indent(seeded, "    ")

        resp = _req.post(
            f'{sandbox_url}/exec',
            json={
                "code": indented_code,
                "file_path": file_path,
                "nodeType": node.type,
                "dataType": data_type,
            },
            timeout=120,
        )
        resp.raise_for_status()
        result = resp.json()

        if result.get('stderr'):
            raise RuntimeError(
                f"Node {node.id} ({node.type}) failed:\n{result['stderr']}"
            )

        out = result['output']
        outputs[node.id] = {"path": out['path'], "dataType": out['dataType']}
        expected[node.id] = out['path']

    return expected


def _wait_for_reactflow_ready(
    page: Page,
    *,
    padding: float = 0.2,
    stable_frames: int = 3,
    timeout_ms: int = 10000,
) -> None:
    """Force ReactFlow into a deterministic viewport before screenshotting.

    Without this, ``save_workflow_test_screenshot`` races the app-side
    ``fitView`` call in ``useWorkflowOperations`` (which runs on a
    ``setTimeout`` after the workflow is uploaded). The screenshot can
    fire before the transform has been applied, producing a pre-fit
    canvas where nodes overflow the viewport.

    Strategy:

    1. Wait until at least one ``.react-flow__node`` is on the page.
    2. Call ``fitView({ padding, duration: 0 })`` on the instance
       exposed at ``window.__curio_reactFlow`` (see ``MainCanvas.tsx``).
       ``duration: 0`` skips the ReactFlow animation so the transform
       is applied synchronously.
    3. Poll the ``.react-flow__viewport`` ``transform`` attribute until
       it has stayed identical for ``stable_frames`` consecutive reads
       (guards against Monaco's layout settling and any late
       node-size measurements from ReactFlow).
    """
    page.wait_for_function(
        "() => document.querySelectorAll('.react-flow__node').length > 0",
        timeout=timeout_ms,
    )

    page.evaluate(
        """(padding) => {
            const rf = window.__curio_reactFlow;
            if (rf && typeof rf.fitView === 'function') {
                //rf.setViewport({ x: 0, y: 0, zoom: 0.35 }, { duration: 0 })
                rf.fitView({ padding, duration: 0, includeHiddenNodes: true });
            }
        }""",
        padding,
    )

    page.wait_for_function(
        """(stable_frames) => {
            const vp = document.querySelector('.react-flow__viewport');
            if (!vp) return false;
            const current = vp.style.transform || '';
            if (!current) return false;
            window.__curio_vp_samples = window.__curio_vp_samples || [];
            const samples = window.__curio_vp_samples;
            samples.push(current);
            if (samples.length > stable_frames) samples.shift();
            if (samples.length < stable_frames) return false;
            return samples.every((s) => s === samples[0]);
        }""",
        arg=stable_frames,
        timeout=timeout_ms,
    )

    page.evaluate("delete window.__curio_vp_samples")


def _capture_full_page(page: Page):
    """Return a Pillow RGB image of the full scrollable page.

    Scrolls to top-left first so the capture is deterministic, then uses
    Playwright's ``full_page=True`` to grab everything.
    """
    from PIL import Image

    page.evaluate("window.scrollTo(0, 0)")
    raw = page.screenshot(full_page=True)
    return Image.open(BytesIO(raw)).convert("RGB")


def _image_to_png_bytes(img) -> bytes:
    """Encode a Pillow image to PNG bytes for Allure attachments."""
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def dump_browser_log(
    workflow_filepath: str,
    test_name: str,
    log_entries: list,
    autk_errors: dict | None = None,
    webgpu_diagnostics: dict | None = None,
) -> str:
    """Write captured browser console + pageerror events (and any AUTK error
    tab text we extracted from the DOM) to a plain text file alongside the
    expected screenshot, and attach it to the Allure report.

    Returns the path written.
    """
    stem = os.path.splitext(os.path.basename(workflow_filepath))[0]
    os.makedirs(WORKFLOW_SCREENSHOT_EXPECTED_DIR, exist_ok=True)
    log_path = os.path.join(
        WORKFLOW_SCREENSHOT_EXPECTED_DIR,
        f"screenshot_{stem}_{test_name}_browser_log.txt",
    )
    lines: list[str] = []
    lines.append(f"# Browser log for {stem} :: {test_name}")
    lines.append(f"# Captured {len(log_entries)} console/pageerror events")
    lines.append("")
    if webgpu_diagnostics is not None:
        lines.append("## WebGPU diagnostics (probed once per session)")
        lines.append(json.dumps(webgpu_diagnostics, indent=2, default=str))
        lines.append("")
    if autk_errors:
        lines.append("## AUTK error tab text (extracted from DOM)")
        for node_id, text in autk_errors.items():
            lines.append(f"--- node {node_id} ---")
            lines.append(text or "(empty)")
            lines.append("")
    lines.append("## Console / pageerror events (chronological)")
    for entry in log_entries:
        if entry.get("kind") == "pageerror":
            lines.append(f"[pageerror] {entry.get('message', '')}")
        else:
            loc = entry.get("location") or {}
            url = loc.get("url", "")
            line_no = loc.get("lineNumber", "")
            lines.append(
                f"[{entry.get('type', 'log')}] {entry.get('text', '')}"
                f"  ({url}:{line_no})"
            )
    payload = "\n".join(lines) + "\n"
    with open(log_path, "w", encoding="utf-8") as f:
        f.write(payload)
    try:
        allure.attach(
            payload,
            name=f"screenshot_{stem}_{test_name}_browser_log.txt",
            attachment_type=allure.attachment_type.TEXT,
        )
    except Exception:
        pass
    return log_path


def save_workflow_test_screenshot(
    page: Page,
    workflow_filepath: str,
    *,
    test_name: str,
    pixel_threshold: int = 30,
    max_diff_ratio: float = 0.20,
) -> str:
    """Compare or create an expected screenshot for a workflow test.

    If the expected file already exists the current page is captured and
    compared pixel-by-pixel against it.  Both images are resized to the
    same dimensions before comparison so layout-only size changes don't
    cause false positives.  The assertion fails when more than
    *max_diff_ratio* (default 15 %) of pixels differ by more than
    *pixel_threshold* (per-channel, 0-255).

    On failure the expected, actual, and diff images are attached to the
    Allure report so that reviewers can inspect the regression directly
    from the GitHub Actions artifact.

    If the file does **not** exist yet the screenshot is saved as the new
    baseline.

    Returns the path to the expected screenshot file.
    """
    from PIL import Image, ImageChops, ImageEnhance

    stem = os.path.splitext(os.path.basename(workflow_filepath))[0]
    os.makedirs(WORKFLOW_SCREENSHOT_EXPECTED_DIR, exist_ok=True)
    filename = f"screenshot_{stem}_{test_name}.png"
    expected_path = os.path.join(WORKFLOW_SCREENSHOT_EXPECTED_DIR, filename)

    # Pin the ReactFlow viewport to a deterministic fitView before any
    # capture, so baselines and subsequent comparisons share the same
    # zoom/pan regardless of when the in-app setTimeout(fitView) fires.
    _wait_for_reactflow_ready(page)

    if not os.path.isfile(expected_path):
        _capture_full_page(page).save(expected_path)

    expected_img = Image.open(expected_path).convert("RGB")
    actual_img = _capture_full_page(page)

    target_w = max(actual_img.width, expected_img.width)
    target_h = max(actual_img.height, expected_img.height)
    actual_cmp = actual_img.resize((target_w, target_h), Image.LANCZOS)
    expected_cmp = expected_img.resize((target_w, target_h), Image.LANCZOS)

    diff = ImageChops.difference(actual_cmp, expected_cmp)
    pixels = list(diff.getdata())
    total = len(pixels)
    mismatched = sum(
        1 for r, g, b in pixels
        if r > pixel_threshold or g > pixel_threshold or b > pixel_threshold
    )
    ratio = mismatched / total if total else 0.0

    if ratio > max_diff_ratio:
        actual_path = os.path.join(
            WORKFLOW_SCREENSHOT_EXPECTED_DIR,
            f"screenshot_{stem}_{test_name}_actual.png",
        )
        actual_img.save(actual_path)

        diff_highlighted = ImageEnhance.Brightness(diff).enhance(3.0)

        allure.attach(
            _image_to_png_bytes(expected_cmp),
            name=f"{filename} — expected",
            attachment_type=allure.attachment_type.PNG,
        )
        allure.attach(
            _image_to_png_bytes(actual_cmp),
            name=f"{filename} — actual",
            attachment_type=allure.attachment_type.PNG,
        )
        allure.attach(
            _image_to_png_bytes(diff_highlighted),
            name=f"{filename} — diff",
            attachment_type=allure.attachment_type.PNG,
        )

        raise AssertionError(
            f"Screenshot regression for {filename}: "
            f"{mismatched}/{total} pixels differ ({ratio:.2%}), "
            f"allowed {max_diff_ratio:.2%}. "
            f"Expected {expected_img.size[0]}x{expected_img.size[1]}, "
            f"actual {actual_img.size[0]}x{actual_img.size[1]}. "
            f"Actual saved to {actual_path}. "
            f"See Allure report attachments for visual diff."
        )
    return expected_path


def debug_log(location: str, message: str, data: dict = None, hypothesis_id: str = ""):
    """Write a single NDJSON debug entry to ``.curio/playwright.log``."""
    try:
        log_path = os.path.join(REPO_ROOT, ".curio", "playwright.log")
        entry = {
            "timestamp": int(time.time() * 1000),
            "location": location,
            "message": message,
            "data": data or {},
            "hypothesisId": hypothesis_id,
        }
        with open(log_path, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Network / server helpers
# ---------------------------------------------------------------------------

def is_port_in_use(port: int) -> bool:
    """Return ``True`` if *port* is already listening on localhost."""
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("localhost", port)) == 0


def wait_for_http_ready(
    base_url: str,
    path: str = "/live",
    timeout: float = 30.0,
    interval: float = 0.5,
) -> None:
    """Wait until ``GET base_url + path`` returns 200 or raise ``TimeoutError``."""
    url = f"{base_url.rstrip('/')}{path}"
    deadline = time.time() + timeout
    last_err = None
    while time.time() < deadline:
        try:
            req = Request(url, method="GET")
            with urlopen(req, timeout=5) as resp:
                if resp.getcode() == 200:
                    return
        except (URLError, OSError) as e:
            last_err = e
        time.sleep(interval)
    raise TimeoutError(
        f"HTTP GET {url} did not return 200 within {timeout}s "
        f"(last error: {last_err})"
    )


def wait_for_port(
    port: int, timeout: float = 30.0, interval: float = 0.5
) -> None:
    """Wait until something is listening on *port* or raise ``TimeoutError``."""
    import socket

    deadline = time.time() + timeout
    while time.time() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(interval)
    raise TimeoutError(
        f"Port {port} did not become ready within {timeout}s"
    )


def e2e_existing_servers():
    """When ``CURIO_E2E_USE_EXISTING=1``, use already-running servers.

    Waits for backend and sandbox ``/live`` to respond before returning.
    """
    host = os.environ.get("CURIO_E2E_HOST", "localhost")
    backend_port = int(os.environ.get("CURIO_E2E_BACKEND_PORT", "5002"))
    sandbox_port = int(os.environ.get("CURIO_E2E_SANDBOX_PORT", "2000"))
    frontend_port = int(os.environ.get("CURIO_E2E_FRONTEND_PORT", "8080"))
    base = f"http://{host}"
    wait_for_http_ready(f"{base}:{backend_port}", timeout=60.0)
    wait_for_http_ready(f"{base}:{sandbox_port}", timeout=60.0)
    return {
        "backend_port": backend_port,
        "sandbox_port": sandbox_port,
        "frontend_port": frontend_port,
        "_host": host,
    }


def base_url(servers: dict, port_key: str) -> str:
    """Build an ``http://host:port`` URL from the *servers* dict."""
    host = servers.get("_host", "127.0.0.1")
    port = servers[port_key]
    return f"http://{host}:{port}"


# ---------------------------------------------------------------------------
# Reusable auth + canvas-entry helpers
#
# Every workflow/project E2E test needs the same bootstrap: sign up a fresh
# user, land on /projects, then open a new empty workflow canvas. These
# helpers centralise that choreography so individual tests (and the class
# scoped ``loaded_workflow`` fixture) stay focused on their actual assertions.
# ---------------------------------------------------------------------------

DEFAULT_TEST_PASSWORD = "testpass123"


def signup_e2e_user(
    page,
    base_url: str,
    *,
    name: str,
    username: str,
    password: str = DEFAULT_TEST_PASSWORD,
) -> None:
    """Sign up a fresh user via the ``/auth/signup`` form.

    Waits until the sign-up flow has redirected to ``/projects`` so callers
    can immediately interact with the authenticated UI.
    """
    require_user_auth()
    page.goto(f"{base_url}/auth/signup")
    page.wait_for_load_state("domcontentloaded")
    page.get_by_text("Create an account").wait_for(timeout=30000)
    page.get_by_label("Name", exact=True).fill(name)
    page.get_by_label("Username").fill(username)
    page.get_by_label("Password", exact=True).fill(password)
    page.get_by_label("Confirm Password").fill(password)
    page.get_by_role("button", name="Create Account").click()
    page.wait_for_url("**/projects", timeout=30000)


def open_new_workflow(page) -> None:
    """From ``/projects``, click "+ New Dataflow" and wait for the canvas."""
    page.get_by_text("+ New Dataflow").click()
    page.wait_for_url("**/dataflow/**", timeout=15000)
    page.wait_for_load_state("domcontentloaded")


def signup_and_enter_new_workflow(
    page,
    base_url: str,
    *,
    name: str,
    username: str,
    password: str = DEFAULT_TEST_PASSWORD,
) -> None:
    """Sign up a user and navigate to a fresh empty dataflow canvas."""
    signup_e2e_user(
        page, base_url, name=name, username=username, password=password,
    )
    open_new_workflow(page)


# ---------------------------------------------------------------------------
# DB stubs for Playwright — the browser does not drive the signup form.
#
# ``/api/testing/stub-login`` creates or fetches a user and returns a fresh
# session token, which we install as the ``session_token`` cookie on the
# Playwright context. ``/api/testing/stub-project`` seeds a workflow row
# owned by that user so ``/projects`` has something to render. Both endpoints
# require ``CURIO_TESTING=1``; see ``backend/app/testing/routes.py``.
# ---------------------------------------------------------------------------

SESSION_COOKIE_NAME = "session_token"


def _post_json(url: str, payload: dict, timeout: float = 10.0) -> dict:
    """POST *payload* as JSON to *url* and return the parsed JSON body.

    Uses ``urllib`` (stdlib only) to match the rest of this module instead
    of introducing a ``requests`` dependency.
    """
    data = json.dumps(payload).encode("utf-8")
    req = Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(req, timeout=timeout) as resp:  # noqa: S310 (trusted local URL)
        body = resp.read().decode("utf-8") or "{}"
        return json.loads(body)


def install_session_cookie(page, frontend_url: str, token: str) -> None:
    """Install *token* as the ``session_token`` cookie on *page*'s context.

    Mirrors what ``setToken`` does in ``utils/authApi.ts`` (``js-cookie``
    defaults: path=/``, host-only, no ``Secure`` on http). Playwright derives
    the domain from ``url`` when neither ``domain`` nor ``path`` is set, so
    the SPA's ``Cookies.get("session_token")`` finds the same value.
    """
    page.context.add_cookies(
        [
            {
                "name": SESSION_COOKIE_NAME,
                "value": token,
                "url": frontend_url,
            }
        ]
    )


def stub_db_login(
    page,
    frontend_url: str,
    backend_url: str,
    *,
    username: str,
    name: str,
    password: str = DEFAULT_TEST_PASSWORD,
    email: str | None = None,
    project_name: str | None = None,
    project_spec: dict | None = None,
) -> dict:
    """DB stub helper for Curio E2E tests.

    Creates (or re-uses) *username* directly via ``/api/testing/stub-login``,
    installs the returned session token as the browser cookie, and — when
    ``project_name`` is provided — seeds a workflow row owned by that user
    via ``/api/testing/stub-project`` so the ``/projects`` list page has
    content to render.

    Returns the parsed ``stub-login`` JSON (``{user, token, created}``),
    augmented with ``project`` when one was stubbed.
    """
    payload = {"username": username, "name": name, "password": password}
    if email is not None:
        payload["email"] = email
    login = _post_json(f"{backend_url}/api/testing/stub-login", payload)
    install_session_cookie(page, frontend_url, login["token"])

    if project_name is not None:
        project_payload: dict = {"username": username, "name": project_name}
        if project_spec is not None:
            project_payload["spec"] = project_spec
        project = _post_json(
            f"{backend_url}/api/testing/stub-project", project_payload,
        )
        login["project"] = project
    return login


def stub_login_and_enter_workflow(
    page,
    frontend_url: str,
    backend_url: str,
    *,
    username: str,
    name: str,
    password: str = DEFAULT_TEST_PASSWORD,
    project_name: str = "StubbedDataflow",
    project_spec: dict | None = None,
) -> dict:
    """DB-stubbed fast-path into an empty dataflow canvas.

    Creates the user + an empty project directly via
    ``/api/testing/stub-login`` and ``/api/testing/stub-project``, installs
    the session cookie on the Playwright context, and navigates straight to
    ``/dataflow/<project_id>`` — **no UI interaction**. Returns the full
    ``stub_db_login`` payload (``{user, token, created, project}``).

    This skips both the signup form and the "+ New Dataflow" click on
    ``/projects`` so the class-scoped ``loaded_workflow`` fixture spends its
    warm-up time on the actual workflow upload instead of UI plumbing.
    """
    result = stub_db_login(
        page,
        frontend_url=frontend_url,
        backend_url=backend_url,
        username=username,
        name=name,
        password=password,
        project_name=project_name,
        project_spec=project_spec,
    )
    project_id = result["project"]["id"]
    page.goto(f"{frontend_url}/dataflow/{project_id}")
    page.wait_for_load_state("domcontentloaded")
    page.wait_for_url(f"**/dataflow/{project_id}", timeout=15000)
    return result


# ---------------------------------------------------------------------------
# Reusable upload helper
# ---------------------------------------------------------------------------

def upload_workflow(
    page, app_frontend, workflow_file: str, expected_node_count: int
):
    """Open the File menu on the current workflow canvas, upload a workflow
    JSON and wait until the expected number of nodes render.

    The caller is expected to have already navigated ``page`` to a
    ``/dataflow/...`` route (e.g. via ``signup_and_enter_new_workflow``).
    """
    debug_log(
        "fixtures.py:upload_workflow",
        "upload_workflow called",
        {
            "page_type": type(page).__name__,
            "app_frontend_type": type(app_frontend).__name__,
            "workflow_file": workflow_file,
            "expected_node_count": expected_node_count,
            "page_is_closed": page.is_closed(),
            "page_url": str(page.url),
        },
        "H1,H2,H3",
    )
    page.wait_for_load_state("domcontentloaded")

    try:
        page.wait_for_load_state("networkidle", timeout=30000)
    except PlaywrightError:
        pass

    file_menu_btn = page.get_by_role("button", name=re.compile("File"))
    file_menu_btn.wait_for(state="visible", timeout=60000)
    file_menu_btn.scroll_into_view_if_needed()
    # force=True so the click isn't captured by the ReactFlow canvas layer
    file_menu_btn.click(force=True)

    # Click "Load dataflow" and upload the JSON file
    load_spec = page.get_by_role("button", name="Load dataflow")
    load_spec.wait_for(state="visible", timeout=15000)
    assert load_spec.is_visible()

    with page.expect_file_chooser() as fc_info:
        page.get_by_text("Load dataflow").click()
    fc_info.value.set_files(workflow_file)

    # Wait until all expected nodes have rendered on the ReactFlow canvas
    page.wait_for_function(
        f"document.querySelectorAll('.react-flow__node').length >= "
        f"{expected_node_count}",
        timeout=60000,
    )
    # hide the tools menu bar so it doesn't interfere with the test
    # get parent of #step-loading
    step_loading = page.locator("#step-loading")
    tools_menu_bar = step_loading.locator("..")
    if tools_menu_bar.count() >= 1:
        page.evaluate(
            "element => { element.style.display = 'none'; }",
            tools_menu_bar.element_handle() # Pass the ElementHandle to the evaluate function
        )

        assert tools_menu_bar.is_hidden() is True, (
            f"Tools menu bar is not hidden"
        )


# ---------------------------------------------------------------------------
# Playwright page wrapper
# ---------------------------------------------------------------------------

class FrontendPage(Page):
    def __init__(self, frontend_server: str, page: Page):  # noqa
        debug_log(
            "utils.py:FrontendPage.__init__",
            "FrontendPage created",
            {
                "frontend_server": frontend_server,
                "page_type": type(page).__name__,
                "page_url": str(page.url),
                "page_is_closed": page.is_closed(),
            },
            "H1,H2,H3",
        )
        self.frontend_server = frontend_server
        self.base_url = frontend_server
        self.page = page
        self.browser_context = page.context

    def __getattribute__(self, item):
        try:
            return object.__getattribute__(self, item)
        except AttributeError:
            page = object.__getattribute__(self, "page")
            return object.__getattribute__(page, item)

    def set_language(self, language="en-US"):
        self.browser_context.set_extra_http_headers(
            {"Accept-Language": language}
        )

    def goto_page(self, path):
        url = f"{self.frontend_server}{path}"
        debug_log(
            "utils.py:goto_page",
            "About to navigate",
            {
                "url": url,
                "page_is_closed": self.page.is_closed(),
                "page_url": str(self.page.url),
                "has_impl_obj": hasattr(self, "_impl_obj"),
            },
            "H2,H3,H5",
        )
        try:
            result = self.page.goto(f"{self.frontend_server}{path}")
            debug_log(
                "utils.py:goto_page",
                "Navigation succeeded",
                {
                    "url": url,
                    "result_status": result.status if result else None,
                },
                "H2,H4",
            )
            return result
        except Exception as e:
            debug_log(
                "utils.py:goto_page",
                "Navigation FAILED",
                {
                    "url": url,
                    "error_type": type(e).__name__,
                    "error_msg": str(e)[:500],
                },
                "H1,H2,H3,H4,H5",
            )
            raise

    def expect_url(self, url: str):
        self.page.expect_navigation(url=url)
        self.page.wait_for_url(url)

    def expect_page_title(self, search_title: str):
        expect(self.page).to_have_title(re.compile(search_title))
