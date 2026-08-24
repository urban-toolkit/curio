import React from "react";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom";

jest.mock("../../services/datasetLineage/useDatasetLineage", () => ({
  useDatasetLineage: jest.fn(),
}));
jest.mock("../../providers/ToastProvider", () => ({
  useToastContext: () => ({ showToast: jest.fn() }),
}));
jest.mock("../../components/datasets/catalog/useDatasetResolvedSchema", () => ({
  useDatasetResolvedSchema: jest.fn(() => ({
    fields: [
      { name: "id", type: "INTEGER", nullable: false },
      { name: "name", type: "STRING", nullable: true },
      { name: "geometry", type: "GEOMETRY", nullable: false },
    ],
    geometryType: null,
    fetching: false,
    unsupportedMessage: null,
  })),
}));
jest.mock("../../components/datasets/catalog/DatasetSchemaPanel", () => ({
  DatasetSchemaPanel: () => <div data-testid="schema-panel" />,
}));
jest.mock("../../components/datasets/catalog/DatasetTablePreview", () => ({
  DatasetTablePreview: () => <div data-testid="table-preview" />,
}));
// Backend cross-dataflow usage fetches on mount; neutralize it so its async
// state update doesn't fire after render (these tests cover live lineage, not
// the backend usage section).
jest.mock("../../components/datasets/catalog/DatasetDataflowUsage", () => ({
  useDatasetDataflowUsage: () => [],
  DatasetDataflowUsageSection: () => null,
}));

import { DatasetDetailPanel } from "../../components/datasets/catalog/DatasetDetailPanel";
import { useDatasetLineage } from "../../services/datasetLineage/useDatasetLineage";
import type { DatasetCatalogItem } from "../../services/datasetCatalog";
import type {
  DatasetLineage,
  DatasetLineageNodeUsageRef,
} from "../../services/datasetLineage";

const mockUseDatasetLineage = useDatasetLineage as jest.MockedFunction<
  typeof useDatasetLineage
>;

function catalogItem(overrides: Partial<DatasetCatalogItem> = {}): DatasetCatalogItem {
  return {
    id: "ds-1",
    title: "Neighborhoods",
    origin: "hub",
    format: "geojson",
    uri: "curio://datasets/neighborhoods",
    consumerNodeIds: [],
    updatedAt: new Date().toISOString(),
    tags: ["geojson"],
    installed: true,
    ...overrides,
  };
}

function usageRef(
  overrides: Partial<DatasetLineageNodeUsageRef> = {},
): DatasetLineageNodeUsageRef {
  return {
    nodeId: "node-1",
    nodeName: "Spatial Join",
    nodeType: "COMPUTE_ANALYSIS",
    dataflowId: "flow-1",
    dataflowName: "Accessibility Analysis",
    usageType: "input",
    status: "active",
    ...overrides,
  };
}

function lineageFixture(overrides: Partial<DatasetLineage> = {}): DatasetLineage {
  return {
    datasetId: "ds-1",
    upstream: {
      generatingNode: null,
      sourceDatasets: [],
      origin: "hub",
      originLabel: "Imported",
    },
    downstream: {
      consumingNodes: [],
      consumingDataflows: [],
      derivedDatasets: [],
    },
    status: {
      hasLineage: false,
      hasUnresolvedReferences: false,
      isPartial: false,
    },
    ...overrides,
  };
}

function renderPanel(lineage: DatasetLineage, dataset = catalogItem()) {
  mockUseDatasetLineage.mockReturnValue(lineage);
  return render(
    <DatasetDetailPanel dataset={dataset} variant="modal" dataflowId="flow-1" />,
  );
}

