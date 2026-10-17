/**
 * The Data Catalog drawer's Remove names every dataflow whose nodes load the
 * dataset in their code alone, this one included, read from its canvas, as the
 * Model Catalog drawer's Remove does (`modelCatalogDrawer.test.tsx`).
 *
 * This dataflow's saved row cannot answer for it: the ref the Remove takes out
 * keeps the dataset in it, so the usage read counts it as kept.
 *
 * Code main lacks is reached through `require`, so main fails test by test.
 */
import { renderHook, act } from "@testing-library/react";

let mockNodes: Array<{ id: string; data: Record<string, unknown> }> = [];
let mockProjectName: string | null = "Street photos";

jest.mock("../../services/datasetCatalog", () => {
  const actual = jest.requireActual("../../services/datasetCatalog");
  return {
    ...actual,
    useDatasetCatalog: () => ({
      items: [],
      facets: { origin: {} },
      loading: false,
      refreshing: false,
      error: null,
      reload: jest.fn(async () => {}),
      install: jest.fn(),
      uninstall: jest.fn(),
      importDataset: jest.fn(),
    }),
  };
});

jest.mock("../../providers/ToastProvider", () => ({
  useToastContext: () => ({ showToast: jest.fn() }),
}));

jest.mock("../../providers/FlowProvider", () => ({
  useFlowContext: () => ({
    projectId: "p1",
    projectName: mockProjectName,
    ensureProjectId: jest.fn(async () => "p1"),
    setDataflowDatasets: jest.fn(),
    outputs: [],
    nodes: mockNodes,
    defaultSaveOutputDataset: false,
    pendingInstalls: [],
    beginPendingInstall: jest.fn(),
    endPendingInstall: jest.fn(),
  }),
}));

jest.mock("../../utils/saveOutputDataset", () => ({
  buildSaveableLiveOutputs: jest.fn(() => []),
}));

import { useDatasetCatalogDrawer } from "../../components/datasets/catalog/useDatasetCatalogDrawer";
import { datasetCatalogApi } from "../../services/datasetCatalog";

const BOUNDARY = "data.utk.chicago-boundary";

/** A shipped dataset in this dataflow, as the drawer's card holds it. */
const DATASET = {
  id: BOUNDARY,
  title: "Chicago boundary",
  origin: "imported" as const,
  format: "geojson" as const,
  dirName: `${BOUNDARY}@1`,
  consumerNodeIds: [],
  tags: [],
  updatedAt: "2026-01-01T00:00:00Z",
  installed: true,
};

/** Node code that loads the boundary, with no binding beside it. */
const LOADS_IT = `gdf = curio_load_data("${BOUNDARY}")\nreturn gdf`;

/** A computed dataset this dataflow's node `maker` saved. */
const COMPUTED = {
  id: "computed.p1.maker",
  title: "Maker output",
  origin: "computed" as const,
  format: "parquet" as const,
  dirName: "computed.p1.maker@1",
  producerNodeId: "maker",
  producerDataflowId: "p1",
  consumerNodeIds: [],
  tags: [],
  updatedAt: "2026-01-01T00:00:00Z",
  installed: true,
};

const computation = (code: string, extra: Record<string, unknown> = {}) => ({
  nodeType: "curio.builtin/computation-analysis@1",
  code,
  ...extra,
});

/** The three bindings a drop writes, each of which keeps the dataset. */
const BINDINGS: Array<[string, Record<string, unknown>]> = [
  ["datasetRefs", { datasetRefs: [BOUNDARY] }],
  ["appliedDatasets", { appliedDatasets: { [BOUNDARY]: { id: BOUNDARY, title: "Chicago boundary" } } }],
  ["datasetSource", { datasetSource: { datasetId: BOUNDARY, title: "Chicago boundary" } }],
];

let restoreUsage: (() => void) | null = null;

/** The Remove confirmation's body, once the usage read answered *usage*. */
async function removeBody(usage: unknown[] | Error): Promise<string> {
  const usageSpy = jest.spyOn(datasetCatalogApi, "datasetUsage");
  restoreUsage = () => usageSpy.mockRestore();
  if (usage instanceof Error) usageSpy.mockRejectedValue(usage);
  else usageSpy.mockResolvedValue(usage as never);
  const { result } = renderHook(() => useDatasetCatalogDrawer(true));
  await act(async () => {
    await result.current.onUninstall(DATASET as never);
  });
  expect(usageSpy).toHaveBeenCalledWith(BOUNDARY);
  return String(result.current.confirmAction?.body ?? "");
}

beforeEach(() => {
  mockNodes = [];
  mockProjectName = "Street photos";
});

afterEach(() => {
  restoreUsage?.();
  restoreUsage = null;
});

