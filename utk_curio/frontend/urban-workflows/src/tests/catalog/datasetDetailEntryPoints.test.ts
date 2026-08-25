import fs from "fs";
import path from "path";

/**
 * One way into a dataset's details, from one page.
 *
 * `/catalog/data` used to offer two. A card's "View details ↗" navigated to
 * `/catalog/data/:id`; the detail drawer's "View sample data" opened a modal.
 * Both rendered the same `DatasetDetailPanel` with the same tabs, so the two
 * names and the two containers described one screen — and the arrow on the card
 * promised a navigation that the drawer did not make.
 *
 * Both now open the modal and stay on the browse page. The route survives for
 * deep links (and the screenshot gallery navigates to it directly), it is simply
 * not something the UI walks you into any more.
 *
 * Read from disk rather than rendered: these are assertions about what the page
 * does *not* do, and a component test can only show what a rendered tree does.
 */

const SRC = path.resolve(__dirname, "../..");
const read = (rel: string) => fs.readFileSync(path.join(SRC, rel), "utf8");

const BROWSE = "pages/dataHub/DataCatalogBrowse.tsx";
const CARD = "pages/dataHub/DataCatalogBrowseCard.tsx";
const DRAWER = "pages/dataHub/DataCatalogBrowseDrawer.tsx";
const PANEL = "components/datasets/catalog/DatasetDetailPanel.tsx";
const MODAL = "components/datasets/catalog/DatasetDetailModal.tsx";
const CANVAS_DRAWER = "components/datasets/catalog/DatasetCatalogDrawer.tsx";

describe("dataset detail entry points", () => {
  it("gives the card and the drawer the same callback", () => {
    for (const file of [CARD, DRAWER]) {
      expect(read(file)).toContain("onViewDetails");
    }
    // The drawer's prop was `onViewSample`, named for the tab it opened on.
    expect(read(DRAWER)).not.toContain("onViewSample");
    expect(read(BROWSE)).not.toContain("onViewSample");
  });

  it("calls them both the same thing", () => {
    expect(read(CARD)).toContain("View details");
    expect(read(DRAWER)).toContain("View details");
    expect(read(DRAWER)).not.toContain("View sample data");
    // The arrow said "this leaves the page", which it no longer does.
    expect(read(CARD)).not.toContain("View details ↗");
  });

  it("does not navigate away from the browse page", () => {
    const browse = read(BROWSE);
    expect(browse).not.toContain("/catalog/data/$");
    expect(browse).not.toContain("useNavigate");
  });

  it("opens the same first tab from either entry point", () => {
    // The drawer used to force initialTab="Table Preview" while the card's
    // page landed on Overview, so the same button name showed two screens.
    expect(read(BROWSE)).not.toContain("initialTab");
  });
});

describe("canvasAvailable means a canvas, not a modal", () => {
  it("is a prop rather than derived from the variant", () => {
    const panel = read(PANEL);
    // `const canvasAvailable = variant === "modal"` made the browse page's
    // modal claim a canvas that page does not have, so the Lineage tab asked
    // the canvas instead of the backend and came back empty.
    expect(panel).not.toMatch(/canvasAvailable\s*=\s*variant\s*===/);
    expect(panel).toContain("canvasAvailable?: boolean");
    expect(panel).toContain("canvasAvailable = false");
  });

  it("is set only by the in-canvas drawer", () => {
    expect(read(CANVAS_DRAWER)).toContain("canvasAvailable");
    // The browse page renders the same modal with no canvas behind it.
    expect(read(BROWSE)).not.toContain("canvasAvailable");
  });

  it("is threaded through the modal", () => {
    const modal = read(MODAL);
    expect(modal).toContain("canvasAvailable = false");
    expect(modal).toContain("canvasAvailable={canvasAvailable}");
  });
});
