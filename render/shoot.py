"""Screenshot each rendered card (render_chart.cjs) to a PNG at twice the size.

    python shoot.py <out dir> <name>...
"""

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright


def main() -> None:
    out = Path(sys.argv[1])
    names = sys.argv[2:]
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 960, "height": 600}, device_scale_factor=2)
        for name in names:
            page.goto((out / f"{name}.html").as_uri())
            page.evaluate("document.fonts.ready")
            page.locator("#shot").screenshot(path=str(out / f"{name}.png"))
            print(out / f"{name}.png")
        browser.close()


if __name__ == "__main__":
    main()
