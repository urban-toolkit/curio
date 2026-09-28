/**
 * The #137 drawer fixes, actually exercised (#360).
 *
 * #137 replaced the placeholder-only hero with a real preview fetch and wired
 * the drawer's close control to its caller. Both are still correct on main, and
 * nothing would notice losing either: ``guestCatalogAffordances.test.tsx``
 * renders this same drawer but stubs ``DataCatalogGeoPreview`` out entirely and
 * never clicks close, while ``catalogDrawerParity.test.ts`` and
 * ``datasetDetailEntryPoints.test.ts`` only grep source text for prop names.
 *
 * So this is the one test that mounts the drawer with the hero LIVE and clicks
 * the control. It asserts behaviour, not markup: rows the API returned reach
 * the DOM, and the close button calls back.
 */
import React from "react";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import "@testing-library/jest-dom";

// UserProvider imports refreshPackageRegistry, which drags in the registry ->
// adapters -> vega chain that will not load under jsdom.
jest.mock("../../registry/packageRegistryBootstrap", () => ({
  refreshPackageRegistry: jest.fn(),
}));

import { DataCatalogBrowseDrawer } from "../../pages/dataCatalog/DataCatalogBrowseDrawer";
import { UserContext } from "../../providers/UserProvider";
import { datasetCatalogApi } from "../../services/datasetCatalog";
import type { DatasetCatalogItem } from "../../services/datasetCatalog";

const DATASET = {
  id: "imported.tracts",
  dirName: "imported.tracts@1",
  title: "Census tracts",
  format: "geojson",
  origin: "imported",
  updatedAt: "2026-01-01T00:00:00Z",
} as unknown as DatasetCatalogItem;

/** Two rows with a geometry column, which the preview is supposed to drop. */
const PREVIEW_ROWS = [
  { tract: "17031010100", population: 4120, geometry: "POLYGON((...))" },
  { tract: "17031010200", population: 3980, geometry: "POLYGON((...))" },
];

function renderDrawer(overrides: Record<string, unknown> = {}) {
  const onClose = jest.fn();
  const utils = render(
    <UserContext.Provider value={{ isSharedGuest: false } as any}>
      <DataCatalogBrowseDrawer
        dataset={DATASET}
        publishingId={null}
        catalogPublishAllowed
        onPublish={jest.fn()}
        onUnpublish={jest.fn()}
        onAddToAllProjects={jest.fn()}
        onRemoveFromAllProjects={jest.fn()}
        onClose={onClose}
        onViewDetails={jest.fn()}
        {...overrides}
      />
    </UserContext.Provider>,
  );
  return { ...utils, onClose };
}

describe("the catalog drawer's dataset preview (#137)", () => {
  afterEach(() => {
    jest.restoreAllMocks();
  });

  test("renders the rows the preview API returned", async () => {
    const preview = jest
      .spyOn(datasetCatalogApi, "preview")
      .mockResolvedValue({ rows: PREVIEW_ROWS } as any);

    renderDrawer();

    // A real cell value, not a placeholder: this is what went missing in #137.
    expect(await screen.findByText("17031010100")).toBeInTheDocument();
    expect(screen.getByText("17031010200")).toBeInTheDocument();
    // Column headers come from the rows, so the header proves the same path.
    expect(screen.getByRole("columnheader", { name: "tract" })).toBeInTheDocument();
    expect(preview).toHaveBeenCalledWith(DATASET.id, { rowLimit: 3 });
  });

  test("leaves the geometry column out of the table", async () => {
    jest
      .spyOn(datasetCatalogApi, "preview")
      .mockResolvedValue({ rows: PREVIEW_ROWS } as any);

    renderDrawer();

    await screen.findByText("17031010100");
    expect(
      screen.queryByRole("columnheader", { name: "geometry" }),
    ).toBeNull();
  });

  test("says so instead of rendering an empty table when there are no rows", async () => {
    jest
      .spyOn(datasetCatalogApi, "preview")
      .mockResolvedValue({ rows: [] } as any);

    renderDrawer();

    expect(await screen.findByText("No preview rows")).toBeInTheDocument();
    expect(screen.queryByRole("table")).toBeNull();
  });

  test("surfaces a refused preview rather than failing silently", async () => {
    jest
      .spyOn(datasetCatalogApi, "preview")
      .mockResolvedValue({ unsupported: true, message: "Raster preview unavailable" } as any);

    renderDrawer();

    expect(await screen.findByText("Raster preview unavailable")).toBeInTheDocument();
  });
});

describe("the catalog drawer's close control (#137)", () => {
  afterEach(() => {
    jest.restoreAllMocks();
  });

  test("calls back when clicked", async () => {
    jest
      .spyOn(datasetCatalogApi, "preview")
      .mockResolvedValue({ rows: PREVIEW_ROWS } as any);

    const { onClose } = renderDrawer();
    await screen.findByText("17031010100");

    fireEvent.click(screen.getByRole("button", { name: "Close" }));

    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
  });
});
