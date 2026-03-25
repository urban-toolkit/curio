import os
import re
import json
import time
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
    max_diff_ratio: float = 0.15,
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