describe("DatasetDetailPanel header actions", () => {
  beforeEach(() => {
    mockUseDatasetLineage.mockReset();
  });

  it("shows Unpublish (not Publish) for an already-published dataset", () => {
    renderPanel(lineageFixture(), catalogItem({ origin: "hub", installed: true }));
    expect(screen.getByRole("button", { name: "Unpublish" })).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Publish" }),
    ).not.toBeInTheDocument();
  });

  it("shows Publish for an unpublished dataset", () => {
    renderPanel(
      lineageFixture(),
      catalogItem({ origin: "computed", installed: false, publishedToHub: false }),
    );
    expect(
      screen.getByRole("button", { name: "Publish" }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Unpublish" })).not.toBeInTheDocument();
  });

  it("disables Export for multi-part bundle datasets", () => {
    renderPanel(lineageFixture(), catalogItem({ format: "bundle" }));
    expect(screen.getByRole("button", { name: "Export" })).toBeDisabled();
  });

  it("enables Export for a regular dataset", () => {
    renderPanel(lineageFixture(), catalogItem({ format: "parquet" }));
    expect(screen.getByRole("button", { name: "Export" })).toBeEnabled();
  });
});

describe("DatasetDetailPanel timestamps (record vs. source file)", () => {
  beforeEach(() => {
    mockUseDatasetLineage.mockReset();
  });

  it("uses createdAt (not updatedAt) for the Imported row", () => {
    renderPanel(
      lineageFixture(),
      catalogItem({
        createdAt: "2020-03-05T14:14:00Z",
        updatedAt: "2026-06-18T00:00:00Z",
      }),
    );
    const sidebar = within(screen.getByRole("complementary", { name: "Dataset info" }));
    const imported = sidebar.getByText("Imported", { selector: "dt" }).nextElementSibling;
    // The absolute Imported date reflects createdAt (2020), not updatedAt (2026).
    expect(imported).toHaveTextContent(/2020|Mar/);
    expect(imported).not.toHaveTextContent("2026");
  });

  it("shows a distinct Source updated row only when sourceUpdatedAt is present", () => {
    renderPanel(
      lineageFixture(),
      catalogItem({ sourceUpdatedAt: "2019-01-01T00:00:00Z" }),
    );
    const sidebar = within(screen.getByRole("complementary", { name: "Dataset info" }));
    expect(sidebar.getByText("Source updated")).toBeInTheDocument();
  });

  it("hides the Source updated row when sourceUpdatedAt is absent", () => {
    renderPanel(lineageFixture(), catalogItem({ sourceUpdatedAt: null }));
    const sidebar = within(screen.getByRole("complementary", { name: "Dataset info" }));
    expect(sidebar.queryByText("Source updated")).not.toBeInTheDocument();
  });
});

describe("DatasetDetailPanel lineage", () => {
  beforeEach(() => {
    mockUseDatasetLineage.mockReset();
  });

  it("renders real downstream usage in the sidebar", () => {
    renderPanel(
      lineageFixture({
        downstream: {
          consumingNodes: [
            usageRef(),
            usageRef({ nodeId: "node-2", nodeName: "Export GeoJSON", status: "stale" }),
          ],
          consumingDataflows: [
            {
              dataflowId: "flow-1",
              dataflowName: "Accessibility Analysis",
              nodeIds: ["node-1", "node-2"],
              usageCount: 2,
              status: "stale",
            },
          ],
          derivedDatasets: [],
        },
        status: { hasLineage: true, hasUnresolvedReferences: false, isPartial: false },
      }),
    );

    const sidebar = within(screen.getByRole("complementary", { name: "Dataset info" }));
    // Column count must come from the shared resolved schema (3 mocked fields).
    expect(sidebar.getByText("Columns").nextElementSibling).toHaveTextContent("3");
    expect(sidebar.getByText("Used by 2 nodes in 1 dataflow")).toBeInTheDocument();
    expect(sidebar.getByText("Spatial Join")).toBeInTheDocument();
    expect(sidebar.getByText("Export GeoJSON")).toBeInTheDocument();
    expect(sidebar.getByText("Stale")).toBeInTheDocument();
  });

  it("shows a real empty state without the old Spatial Filter stub", () => {
    renderPanel(lineageFixture());

    expect(
      screen.getAllByText("No nodes or dataflows are currently using this dataset.").length,
    ).toBeGreaterThan(0);
    expect(screen.queryByText("Spatial Filter")).not.toBeInTheDocument();
  });

  it("shows the partial state for unresolved references", () => {
    renderPanel(
      lineageFixture({
        downstream: {
          consumingNodes: [
            usageRef({ nodeId: "ghost", nodeName: undefined, status: "unresolved" }),
          ],
          consumingDataflows: [],
          derivedDatasets: [],
        },
        status: { hasLineage: true, hasUnresolvedReferences: true, isPartial: true },
      }),
    );

    expect(
      screen.getByText(
        "Lineage is partially available. Some node or dataflow references could not be resolved.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByText("Unresolved")).toBeInTheDocument();
  });

  it("renders the real generating node upstream", () => {
    renderPanel(
      lineageFixture({
        upstream: {
          generatingNode: {
            nodeId: "producer-1",
            nodeName: "Join Attributes",
            nodeType: "COMPUTE_ANALYSIS",
          },
          sourceDatasets: [],
          origin: "computed",
          originLabel: "Computed",
        },
        status: { hasLineage: true, hasUnresolvedReferences: false, isPartial: false },
      }),
      catalogItem({ origin: "computed", producerNodeId: "producer-1" }),
    );

    expect(screen.getByText(/Generated by\s+Join Attributes/)).toBeInTheDocument();
  });

  it("does not label an installed computed node output as installed from the catalog", () => {
    renderPanel(
      lineageFixture({
        upstream: {
          generatingNode: {
            nodeId: "producer-1",
            nodeName: "Data Loading",
            nodeType: "DATA_LOADING",
          },
          sourceDatasets: [],
          origin: "computed",
          originLabel: "Computed",
        },
        status: { hasLineage: true, hasUnresolvedReferences: false, isPartial: false },
      }),
      catalogItem({
        origin: "computed",
        format: "parquet",
        installed: true,
        producerNodeId: "producer-1",
      }),
    );

    expect(screen.getByText(/Generated by\s+Data Loading/)).toBeInTheDocument();
    expect(screen.queryByText("Added from Data Catalog")).not.toBeInTheDocument();
  });

  it("labels a dataset installed from the catalog as installed from the catalog", () => {
    renderPanel(
      lineageFixture({
        upstream: {
          generatingNode: null,
          sourceDatasets: [],
          origin: "imported",
          originLabel: "Imported",
        },
      }),
      catalogItem({ origin: "imported", installed: true }),
    );

    expect(screen.getAllByText("Added from Data Catalog").length).toBeGreaterThan(0);
  });

  it("does not claim an available (not installed) catalog dataset is installed", () => {
    renderPanel(
      lineageFixture({
        upstream: {
          generatingNode: null,
          sourceDatasets: [],
          origin: "hub",
          originLabel: "Imported",
        },
      }),
      catalogItem({ origin: "hub", installed: false }),
    );

    expect(screen.queryByText("Added from Data Catalog")).not.toBeInTheDocument();
  });

  it("lists the inputs that fed the producing node", () => {
    // upstreamInputs is the only record of what a computed dataset was built
    // from; before this it was persisted on every manifest and rendered nowhere.
    renderPanel(
      lineageFixture({
        upstream: {
          generatingNode: { nodeId: "producer-1", nodeName: "Python Computation" },
          inputNodes: [
            { nodeId: "feeder-1", nodeName: "Data Loading", nodeType: "DATA_LOADING" },
          ],
          sourceDatasets: [
            { datasetId: "data.urbanlab.acs", title: "acs" },
          ],
          origin: "computed",
          originLabel: "Computed",
        },
      }),
      catalogItem({ origin: "computed" }),
    );

    // Both columns render UpstreamCards, so count instead of asserting one node.
    expect(screen.getAllByText("Inputs (2)").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Data Loading").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Node input").length).toBeGreaterThan(0);
    expect(screen.getAllByText("acs").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Dataset input").length).toBeGreaterThan(0);
  });

  it("names an input node by its id when nothing resolved a label", () => {
    renderPanel(
      lineageFixture({
        upstream: {
          generatingNode: null,
          inputNodes: [{ nodeId: "abcdefgh-1234-5678" }],
          sourceDatasets: [],
          origin: "computed",
          originLabel: "Computed",
        },
      }),
      catalogItem({ origin: "computed" }),
    );

    expect(screen.getAllByText("Inputs (1)").length).toBeGreaterThan(0);
    expect(screen.getAllByText("node abcdefgh").length).toBeGreaterThan(0);
  });

  it("shows no inputs section for a dataset that records none", () => {
    // The imported case, which is most datasets: no Inputs label at all rather
    // than an empty one.
    renderPanel(lineageFixture());

    expect(screen.queryByText(/^Inputs \(/)).not.toBeInTheDocument();
    expect(screen.queryByText("Node input")).not.toBeInTheDocument();
    expect(screen.queryByText("Dataset input")).not.toBeInTheDocument();
  });

  it("switches to the expanded lineage view on the Lineage tab", async () => {
    const user = userEvent.setup();
    renderPanel(
      lineageFixture({
        downstream: {
          consumingNodes: [usageRef()],
          consumingDataflows: [
            {
              dataflowId: "flow-1",
              dataflowName: "Accessibility Analysis",
              nodeIds: ["node-1"],
              usageCount: 1,
              status: "active",
            },
          ],
          derivedDatasets: [],
        },
        status: { hasLineage: true, hasUnresolvedReferences: false, isPartial: false },
      }),
    );

    expect(screen.getByTestId("table-preview")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Lineage" }));

    expect(screen.queryByTestId("table-preview")).not.toBeInTheDocument();
    expect(screen.getByText("Dataflows")).toBeInTheDocument();
    expect(
      screen.getByText("Dataflows that generate or consume this dataset"),
    ).toBeInTheDocument();
    expect(screen.getByText("Consumed by (1)")).toBeInTheDocument();
  });
});