describe("the Data Catalog drawer's Remove names the dataflows that load the dataset in code alone", () => {
  test("this one from its canvas, the account's others from the usage read", async () => {
    // On the canvas: a node that loads the boundary in its code, with no binding.
    mockNodes = [{ id: "n1", data: computation(LOADS_IT) }];
    const body = await removeBody([
      // This dataflow as last saved: the ref the Remove takes out keeps the
      // dataset, so its row reads kept. Its canvas answers for it.
      { dataflowId: "p1", dataflowName: "Street photos, as saved", nodeCount: 1, codeOnly: false },
      { dataflowId: "p2", dataflowName: "Crosswalks", nodeCount: 1, codeOnly: true },
      { dataflowId: "p3", dataflowName: "Keeps the dataset", nodeCount: 1, codeOnly: false },
    ]);
    expect(body).toContain(
      "Nodes in Crosswalks, Street photos load this dataset in code. " +
        "That code is left as it is and will fail the next time those nodes run.",
    );
    expect(body).not.toContain("as saved");
    expect(body).not.toContain("Keeps the dataset");
  });

  test("this one's saved row never names it: edited since, its canvas loads the dataset no more", async () => {
    mockNodes = [{ id: "n1", data: computation("return 1") }];
    const body = await removeBody([
      { dataflowId: "p1", dataflowName: "Street photos, as saved", nodeCount: 1, codeOnly: true },
      { dataflowId: "p2", dataflowName: "Crosswalks", nodeCount: 1, codeOnly: true },
    ]);
    expect(body).toContain(
      "A node in Crosswalks loads this dataset in code. " +
        "That code is left as it is and will fail the next time it runs.",
    );
    expect(body).not.toContain("Street photos");
  });

  test("an unread usage still names this one, from its canvas", async () => {
    mockNodes = [{ id: "n1", data: computation(LOADS_IT) }];
    const body = await removeBody(new Error("offline"));
    expect(body).toContain(
      "A node in Street photos loads this dataset in code. " +
        "That code is left as it is and will fail the next time it runs.",
    );
  });

  test("a dataflow with no name is named Untitled dataflow", async () => {
    mockProjectName = null;
    mockNodes = [{ id: "n1", data: computation(LOADS_IT) }];
    const body = await removeBody([]);
    expect(body).toContain("A node in Untitled dataflow loads this dataset in code.");
  });

  test.each(BINDINGS)("a node bound to it by %s keeps it, so this one is not named", async (_name, binding) => {
    // The bound node keeps the dataset in this dataflow, as a usage read
    // counts a binding for any other dataflow, so the code of the first node
    // leaves nothing behind.
    mockNodes = [
      { id: "n1", data: computation(LOADS_IT) },
      { id: "n2", data: computation(LOADS_IT, binding) },
    ];
    const body = await removeBody([]);
    expect(body).not.toContain("in code");
  });
});

describe("canvasLoadsDatasetInCodeOnly", () => {
  const loadsInCodeOnly = (
    nodes: Array<{ id: string; data: Record<string, unknown> }>,
    dataset: object = DATASET,
    dataflowId: string | null = "p1",
  ): boolean =>
    require("../../services/datasetCatalog").canvasLoadsDatasetInCodeOnly(nodes, dataset, dataflowId);

  test("holds for a node whose code alone loads the dataset", () => {
    expect(loadsInCodeOnly([{ id: "n1", data: computation(LOADS_IT) }])).toBe(true);
    expect(loadsInCodeOnly([{ id: "n1", data: computation(`p = curio_data_path('${BOUNDARY}')`) }])).toBe(true);
  });

  test("reads the code a node runs: its own once it has any, else its template's", () => {
    expect(loadsInCodeOnly([{ id: "n1", data: { defaultCode: LOADS_IT } }])).toBe(true);
    expect(loadsInCodeOnly([{ id: "n1", data: { code: "return 1", defaultCode: LOADS_IT } }])).toBe(false);
  });

  test("does not hold for code that loads another dataset, or for no code", () => {
    expect(loadsInCodeOnly([{ id: "n1", data: computation('gdf = curio_load_data("data.utk.milan-mrt")') }])).toBe(false);
    expect(loadsInCodeOnly([{ id: "n1", data: { nodeType: "curio.builtin/vega-lite@1" } }])).toBe(false);
    expect(loadsInCodeOnly([])).toBe(false);
  });

  test.each(BINDINGS)("a node bound to it by %s keeps it", (_name, binding) => {
    expect(loadsInCodeOnly([{ id: "n1", data: computation(LOADS_IT, binding) }])).toBe(false);
    expect(
      loadsInCodeOnly([
        { id: "n1", data: computation(LOADS_IT) },
        { id: "n2", data: computation("return 1", binding) },
      ]),
    ).toBe(false);
  });

  test("the node of this dataflow that saved it keeps it", () => {
    const reader = { id: "reader", data: computation(`df = curio_load_data("${COMPUTED.id}")`) };
    expect(loadsInCodeOnly([{ id: "maker", data: computation("return df") }, reader], COMPUTED, "p1")).toBe(false);
    // A node of another dataflow with the same id did not save it.
    expect(loadsInCodeOnly([{ id: "maker", data: computation("return df") }, reader], COMPUTED, "p2")).toBe(true);
    // Nor does the reader alone, with its maker gone from the canvas.
    expect(loadsInCodeOnly([reader], COMPUTED, "p1")).toBe(true);
  });
});
