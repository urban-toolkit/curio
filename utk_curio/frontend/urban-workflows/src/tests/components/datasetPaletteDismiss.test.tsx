import React from "react";
import { render, screen, fireEvent } from "@testing-library/react";

/**
 * Pins the palette's dismissal contract: it closes on its own trigger and on
 * nothing else.
 *
 * Before the palettes moved into the left rail, both dropdowns ran a document
 * ``mousedown`` capture and an Escape ``keydown`` handler routed through
 * ``isToolsPaletteDismissOutsideClick``. Those were deleted deliberately: the
 * panel now opens into a fixed strip beside the rail, and dragging a dataset
 * from it onto the canvas is an outside click, so self-dismissal made the
 * palette unusable for its main purpose.
 *
 * That makes the current behaviour an absence of code, which is exactly the
 * kind of thing a later "the palette doesn't close when I click away" bug
 * report gets 'fixed' back into place. These tests fail if it is.
 *
 * ``PackagesPaletteDropdown`` lost the identical pair of handlers in the same
 * change; it is not covered here only because standing it up needs five more
 * providers for the same assertion.
 */

// DatasetPaletteRows imports one constant (OVERLAY_TRIGGER_DELAY_PROPS) through
// the package-palette barrel, which re-exports PackagesPaletteDropdown and so
// drags in the registry and vega/vega-lite — ESM that jest's transform does not
// handle. Stub the barrel down to the constant that is actually used.
jest.mock("../../components/menus/nodes/toolsMenuPackagePalette", () => ({
  OVERLAY_TRIGGER_DELAY_PROPS: { delay: { show: 0, hide: 0 } },
}));

jest.mock("../../providers/FlowProvider", () => ({
  useFlowContext: () => ({
    projectId: "p1",
    outputs: [],
    nodes: [],
    defaultSaveOutputDataset: false,
    pendingInstalls: [],
  }),
}));
jest.mock("../../providers/datasetCatalog", () => ({
  useDatasetCatalogDrawer: () => ({ openDatasetCatalogDrawer: jest.fn() }),
}));
jest.mock("../../providers/DatasetPaletteContext", () => ({
  useDatasetPalette: () => ({ datasetRevealId: null, setDatasetRevealId: jest.fn() }),
}));
jest.mock("../../services/datasetCatalog", () => ({
  DATASET_CATALOG_REFRESH_EVENT: "curio:dataset-catalog-refresh",
  useDatasetCatalog: () => ({ items: [], loading: false, refreshing: false }),
  prefetchDatasetCatalog: jest.fn(),
  groupDatasetsForPalette: () => [],
  isUserInstalledDataset: () => false,
  sortDatasetPaletteEntries: (rows: unknown[]) => rows,
}));
jest.mock("../../utils/saveOutputDataset", () => ({ buildSaveableLiveOutputs: () => [] }));
jest.mock("../../services/datasetCatalog/pendingInstallView", () => ({
  pendingInstallsNotYetListed: () => [],
}));

import { DatasetsPaletteDropdown } from "../../components/menus/nodes/datasetPalette/DatasetsPaletteDropdown";

const panel = () => screen.queryByRole("region", { name: "Dataset palette" });

describe("DatasetsPaletteDropdown dismissal", () => {
  test("the trigger toggles the palette", () => {
    const setOpen = jest.fn();
    const { rerender } = render(<DatasetsPaletteDropdown open={false} setOpen={setOpen} />);
    expect(panel()).toBeNull();

    fireEvent.click(screen.getByTitle("Open dataset palette"));
    expect(setOpen).toHaveBeenCalledWith(true);

    rerender(<DatasetsPaletteDropdown open setOpen={setOpen} />);
    expect(panel()).not.toBeNull();

    fireEvent.click(screen.getByTitle("Close dataset palette"));
    expect(setOpen).toHaveBeenLastCalledWith(false);
  });

  test("Escape does NOT close it", () => {
    const setOpen = jest.fn();
    render(<DatasetsPaletteDropdown open setOpen={setOpen} />);
    expect(panel()).not.toBeNull();

    fireEvent.keyDown(document, { key: "Escape" });
    fireEvent.keyDown(document.body, { key: "Escape" });

    expect(setOpen).not.toHaveBeenCalled();
    expect(panel()).not.toBeNull();
  });

  test("a mousedown outside the palette does NOT close it", () => {
    const setOpen = jest.fn();
    const outside = document.createElement("div");
    document.body.appendChild(outside);
    render(<DatasetsPaletteDropdown open setOpen={setOpen} />);

    // Both a plain document mousedown and one on a detached-from-the-palette
    // element: the old handler listened in the capture phase on document.
    fireEvent.mouseDown(document);
    fireEvent.mouseDown(outside);

    expect(setOpen).not.toHaveBeenCalled();
    expect(panel()).not.toBeNull();
    outside.remove();
  });

  test("the open panel carries the marker fitView measures against", () => {
    // fitViewWithMenuOffset finds the occluded strip by querying this attribute
    // inside #tools-palette-dock; the panel is absolutely positioned and so is
    // outside the dock's own bounding rect.
    const { container } = render(<DatasetsPaletteDropdown open setOpen={jest.fn()} />);
    expect(container.querySelector("[data-curio-tools-palette-panel]")).not.toBeNull();
  });

  test("the marker is absent while closed", () => {
    const { container } = render(<DatasetsPaletteDropdown open={false} setOpen={jest.fn()} />);
    expect(container.querySelector("[data-curio-tools-palette-panel]")).toBeNull();
  });
});
