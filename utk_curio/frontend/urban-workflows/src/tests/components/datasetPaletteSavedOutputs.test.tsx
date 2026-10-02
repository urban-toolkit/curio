import React from "react";
import { render, screen, within } from "@testing-library/react";

/**
 * #217 / #441: the Tools rail's "Data Catalog" list shows this dataflow's
 * saved outputs under "Saved outputs". A run's "Adding ..." placeholder is
 * replaced there by the output's row instead of vanishing, and a node's
 * OUTPUT pill reveals that row, or opens the dataset's details when no row
 * lists it.
 */

jest.mock("../../components/menus/nodes/toolsMenuPackagePalette", () => ({
  OVERLAY_TRIGGER_DELAY_PROPS: { delay: { show: 0, hide: 0 } },
}));
jest.mock("../../components/menus/nodes/datasetPalette/DatasetPaletteRows", () => ({
  DatasetRow: ({ dataset }: { dataset: { id: string; title: string } }) => (
    <div data-dataset-id={dataset.id}>{dataset.title}</div>
  ),
  DatasetGroupRow: () => null,
}));
jest.mock("../../components/menus/nodes/datasetPalette/DatasetInstallingRow", () => ({
  DatasetInstallingRow: ({ pending }: { pending: { label: string } }) => (
    <div role="status" aria-label={`Adding ${pending.label}`} />
  ),
}));

let mockPending: Array<Record<string, unknown>> = [];
jest.mock("../../providers/FlowProvider", () => ({
  useFlowContext: () => ({
    projectId: "flow-1",
    outputs: [],
    nodes: [],
    defaultSaveOutputDataset: false,
    pendingInstalls: mockPending,
  }),
}));
jest.mock("../../providers/datasetCatalog", () => ({
  useDatasetCatalogDrawer: () => ({ openDatasetCatalogDrawer: jest.fn() }),
}));
let mockRevealId: string | null = null;
const mockSetRevealId = jest.fn();
jest.mock("../../providers/DatasetPaletteContext", () => ({
  useDatasetPalette: () => ({ datasetRevealId: mockRevealId, setDatasetRevealId: mockSetRevealId }),
}));
const mockOpenDetails = jest.fn();
jest.mock("../../components/datasets/catalog/datasetDetailsContext", () => ({
  useDatasetDetails: () => ({ openDatasetDetails: mockOpenDetails }),
}));
let mockItems: Array<Record<string, unknown>> = [];
jest.mock("../../services/datasetCatalog", () => ({
  DATASET_CATALOG_REFRESH_EVENT: "curio:dataset-catalog-refresh",
  useDatasetCatalog: () => ({ items: mockItems, loading: false, refreshing: false, reload: jest.fn() }),
  prefetchDatasetCatalog: jest.fn(),
  groupDatasetsForPalette: (rows: unknown[]) => rows.map((dataset) => ({ kind: "dataset", dataset })),
  isInThisDataflow: (item: { installed?: boolean }) => item.installed === true,
  isUserInstalledDataset: () => false,
  sortDatasetPaletteEntries: (rows: unknown[]) => rows,
}));
jest.mock("../../utils/saveOutputDataset", () => ({ buildSaveableLiveOutputs: () => undefined }));

import { DatasetsPaletteDropdown } from "../../components/menus/nodes/datasetPalette/DatasetsPaletteDropdown";

const IN_PROJECT = {
  id: "data.utk.chicago-boundary@1",
  title: "Chicago boundary",
  origin: "hub",
  format: "geojson",
  installed: true,
};
const SAVED_HERE = {
  id: "computed.flow-1.n1@1",
  title: "Output of n1",
  origin: "computed",
  format: "json",
  dirName: "computed.flow-1.n1@1",
  producerNodeId: "n1",
  producerDataflowId: "flow-1",
};
// Same node id, another dataflow (#168): never listed here.
const SAVED_ELSEWHERE = {
  id: "computed.flow-2.n1@1",
  title: "Output of n1 elsewhere",
  origin: "computed",
  format: "json",
  dirName: "computed.flow-2.n1@1",
  producerNodeId: "n1",
  producerDataflowId: "flow-2",
};
// A live output never saved to the store.
const UNSAVED = {
  id: "computed.flow-1.n2@1",
  title: "Unsaved output of n2",
  origin: "computed",
  format: "json",
  producerNodeId: "n2",
};

function renderOpen() {
  return render(<DatasetsPaletteDropdown open setOpen={() => {}} />);
}

function savedGroup() {
  const summary = screen.getByText("Saved outputs");
  return summary.closest("details") as HTMLElement;
}

beforeEach(() => {
  mockPending = [];
  mockRevealId = null;
  mockItems = [IN_PROJECT, SAVED_HERE, SAVED_ELSEWHERE, UNSAVED];
  jest.clearAllMocks();
});

test("lists this dataflow's saved outputs under Saved outputs, and nothing else there", () => {
  renderOpen();
  const group = savedGroup();
  expect(within(group).getByText("Output of n1")).toBeTruthy();
  expect(within(group).queryByText("Output of n1 elsewhere")).toBeNull();
  expect(within(group).queryByText("Unsaved output of n2")).toBeNull();
  expect(within(group).queryByText("Chicago boundary")).toBeNull();
  expect(screen.getByText("Chicago boundary")).toBeTruthy();
});

test("the badge counts both groups", () => {
  renderOpen();
  const trigger = screen.getByTitle("Close dataset palette");
  expect(trigger.textContent).toContain("2");
});

test("a run's placeholder is replaced by its saved output's row", () => {
  mockPending = [{ key: "n1", producerNodeId: "n1", label: "Python Computation", startedAt: 0 }];
  renderOpen();
  expect(screen.queryByRole("status")).toBeNull();
  expect(within(savedGroup()).getByText("Output of n1")).toBeTruthy();
});

test("a run's placeholder waits under Saved outputs until its row lands", () => {
  mockItems = [IN_PROJECT];
  mockPending = [{ key: "n3", producerNodeId: "n3", label: "Python Computation", startedAt: 0 }];
  renderOpen();
  expect(within(savedGroup()).getByRole("status", { name: "Adding Python Computation" })).toBeTruthy();
});

test("a pill whose dataset no row lists opens the dataset's details instead", () => {
  const raf = jest
    .spyOn(window, "requestAnimationFrame")
    .mockImplementation((callback: FrameRequestCallback) => {
      callback(0);
      return 0;
    });
  mockItems = [IN_PROJECT];
  mockRevealId = "computed.flow-1.gone@1";
  renderOpen();
  expect(mockOpenDetails).toHaveBeenCalledWith("computed.flow-1.gone@1", undefined);
  expect(mockSetRevealId).toHaveBeenCalledWith(null);
  raf.mockRestore();
});

test("a pill whose dataset is listed reveals the row and opens nothing", () => {
  const raf = jest
    .spyOn(window, "requestAnimationFrame")
    .mockImplementation((callback: FrameRequestCallback) => {
      callback(0);
      return 0;
    });
  Element.prototype.scrollIntoView = jest.fn();
  mockRevealId = SAVED_HERE.id;
  renderOpen();
  expect(mockOpenDetails).not.toHaveBeenCalled();
  expect(Element.prototype.scrollIntoView).toHaveBeenCalled();
  raf.mockRestore();
});
