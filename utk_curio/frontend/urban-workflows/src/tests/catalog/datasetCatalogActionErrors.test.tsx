import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";
import { MemoryRouter, Route, Routes } from "react-router-dom";

/**
 * #446: a failed action on the Data Catalog page says why.
 *
 * The server's refusal arrives (`apiFetch` puts the body's `error` on the
 * Error's message), but every catch on this page showed only "Couldn't
 * unpublish <title>". A user refused by the owner check could not tell that
 * from a network failure.
 */

const mockShowToast = jest.fn();

jest.mock("../../registry/packageRegistryBootstrap", () => ({
  refreshPackageRegistry: jest.fn(),
}));
jest.mock("../../providers/FlowProvider", () => ({
  useFlowContext: () => ({ projectId: null }),
}));
jest.mock("../../providers/ToastProvider", () => ({
  useToastContext: () => ({ showToast: mockShowToast }),
}));
jest.mock("../../services/packages/packagesApi", () => ({
  packagesApi: { factoryCapabilities: jest.fn(() => Promise.resolve({ catalogPublish: true })) },
}));
jest.mock("../../components/datasets/catalog/DatasetDetailModal", () => ({
  DatasetDetailModal: () => null,
}));

const mockItem = {
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

// The drawer is where these actions are pressed; stand in for it with one
// button per handler the page hands it.
jest.mock("../../pages/dataCatalog/DataCatalogBrowseDrawer", () => ({
  DataCatalogBrowseDrawer: (props: Record<string, (d: unknown) => void>) => (
    <div>
      <button type="button" onClick={() => props.onUnpublish(mockItem)}>unpublish</button>
      <button type="button" onClick={() => props.onPublish(mockItem)}>publish</button>
      <button type="button" onClick={() => props.onAddToAllProjects(mockItem)}>add</button>
      <button type="button" onClick={() => props.onRemoveFromAllProjects(mockItem)}>remove</button>
    </div>
  ),
}));

/** What `apiFetch` throws for a refusal: the body's `error` as the message. */
const refusal = (message: string, status = 403) =>
  Object.assign(new Error(message), { status, body: { error: message } });

jest.mock("../../services/datasetCatalog", () => {
  const actual = jest.requireActual("../../services/datasetCatalog");
  return {
    ...actual,
    useDatasetCatalog: () => ({
      items: [mockItem],
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
      unpublishDataset: jest.fn(),
      publishDataset: jest.fn(),
      addDatasetToDefaults: jest.fn(),
      removeDatasetFromDefaults: jest.fn(),
    },
  };
});

import { DataCatalogBrowse } from "../../pages/dataCatalog/DataCatalogBrowse";
import { DatasetDetailsProvider } from "../../components/datasets/catalog/DatasetDetailsProvider";
import { datasetCatalogApi } from "../../services/datasetCatalog";

const api = datasetCatalogApi as unknown as Record<string, jest.Mock>;

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/catalog/data"]}>
      <DatasetDetailsProvider closeOnNavigate>
        <Routes>
          <Route path="/catalog/data/:datasetId?" element={<DataCatalogBrowse />} />
        </Routes>
      </DatasetDetailsProvider>
    </MemoryRouter>,
  );
}

beforeEach(() => mockShowToast.mockClear());

test.each([
  ["unpublish", "unpublishDataset", "Only the dataset's owner can unpublish it.", "Couldn't unpublish Bike Routes: Only the dataset's owner can unpublish it."],
  ["publish", "publishDataset", "Publishing is turned off on this server.", "Couldn't publish Bike Routes: Publishing is turned off on this server."],
  ["add", "addDatasetToDefaults", "HTTP 500", "Couldn't add Bike Routes to all projects: HTTP 500"],
  ["remove", "removeDatasetFromDefaults", "HTTP 502", "Couldn't remove Bike Routes from all projects: HTTP 502"],
])("a failed %s shows the server's reason", async (button, method, reason, toast) => {
  api[method].mockRejectedValueOnce(refusal(reason));
  renderPage();
  fireEvent.click(await screen.findByRole("button", { name: button }));
  await waitFor(() => expect(mockShowToast).toHaveBeenCalledWith(toast, "error"));
});
