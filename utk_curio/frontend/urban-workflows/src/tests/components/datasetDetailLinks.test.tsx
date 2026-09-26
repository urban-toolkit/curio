import fs from "fs";
import path from "path";
import React from "react";
import { fireEvent, render, screen, within } from "@testing-library/react";
import "@testing-library/jest-dom";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";

/**
 * Following a link inside a dataset's details modal.
 *
 * The details hold two in-app links: the portal a download came from, and each
 * dataflow that uses the dataset. They were plain `<Link>`s, so the modal
 * stayed open over whatever page they opened; on the portal's own page the
 * navigation cleared the search behind the modal. From the canvas they left
 * the dataflow without the unsaved-changes prompt every other way out of it
 * shows. Now a link closes the modal, a link to the page already open only
 * closes it, and leaving a dataflow with unsaved changes asks first.
 */

jest.mock("../../services/datasetLineage/useDatasetLineage", () => ({
  useDatasetLineage: () => ({
    datasetId: "imported.xabc",
    upstream: { generatingNode: null, sourceDatasets: [], origin: "imported", originLabel: "Imported" },
    downstream: { consumingNodes: [], consumingDataflows: [], derivedDatasets: [] },
    status: { hasLineage: false, hasUnresolvedReferences: false, isPartial: false },
  }),
}));
jest.mock("../../providers/ToastProvider", () => ({
  useToastContext: () => ({ showToast: jest.fn() }),
}));
jest.mock("../../components/datasets/catalog/useDatasetResolvedSchema", () => ({
  useDatasetResolvedSchema: () => ({
    fields: [],
    geometryType: null,
    fetching: false,
    unsupportedMessage: null,
  }),
}));
jest.mock("../../components/datasets/catalog/DatasetSchemaPanel", () => ({
  DatasetSchemaPanel: () => null,
}));
jest.mock("../../components/datasets/catalog/DatasetTablePreview", () => ({
  DatasetTablePreview: () => null,
}));
jest.mock("../../services/datasetCatalog", () => {
  const actual = jest.requireActual("../../services/datasetCatalog");
  return {
    ...actual,
    datasetCatalogApi: {
      ...actual.datasetCatalogApi,
      getDataset: jest.fn(() => new Promise(() => {})),
      datasetUsage: jest.fn(() =>
        Promise.resolve([
          { dataflowId: "flow-other", dataflowName: "Other flow", nodeCount: 1, nodes: [] },
        ])
      ),
    },
  };
});

import { DatasetDetailModal } from "../../components/datasets/catalog/DatasetDetailModal";
import type { DatasetCatalogItem } from "../../services/datasetCatalog";

const PORTAL = "/catalog/lakes/lake.a.portal%401";

const dataset: DatasetCatalogItem = {
  id: "imported.xabc",
  title: "Bike Routes",
  origin: "imported",
  format: "csv",
  uri: "curio://datasets/imported.xabc",
  consumerNodeIds: [],
  updatedAt: new Date().toISOString(),
  tags: [],
  installed: false,
  lakeSource: {
    lakeId: "lake.a.portal@1",
    lakeName: "Alpha Portal",
    resourceId: "abcd-1234",
    resourceUrl: "https://alpha.example/d/abcd-1234",
  },
};

let location = "";
const LocationProbe: React.FC = () => {
  const loc = useLocation();
  location = `${loc.pathname}${loc.search}`;
  return null;
};

function renderModal(
  entry: string,
  props: { unsavedChanges?: boolean; fallbackDataset?: DatasetCatalogItem | null } = {},
) {
  const onClose = jest.fn();
  render(
    <MemoryRouter initialEntries={[entry]}>
      <Routes>
        <Route
          path="*"
          element={
            <DatasetDetailModal
              datasetId={dataset.id}
              fallbackDataset={dataset}
              onClose={onClose}
              {...props}
            />
          }
        />
      </Routes>
      <LocationProbe />
    </MemoryRouter>
  );
  return { onClose };
}

const details = () => screen.getByRole("dialog", { name: "Dataset details" });
const portalLink = () => within(details()).getByRole("link", { name: "Alpha Portal" });

