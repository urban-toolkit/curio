import os
import re
import json
import time
import zlib
import shutil
import textwrap
from pathlib import Path
from io import BytesIO
from urllib.request import urlopen, Request
from urllib.error import URLError

import allure
from playwright.sync_api import Page, expect

# Repo root is 4 levels up: test_frontend -> tests -> backend -> utk_curio -> curio-main
REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "..")
)

# PNGs from workflow E2E tests: ``screenshot_{workflow_stem}_{test_name}.png``
WORKFLOW_SCREENSHOT_EXPECTED_DIR = os.path.join(
    REPO_ROOT, "docs", "examples", "flows", "expected_outputs"
)



def get_shared_data_dir() -> str:
    """Directory where ``save_memory_mapped_file`` writes ``.data`` blobs.

    Matches ``utk_curio/sandbox/util/parsers.py`` (``CURIO_LAUNCH_CWD`` +
    ``CURIO_SHARED_DATA``). Defaults ``CURIO_LAUNCH_CWD`` to the repo root
    so host-side Playwright resolves the same path as ``curio start`` when the
    subprocess uses ``cwd`` = repo root (and matches Docker once ``./.curio`` is
    bind-mounted to ``/app/.curio``).
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

def load_dot_data(path: str) -> dict:
    """Read a ``.data`` file (zlib-compressed JSON) and return the parsed dict."""
    with open(path, "rb") as f:
        return json.loads(zlib.decompress(f.read()).decode("utf-8"))


def save_dot_data(path: str, data: dict) -> None:
    """Write *data* as zlib-compressed JSON to *path*."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    compressed = zlib.compress(json.dumps(data, ensure_ascii=False).encode("utf-8"))
    with open(path, "wb") as f:
        f.write(compressed)


def strip_volatile_keys(data: dict) -> dict:
    """Return a shallow copy of *data* without per-run metadata (``filename``)."""
    stripped = {**data}
    stripped.pop("filename", None)
    return stripped


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

    ``save_memory_mapped_file`` uses ``CURIO_SHARED_DATA`` with
    ``Path.relative_to`` and requires an absolute path.  When the test
    process is *not* started via ``curio start`` (e.g. ``CURIO_E2E_USE_EXISTING``
    in CI) these variables may be absent.
    """
    if "CURIO_LAUNCH_CWD" not in os.environ:
        os.environ["CURIO_LAUNCH_CWD"] = REPO_ROOT
    if "CURIO_SHARED_DATA" not in os.environ:
        os.environ["CURIO_SHARED_DATA"] = str(
            Path(os.path.join(REPO_ROOT, ".curio", "data")).resolve()
        )


def execute_workflow_programmatically(spec, seed: int = 42) -> dict[str, str]:
    """Execute every code node in-process and return *{node_id: expected_path}*.

    Mirrors the sandbox ``python_wrapper.txt`` flow — load upstream data,
    call user code, serialise via ``parseOutput`` / ``save_memory_mapped_file``
    — but runs entirely inside the test process.  Results are copied to
    ``.curio/playwright/expected/<workflow>/`` for later comparison with the
    browser-produced ``.data`` files.
    """
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
# Reusable upload helper
# ---------------------------------------------------------------------------

def upload_workflow(
    page, app_frontend, workflow_file: str, expected_node_count: int
):
    """Navigate to the app, open the File menu, upload a workflow JSON,
    and wait until the expected number of nodes appear on the canvas."""
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
    app_frontend.goto_page("/")
    page.wait_for_load_state("domcontentloaded")

    # Open the File dropdown in the menu bar
    file_menu_btn = page.get_by_role("button", name=re.compile("File"))
    file_menu_btn.wait_for(state="visible", timeout=15000)
    file_menu_btn.scroll_into_view_if_needed()
    # force=True so the click isn't captured by the ReactFlow canvas layer
    file_menu_btn.click(force=True)

    # Click "Load specification" and upload the JSON file
    load_spec = page.get_by_role("button", name="Load specification")
    load_spec.wait_for(state="visible", timeout=5000)
    assert load_spec.is_visible()

    with page.expect_file_chooser() as fc_info:
        page.get_by_text("Load specification").click()
    fc_info.value.set_files(workflow_file)

    # Wait until all expected nodes have rendered on the ReactFlow canvas
    page.wait_for_function(
        f"document.querySelectorAll('.react-flow__node').length >= "
        f"{expected_node_count}",
        timeout=15000,
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
        self.page = page
        self.browser_context = page.context

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

