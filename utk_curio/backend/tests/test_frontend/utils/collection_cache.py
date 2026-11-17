"""The Data Catalog drawer, and **Cache files** in a collection's details.

A committed collection whose files are in a bucket
(``dataset_catalog_coverage.bucket_source``) is read once its files are on
this machine wherever no mount reads the bucket, as on every e2e stack: the
Collection section of its details offers **Cache files**, which copies them
from the recorded corpus, the bucket's stand-in here.
"""

from __future__ import annotations

import re

from playwright.sync_api import expect

#: The Data Catalog drawer's root.
DRAWER_ROOT = '[data-curio-dataset-catalog-drawer="true"]'
# The "Adding…" placeholder is an <article role="status"> carrying the same
# title as the real card, so every card locator has to exclude it.
CARD = 'article:not([role="status"])'


def data_catalog_drawer(page):
    """The Data Catalog drawer, once a click opened it and it is in place."""
    root = page.locator(DRAWER_ROOT)
    root.wait_for(state="attached", timeout=15000)
    # aria-hidden IS the presented signal: until the rAF flips it, every role
    # query inside the subtree returns zero matches, so gating on it is
    # strictly better than waiting for visibility (the drawer slides in via
    # translate3d, so it is "visible" before it is usable).
    expect(root).to_have_attribute("aria-hidden", "false", timeout=10000)
    dialog = page.get_by_role("dialog").filter(
        has=page.get_by_role("heading", name="Data Catalog", exact=True)
    )
    expect(dialog).to_be_visible(timeout=10000)
    return dialog


def cache_collection_files(page, drawer, card_id: str, files: int) -> None:
    """Cache the collection's files from its details, as a person does, then
    close them.

    A committed collection whose files are in a bucket (``bucket_source``) is
    read once they are on this machine wherever no mount reads the bucket, as
    on every e2e stack: the Collection section's **Cache files** copies them
    from the recorded corpus, the bucket's stand-in here, and then says every
    file is on this machine.
    """
    card = drawer.locator(f'{CARD}[data-dataset-id="{card_id}"]')
    card.get_by_role("button", name=re.compile(r"^View .+ details$")).click()
    details = page.get_by_role("dialog", name="Dataset details")
    expect(details).to_be_visible(timeout=30000)
    details.get_by_role("button", name="Cache files", exact=True).click()
    expect(details.get_by_text(f"{files:,} of {files:,} files", exact=True)).to_be_visible(timeout=120000)
    expect(details.get_by_role("button", name="Cache files", exact=True)).to_have_count(0)
    # One Escape closes the details alone; the drawer under them stays open.
    page.keyboard.press("Escape")
    expect(details).to_have_count(0, timeout=10000)


def bucket_collections_of(dataset_ids) -> list:
    """Of *dataset_ids*, the committed collections whose files are in a bucket,
    as ``dataset_catalog_coverage`` finds them, with each one's file count."""
    from utk_curio.backend.tests.dataset_catalog_coverage import bucket_collections, expected_markers

    wanted = set(dataset_ids)
    return [
        (dataset, int(expected_markers(dataset)["CURIO_E2E_ROWS"]))
        for dataset in bucket_collections()
        if dataset.dataset_id in wanted
    ]


def cache_bucket_collections(page, dataset_ids) -> list[str]:
    """Cache, from the open dataflow's Data Catalog drawer, the files of each
    of *dataset_ids* that is a committed collection of a bucket, as a person
    does on a Curio that mounts no bucket; the ids it cached."""
    from .palettes import close_tools_palette, open_tools_palette

    collections = bucket_collections_of(dataset_ids)
    if not collections:
        return []
    palette = open_tools_palette(page, "datasets")
    palette.get_by_role("button", name="Browse Data Catalog +").click(force=True)
    drawer = data_catalog_drawer(page)
    for dataset, files in collections:
        cache_collection_files(page, drawer, dataset.dataset_id, files)
    # This drawer has no Escape handler, so close through the header button.
    drawer.locator("header").get_by_role("button", name="Close Data Catalog drawer").click()
    expect(page.locator(DRAWER_ROOT)).to_have_count(0, timeout=5000)
    close_tools_palette(page, "datasets")
    return [dataset.dataset_id for dataset, _files in collections]
