/**
 * A dataset's details, opened on the canvas, read the dataflow of the canvas by
 * the rule its Data Catalog palette and drawer list with (`useAgentsDataflowId`):
 * the owner's canvas the dataflow it saves, an invited editor's the dataflow its
 * route opened, though the editor's canvas saves none, and a watcher's none.
 * On an editor's canvas the details of one of the dataflow's datasets then load
 * and preview: with no dataflow, the backend answers 404 for a dataset of the
 * owner's.
 *
 * The test opens the same dataset on three canvases of alice's dataflow, hers,
 * an editor's and a watcher's, and compares what each one's details asked for.
 */
import React, { useEffect } from "react";
import { act, render } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

let mockFlow: Record<string, unknown> = {};
jest.mock("../../providers/FlowProvider", () => ({
  useFlowContext: () => ({
    projectId: null,
    viewerMode: "owner",
    projectDirty: false,
    whenChangesKept: undefined,
    outputs: [],
    nodes: [],
    defaultSaveOutputDataset: false,
    ...mockFlow,
  }),
}));
// The tab's role in the dataflow's room.
let mockRole: string | null = null;
jest.mock("../../providers/CollaborationProvider", () => ({
  useCollab: () => ({
    connected: false,
    users: [],
    lockedNodes: {},
    role: mockRole,
    onRemote: () => () => undefined,
  }),
}));
jest.mock("../../providers/ToastProvider", () => ({
  useToastContext: () => ({ showToast: jest.fn() }),
}));
jest.mock("../../utils/saveOutputDataset", () => ({ buildSaveableLiveOutputs: () => undefined }));
// The panel's parts that read on their own, stubbed as datasetDetailLinks.test.tsx
// stubs them; the Table Preview and the schema sample record the dataflow
// they would read through.
jest.mock("../../services/datasetLineage/useDatasetLineage", () => ({
  useDatasetLineage: () => ({
    datasetId: "imported.xstreettrees",
    upstream: { generatingNode: null, sourceDatasets: [], origin: "imported", originLabel: "Imported" },
    downstream: { consumingNodes: [], consumingDataflows: [], derivedDatasets: [] },
    status: { hasLineage: false, hasUnresolvedReferences: false, isPartial: false },
  }),
}));
const mockSchemaSamples: Array<string | null> = [];
jest.mock("../../components/datasets/catalog/useDatasetResolvedSchema", () => ({
  useDatasetResolvedSchema: (_dataset: unknown, dataflowId?: string | null) => {
    mockSchemaSamples.push(dataflowId ?? null);
    return { fields: [], geometryType: null, fetching: false, unsupportedMessage: null };
  },
}));
jest.mock("../../components/datasets/catalog/DatasetSchemaPanel", () => ({
  DatasetSchemaPanel: () => null,
}));
const mockTablePreviews: Array<string | null> = [];
jest.mock("../../components/datasets/catalog/DatasetTablePreview", () => ({
  DatasetTablePreview: ({ dataflowId }: { dataflowId?: string | null }) => {
    mockTablePreviews.push(dataflowId ?? null);
    return null;
  },
}));
const mockDetailReads: Array<string | null> = [];
jest.mock("../../services/datasetCatalog", () => {
  const actual = jest.requireActual("../../services/datasetCatalog");
  return {
    ...actual,
    datasetCatalogApi: {
      ...actual.datasetCatalogApi,
      getDataset: jest.fn((_id: string, query?: { dataflowId?: string | null }) => {
        mockDetailReads.push(query?.dataflowId ?? null);
        return Promise.resolve(mockStreetTrees);
      }),
      listDatasetDefaults: jest.fn(() => Promise.resolve({ datasets: [] })),
      datasetUsage: jest.fn(() => Promise.resolve([])),
    },
  };
});

import { CanvasDatasetDetailsProvider } from "../../components/datasets/catalog/CanvasDatasetDetailsProvider";
import { useDatasetDetails } from "../../components/datasets/catalog/datasetDetailsContext";
import { clearCurrentProject, setCurrentProject } from "../../registry/projectPackagesStore";

const ALICES = "alices-dataflow";

/** A dataset of alice's that her dataflow lists. */
const mockStreetTrees = {
  id: "imported.xstreettrees",
  title: "Street trees",
  origin: "imported" as const,
  format: "csv" as const,
  uri: "curio://datasets/imported.xstreettrees@1",
  dirName: "imported.xstreettrees@1",
  installed: true,
  consumerNodeIds: [],
  tags: [],
  updatedAt: "2026-10-29T00:00:00Z",
};

type Canvas = "owner" | "editor" | "watcher";

/** Three tabs on alice's dataflow, each opened from its route. Only hers saves
 *  it, so only hers has the flow state's `projectId`. */
const CANVASES: Record<Canvas, { flow: Record<string, unknown>; role: string | null }> = {
  owner: { flow: { projectId: ALICES, viewerMode: "owner" }, role: "owner" },
  editor: { flow: { projectId: null, viewerMode: "shared" }, role: "editor" },
  watcher: { flow: { projectId: null, viewerMode: "shared" }, role: "watcher" },
};

/** A palette row's click: open the dataset's details. */
function OpenStreetTrees() {
  const { openDatasetDetails } = useDatasetDetails();
  useEffect(() => {
    openDatasetDetails(mockStreetTrees.id, { fallbackDataset: mockStreetTrees as never });
  }, [openDatasetDetails]);
  return null;
}

const once = (values: Array<string | null>) => Array.from(new Set(values));

afterEach(() => {
  clearCurrentProject();
  mockFlow = {};
  mockRole = null;
});

test("the details of a dataflow's dataset load and preview through the dataflow on the owner's canvas and an editor's, and through none on a watcher's", async () => {
  const seen = {} as Record<Canvas, { details: Array<string | null>; tablePreview: Array<string | null>; schemaSample: Array<string | null> }>;
  for (const canvas of Object.keys(CANVASES) as Canvas[]) {
    mockFlow = CANVASES[canvas].flow;
    mockRole = CANVASES[canvas].role;
    setCurrentProject(ALICES, []);
    mockDetailReads.length = 0;
    mockTablePreviews.length = 0;
    mockSchemaSamples.length = 0;
    const view = render(
      <MemoryRouter>
        <CanvasDatasetDetailsProvider>
          <OpenStreetTrees />
        </CanvasDatasetDetailsProvider>
      </MemoryRouter>,
    );
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    seen[canvas] = {
      details: once(mockDetailReads),
      tablePreview: once(mockTablePreviews),
      schemaSample: once(mockSchemaSamples),
    };
    view.unmount();
  }

  expect(seen).toEqual({
    owner: { details: [ALICES], tablePreview: [ALICES], schemaSample: [ALICES] },
    editor: { details: [ALICES], tablePreview: [ALICES], schemaSample: [ALICES] },
    watcher: { details: [null], tablePreview: [null], schemaSample: [null] },
  });
});
