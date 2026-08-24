/**
 * DatasetDetailPanel + the backend cross-dataflow usage section.
 *
 * `DatasetDetailPanel.test.tsx` mocks `DatasetDataflowUsage` away on purpose so
 * its cases cover live-canvas lineage without an async fetch firing mid-render.
 * That leaves two things untested at any layer:
 *
 *   * the fallback merge in `DatasetDetailPanel` - live-canvas consumers are
 *     preferred, and the backend `/usage` rows populate the downstream list only
 *     when the canvas resolved none (the standalone catalog page, or a dataflow
 *     that merely imported the dataset), and
 *   * `DatasetDataflowUsageSection` itself: the "Used in dataflows (N)" list,
 *     its dataflow links, and the "Produced here" row a dataflow gets when it
 *     owns the dataset but no node consumes it.
 *
 * So this file renders the REAL usage section and stubs only the network call
 * (`datasetCatalogApi.datasetUsage`). It needs a router, because each row links
 * to its dataflow.
 *
 * The resolver behind the fallback (`downstreamFromDataflowUsage`) is unit
 * tested in `src/tests/services/datasetLineageResolver.test.ts`; what is
 * asserted here is only what the panel does with its result.
 */
import React from "react";
import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import "@testing-library/jest-dom";

jest.mock("../../services/datasetLineage/useDatasetLineage", () => ({
  useDatasetLineage: jest.fn(),
}));
jest.mock("../../providers/ToastProvider", () => ({
  useToastContext: () => ({ showToast: jest.fn() }),
}));
jest.mock("../../components/datasets/catalog/useDatasetResolvedSchema", () => ({
  useDatasetResolvedSchema: jest.fn(() => ({
    fields: [{ name: "id", type: "INTEGER", nullable: false }],
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
import {
  datasetCatalogApi,
  type DatasetCatalogItem,
  type DatasetDataflowUsageRef,
} from "../../services/datasetCatalog";
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

/** One backend `/usage` row: a dataflow with one consumer node.
 *
 * The node type is the legacy uppercase form, as the sibling test file's
 * fixtures use, because `formatNodeTypeLabel` is what turns a raw type into the
 * label the UI shows ("DATA_TRANSFORMATION" -> "Data Transformation") and this
 * keeps the expected strings readable. A backend row carries no node *name*,
 * which is why the card below falls back to "Node <first 8 of the id>".
 */
function backendUsage(
  overrides: Partial<DatasetDataflowUsageRef> = {},
): DatasetDataflowUsageRef {
  return {
    dataflowId: "flow-9",
    dataflowName: "Saved Accessibility Flow",
    nodeCount: 1,
    nodes: [{ nodeId: "node-9", nodeType: "DATA_TRANSFORMATION" }],
    ...overrides,
  };
}

function renderPanel(lineage: DatasetLineage, dataset = catalogItem()) {
  mockUseDatasetLineage.mockReturnValue(lineage);
  return render(
    <MemoryRouter>
      <DatasetDetailPanel dataset={dataset} variant="modal" dataflowId="flow-1" />
    </MemoryRouter>,
  );
}

/** The sidebar column, which is where the lineage summary lives. */
const sidebar = () => screen.getByRole("complementary", { name: "Dataset info" });

describe("DatasetDetailPanel backend usage fallback", () => {
  let usageSpy: jest.SpyInstance;

  beforeEach(() => {
    mockUseDatasetLineage.mockReset();
    usageSpy = jest.spyOn(datasetCatalogApi, "datasetUsage");
  });

  afterEach(() => {
    usageSpy.mockRestore();
  });

  it("populates the downstream list from backend usage when the canvas resolved none", async () => {
    usageSpy.mockResolvedValue([backendUsage()]);
    renderPanel(lineageFixture());

    // The summary counts BOTH the nodes and the dataflows, so it is the single
    // value that proves downstreamFromDataflowUsage filled in consumingDataflows
    // as well as consumingNodes (otherwise it reads "in 0 dataflows").
    expect(
      await within(sidebar()).findByText("Used by 1 node in 1 dataflow"),
    ).toBeInTheDocument();
    expect(
      within(sidebar()).getByText("Downstream usage (1)"),
    ).toBeInTheDocument();
    const downstream = within(sidebar()).getByText("Downstream usage (1)")
      .parentElement as HTMLElement;
    // No node name on a backend row, so the card falls back to the sliced id
    // and carries the type as its badge.
    expect(within(downstream).getByText("Node node-9")).toBeInTheDocument();
    expect(within(downstream).getByText("Data Transformation")).toBeInTheDocument();
    expect(
      within(downstream).queryByText(
        "No nodes or dataflows are currently using this dataset.",
      ),
    ).not.toBeInTheDocument();

    // ...and the usage section itself, which the sibling test file stubs out.
    const usage = within(sidebar()).getByRole("region", {
      name: "Dataflows using this dataset",
    });
    expect(within(usage).getByText("Used in dataflows (1)")).toBeInTheDocument();
    expect(
      within(usage).getByRole("link", { name: "Saved Accessibility Flow" }),
    ).toHaveAttribute("href", "/dataflow/flow-9");
    expect(
      within(usage).getByText("Consumed by Data Transformation"),
    ).toBeInTheDocument();
  });

  it("prefers live-canvas consumers over backend usage", async () => {
    usageSpy.mockResolvedValue([backendUsage()]);
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

    // The section still renders (it is cross-dataflow context, not a consumer
    // list), so wait on it rather than on the downstream list - that way the
    // negative assertion below runs after the fetch resolved, not before it.
    expect(
      await within(sidebar()).findByText("Used in dataflows (1)"),
    ).toBeInTheDocument();

    const downstream = within(sidebar()).getByText("Downstream usage (1)")
      .parentElement as HTMLElement;
    expect(within(downstream).getByText("Spatial Join")).toBeInTheDocument();
    // The backend row must NOT be merged in alongside the live one: the fallback
    // is all-or-nothing, so a live consumer suppresses it entirely.
    expect(within(downstream).queryByText("Data Transformation")).not.toBeInTheDocument();
    expect(within(sidebar()).getByText("Used by 1 node in 1 dataflow")).toBeInTheDocument();
  });

  it("does not count a dataflow that owns the dataset but consumes it nowhere", async () => {
    // What the backend returns for the dataflow the dataset is installed in
    // while nothing is wired downstream of its loader: it "uses" the dataset,
    // so it gets a row, but with no consumer nodes.
    usageSpy.mockResolvedValue([backendUsage({ nodeCount: 0, nodes: [] })]);
    renderPanel(lineageFixture());

    const usage = await within(sidebar()).findByRole("region", {
      name: "Dataflows using this dataset",
    });
    expect(within(usage).getByText("Produced here")).toBeInTheDocument();

    // The point: a nodeless row is listed but is not a consumer, so the
    // downstream list stays empty instead of reading "Used by 0 nodes in 1
    // dataflow" (or worse, inventing a consumer). The empty sentence renders
    // twice in this column - as the summary and inside the group - so assert it
    // inside the group and pin the summary by what it is NOT.
    const downstream = within(sidebar()).getByText("Downstream usage (0)")
      .parentElement as HTMLElement;
    expect(
      within(downstream).getByText(
        "No nodes or dataflows are currently using this dataset.",
      ),
    ).toBeInTheDocument();
    expect(within(sidebar()).queryByText(/^Used by /)).not.toBeInTheDocument();
  });
});
