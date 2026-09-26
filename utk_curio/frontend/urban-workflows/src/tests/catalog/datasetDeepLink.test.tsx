import React from "react";
import { fireEvent, render, screen, within } from "@testing-library/react";
import "@testing-library/jest-dom";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";

/**
 * A link to a dataset opens the Data Catalog with that dataset's details.
 *
 * `/catalog/data/<id>` used to be a page of its own, the one full-page details
 * view left in the app: every "View details" opens the modal, so a shared link
 * showed the same dataset in a different container, with a Back button instead
 * of a close. It is now the Data Catalog page with the modal open, and closing
 * the modal leaves the plain page.
 */

jest.mock("../../registry/packageRegistryBootstrap", () => ({
  refreshPackageRegistry: jest.fn(),
}));
jest.mock("../../providers/FlowProvider", () => ({
  useFlowContext: () => ({ projectId: null }),
}));
jest.mock("../../providers/ToastProvider", () => ({
  useToastContext: () => ({ showToast: jest.fn() }),
}));
jest.mock("../../api/packagesApi", () => ({
  packagesApi: { factoryCapabilities: jest.fn(() => Promise.resolve({ catalogPublish: false })) },
}));
jest.mock("../../pages/dataCatalog/DataCatalogBrowseDrawer", () => ({
  DataCatalogBrowseDrawer: () => null,
}));
jest.mock("../../components/datasets/catalog/DatasetDetailModal", () => ({
  DatasetDetailModal: ({ datasetId, onClose }: { datasetId: string; onClose: () => void }) => (
    <div role="dialog" aria-label="Dataset details" data-dataset-id={datasetId}>
      <button type="button" onClick={onClose}>
        Close
      </button>
    </div>
  ),
}));
jest.mock("../../services/datasetCatalog", () => {
  const actual = jest.requireActual("../../services/datasetCatalog");
  const item = {
    id: "imported.bikes",
    title: "Bike Routes",
    origin: "imported",
    format: "csv",
    uri: "curio://datasets/imported.bikes",
    consumerNodeIds: [],
    updatedAt: "2026-01-01T00:00:00Z",
    tags: [],
    installed: false,
  };
  return {
    ...actual,
    useDatasetCatalog: () => ({
      items: [item],
      facets: { format: { csv: 1 }, origin: { imported: 1 } },
      loading: false,
      refreshing: false,
      error: null,
      reload: jest.fn(),
      importDataset: jest.fn(),
    }),
    useDatasetImport: () => ({ importing: false, importFile: jest.fn() }),
    datasetCatalogApi: {
      ...actual.datasetCatalogApi,
      listDatasetDefaults: jest.fn(() => Promise.resolve({ datasets: [] })),
    },
  };
});

import { DataCatalogBrowse } from "../../pages/dataCatalog/DataCatalogBrowse";

let location = "";
const LocationProbe: React.FC = () => {
  const loc = useLocation();
  location = loc.pathname;
  return null;
};

function renderAt(entry: string) {
  return render(
    <MemoryRouter initialEntries={[entry]}>
      <Routes>
        <Route path="/catalog/data/:datasetId?" element={<DataCatalogBrowse />} />
      </Routes>
      <LocationProbe />
    </MemoryRouter>,
  );
}

const details = () => screen.queryByRole("dialog", { name: "Dataset details" });

describe("a dataset link", () => {
  test("opens the Data Catalog with that dataset's details", async () => {
    renderAt("/catalog/data/imported.bikes");
    expect(await screen.findByRole("heading", { name: "Data Catalog" })).toBeInTheDocument();
    expect(details()).toHaveAttribute("data-dataset-id", "imported.bikes");
  });

  test("closing the details leaves the plain page", async () => {
    renderAt("/catalog/data/imported.bikes");
    fireEvent.click(within(details() as HTMLElement).getByRole("button", { name: "Close" }));

    expect(details()).toBeNull();
    expect(location).toBe("/catalog/data");
    expect(screen.getByRole("heading", { name: "Data Catalog" })).toBeInTheDocument();
  });

  test("the plain page opens nothing until asked", async () => {
    renderAt("/catalog/data");
    expect(await screen.findByRole("heading", { name: "Data Catalog" })).toBeInTheDocument();
    expect(details()).toBeNull();
  });

  test("View details opens the same modal without changing the address", async () => {
    renderAt("/catalog/data");
    fireEvent.click(await screen.findByRole("button", { name: "View details" }));

    expect(details()).toHaveAttribute("data-dataset-id", "imported.bikes");
    expect(location).toBe("/catalog/data");
  });
});
