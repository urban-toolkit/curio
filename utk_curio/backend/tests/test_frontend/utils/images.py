"""Page captures as Pillow images, Autark maps painted in, and the pixel
comparison of two images.
"""

from contextlib import contextmanager
from io import BytesIO
from typing import NamedTuple

from playwright.sync_api import Page


# Each Autark map canvas gets its own pixels as a CSS background for the length
# of one capture. On the GPU runner no Chrome screenshot includes a hardware
# WebGPU canvas (#427): the maps draw, and every frame showed them blank. A CSS
# background is painted by the page's own compositor, which the screenshot does
# capture, and it sits under the canvas and the map's overlays. Where the
# screenshot does include the canvas (a Mac), the opaque map covers it, so the
# frame is unchanged.
_PAINT_MAP_CANVASES_JS = """async () => {
    await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
    let painted = 0;
    for (const c of document.querySelectorAll('canvas[id^="autk-grammar-map-"]')) {
        let url;
        try { url = c.toDataURL('image/png'); } catch (e) { continue; }
        c.dataset.curioCaptureBackground = JSON.stringify(
            [c.style.backgroundImage, c.style.backgroundSize, c.style.backgroundRepeat]);
        c.style.backgroundImage = `url("${url}")`;
        c.style.backgroundSize = '100% 100%';
        c.style.backgroundRepeat = 'no-repeat';
        painted += 1;
    }
    if (painted) await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
    return painted;
}"""

_UNPAINT_MAP_CANVASES_JS = """() => {
    for (const c of document.querySelectorAll('canvas[data-curio-capture-background]')) {
        const [image, size, repeat] = JSON.parse(c.dataset.curioCaptureBackground);
        c.style.backgroundImage = image;
        c.style.backgroundSize = size;
        c.style.backgroundRepeat = repeat;
        delete c.dataset.curioCaptureBackground;
    }
}"""


@contextmanager
def _map_canvases_painted(page: Page):
    """Autark map canvases carry their own pixels as a background while inside."""
    painted = page.evaluate(_PAINT_MAP_CANVASES_JS)
    try:
        yield painted
    finally:
        if painted:
            page.evaluate(_UNPAINT_MAP_CANVASES_JS)


def _capture_full_page(page: Page):
    """Return a Pillow RGB image of the full scrollable page.

    Scrolls to top-left first so the capture is deterministic, then uses
    Playwright's ``full_page=True`` to grab everything.
    """
    from PIL import Image

    page.evaluate("window.scrollTo(0, 0)")
    with _map_canvases_painted(page):
        raw = page.screenshot(full_page=True)
    return Image.open(BytesIO(raw)).convert("RGB")


def _capture_element(page: Page, selector: str):
    """Return a Pillow RGB image of one element, or raise if it is not there.

    For a baseline whose subject is a panel rather than a page. A full-page
    capture of, say, an agent chat turn is more than half static canvas and
    chrome, which does not just waste the image - it dilutes the comparison,
    since a regression inside the panel is a small fraction of the frame
    against a 10% budget.
    """
    from PIL import Image

    locator = page.locator(selector)
    locator.wait_for(state="visible", timeout=15000)
    with _map_canvases_painted(page):
        raw = locator.screenshot()
    return Image.open(BytesIO(raw)).convert("RGB")


def _image_to_png_bytes(img) -> bytes:
    """Encode a Pillow image to PNG bytes for Allure attachments."""
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class _Comparison(NamedTuple):
    actual_cmp: object
    expected_cmp: object
    diff: object
    arr: object
    counted: object
    mismatched: int
    total: int
    ratio: float


def _compare_images(actual_img, expected_img, pixel_threshold: int) -> _Comparison:
    """Count the pixels where *actual_img* and *expected_img* differ by more than
    *pixel_threshold* in any channel, both resized to the larger of their sizes.
    """
    from PIL import Image, ImageChops
    import numpy as np

    target_w = max(actual_img.width, expected_img.width)
    target_h = max(actual_img.height, expected_img.height)
    actual_cmp = actual_img.resize((target_w, target_h), Image.LANCZOS)
    expected_cmp = expected_img.resize((target_w, target_h), Image.LANCZOS)

    diff = ImageChops.difference(actual_cmp, expected_cmp)
    arr = np.asarray(diff)
    total = int(arr.shape[0] * arr.shape[1])
    counted = (arr > pixel_threshold).any(axis=2)
    mismatched = int(counted.sum())
    ratio = mismatched / total if total else 0.0
    return _Comparison(actual_cmp, expected_cmp, diff, arr, counted, mismatched, total, ratio)