beforeEach(() => {
  location = "";
});

describe("the portal link in a downloaded dataset's details", () => {
  test("closes the modal on the way to the portal", () => {
    const { onClose } = renderModal("/catalog/data");
    fireEvent.click(portalLink());
    expect(onClose).toHaveBeenCalled();
    expect(location).toBe(PORTAL);
  });

  test("on the portal's own page only closes, and keeps the search", () => {
    const { onClose } = renderModal(`${PORTAL}?q=bike`);
    fireEvent.click(portalLink());
    expect(onClose).toHaveBeenCalled();
    expect(location).toBe(`${PORTAL}?q=bike`);
  });

  test("leaves a new-tab click to the browser", () => {
    const { onClose } = renderModal("/catalog/data");
    fireEvent.click(portalLink(), { ctrlKey: true });
    expect(onClose).not.toHaveBeenCalled();
  });

  test("the resource link says it opens elsewhere", () => {
    renderModal("/catalog/data");
    const link = within(details()).getByRole("link", { name: "abcd-1234 ↗" });
    expect(link).toHaveAttribute("target", "_blank");
  });
});

describe("leaving a dataflow with unsaved changes from its details", () => {
  test("asks first, and staying keeps everything where it was", () => {
    const { onClose } = renderModal("/dataflow/flow-1", { unsavedChanges: true });
    fireEvent.click(portalLink());

    expect(screen.getByRole("dialog", { name: "Discard unsaved changes?" })).toBeInTheDocument();
    expect(location).toBe("/dataflow/flow-1");

    fireEvent.click(screen.getByRole("button", { name: "Stay here" }));
    expect(screen.queryByRole("dialog", { name: "Discard unsaved changes?" })).toBeNull();
    expect(onClose).not.toHaveBeenCalled();
    expect(location).toBe("/dataflow/flow-1");
  });

  test("discarding goes on, and closes the modal", () => {
    const { onClose } = renderModal("/dataflow/flow-1", { unsavedChanges: true });
    fireEvent.click(portalLink());
    fireEvent.click(screen.getByRole("button", { name: "Discard and continue" }));

    expect(onClose).toHaveBeenCalled();
    expect(location).toBe(PORTAL);
  });

  test("a dataflow that uses the dataset is a way out too", async () => {
    const { onClose } = renderModal("/dataflow/flow-1", { unsavedChanges: true });
    fireEvent.click(within(details()).getByRole("button", { name: "Lineage" }));
    fireEvent.click(await within(details()).findByRole("link", { name: "Other flow" }));

    expect(screen.getByRole("dialog", { name: "Discard unsaved changes?" })).toBeInTheDocument();
    expect(location).toBe("/dataflow/flow-1");
    expect(onClose).not.toHaveBeenCalled();
  });

  test("with nothing unsaved, it simply goes", () => {
    const { onClose } = renderModal("/dataflow/flow-1");
    fireEvent.click(portalLink());
    expect(screen.queryByRole("dialog", { name: "Discard unsaved changes?" })).toBeNull();
    expect(onClose).toHaveBeenCalled();
    expect(location).toBe(PORTAL);
  });
});

describe("a link to a dataset that does not exist", () => {
  test("says the dataset was not found, not the server's 404", async () => {
    // eslint-disable-next-line @typescript-eslint/no-var-requires
    const { datasetCatalogApi } = require("../../services/datasetCatalog");
    datasetCatalogApi.getDataset.mockImplementationOnce(() =>
      Promise.reject(Object.assign(new Error("HTTP 404"), { status: 404 })),
    );
    renderModal("/catalog/data/data.nope", { fallbackDataset: null });
    expect(await within(details()).findByText("Dataset not found.")).toBeInTheDocument();
    expect(within(details()).queryByText("HTTP 404")).toBeNull();
  });
});

describe("the canvas drawer tells the modal", () => {
  test("whether the dataflow has unsaved changes", () => {
    const src = fs.readFileSync(
      path.resolve(__dirname, "../../components/datasets/catalog/DatasetCatalogDrawer.tsx"),
      "utf8"
    );
    expect(src).toContain("unsavedChanges={projectDirty}");
  });
});
