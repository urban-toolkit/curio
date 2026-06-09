import React from "react";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom";

jest.mock("../../services/datasetLineage/useDatasetLineage", () => ({
  useDatasetLineage: jest.fn(),
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
    expect(screen.getByText("Data Flows")).toBeInTheDocument();
    expect(
      screen.getByText("Dataflows that generate or consume this dataset"),
    ).toBeInTheDocument();
    expect(screen.getByText("Consumed by (1)")).toBeInTheDocument();
  });
});
