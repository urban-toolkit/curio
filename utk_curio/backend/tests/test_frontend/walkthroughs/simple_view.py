"""The scene on Simple View showing the images a frame carries."""
from __future__ import annotations

from ..utils import frame_node, node_locator, run_node_and_wait
from .framework import Ctx, walkthrough
from .steps import first_node_of_type


IMAGE_URLS_EXAMPLE = "dataflows/ImageUrls.json"


@walkthrough(
    slug="simple-view-shows-a-frames-images",
    refs=[276],
    title="Simple View shows the pictures a frame carries",
    premise="Run a node that emits a GeoDataFrame of images, and read the node below it.",
    note="Simple View decided it was looking at images by testing `input.data.image_id`, "
         "which is a DataFrame column map - so a GeoDataFrame, whose columns live under "
         "each feature's properties, could never reach image mode however it was shaped, "
         "and a column of image URLs had no path at all. It now derives rows first and "
         "reads the image columns off them, and draws a card per row: the picture, then "
         "the rest of that row. That is what let the CV-specific gallery node retire.",
    tests=["src/tests/adapters/node/simpleVisImages.test.tsx",
           "src/tests/utils/imageColumns.test.ts"],
    example=IMAGE_URLS_EXAMPLE,
    # The scene frames the Simple View node itself; the harness must not re-fit.
    fit_reactflow=False,
)
def simple_view_shows_a_frames_images(ctx: Ctx) -> None:
    page = ctx.page

    producer = first_node_of_type(
        IMAGE_URLS_EXAMPLE, "computation-analysis", containing="image_url",
    )
    viewer = first_node_of_type(IMAGE_URLS_EXAMPLE, "vis-simple")

    node = node_locator(page, viewer)
    node.wait_for(state="visible", timeout=45000)
    ctx.focus(node, hold=900)
    ctx.say("A Simple View, waiting on the node above it",
            "The frame it is about to receive carries a column of pictures.")

    text = run_node_and_wait(page, producer, node_type="computation-analysis",
                             timeout_ms=180000)
    assert "Saved to file" in text, (
        f"the producer should have written an artifact, got {text!r}"
    )

    # The claim: one card per row, each with its image and the row it came from.
    # A GeoDataFrame took the table branch before this fix, so `img` was 0.
    cards = node.locator(f'[id^="imageBox_content_{viewer}_"]')
    cards.first.wait_for(state="visible", timeout=45000)
    assert cards.count() == 3, (
        f"expected one card per row, got {cards.count()} (#276)"
    )
    images = page.locator(f'#imageBox_content_{viewer} img')
    assert images.count() == 3, (
        f"expected one image per card, got {images.count()}; a GeoDataFrame of "
        f"image URLs used to render as a table (#276)"
    )
    assert "dominant_class: vegetation" in (node.inner_text() or ""), (
        "each card should caption the row that produced its image"
    )

    frame_node(page, viewer, zoom=1.1)
    ctx.focus(node, hold=1200)
    ctx.say("One card per row",
            "The picture, and the values that describe it.")
    ctx.capture("cards-rendered")
