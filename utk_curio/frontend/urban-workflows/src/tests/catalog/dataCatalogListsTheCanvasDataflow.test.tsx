/**
 * The Data Catalog's palette and drawer list the dataflow of the canvas by the
 * rule its agents and its runs follow (`useAgentsDataflowId`): the owner's
 * canvas lists the dataflow it saves, an invited editor's the dataflow its
 * route opened, though the editor's canvas saves none (`loadSharedProject`),
 * and a watcher's lists none. For the owner and her editors the backend then
 * lists the datasets the dataflow lists, as installed, beside the reader's own
 * and the shared ones.
 *
 * Each test renders one surface on three canvases of alice's dataflow, hers,
 * an editor's and a watcher's, and compares what each asked for or shows.
 */
import React from "react";
import { act, render, renderHook, screen, waitFor } from "@testing-library/react";

let mockFlow: Record<string, unknown> = {};
jest.mock("../../providers/FlowProvider", () => ({
  useFlowContext: () => ({
    projectId: null,
    viewerMode: "owner",
    projectName: "Street trees",
    outputs: [],
    nodes: [],
    defaultSaveOutputDataset: false,
    pendingInstalls: [],
    ensureProjectId: async () => null,
    setDataflowDatasets: () => undefined,
    beginPendingInstall: () => undefined,
    endPendingInstall: () => undefined,
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
  useToastContext: () => ({ showToast: () => undefined }),
}));
jest.mock("../../components/apiSettings/useHostedGuest", () => ({
  useHostedGuest: () => false,
  hostedGuestSignInNote: (action: string) => `Sign in to ${action}.`,
}));
// The drawer's own markup, which its provider mounts only once it is opened.
jest.mock("../../components/datasets/catalog", () => ({
  DatasetCatalogDrawer: () => null,
}));
jest.mock("../../components/menus/nodes/datasetPalette/DatasetPaletteRows", () => ({
  DatasetRow: ({ dataset }: { dataset: { id: string; title: string } }) => (
    <div data-dataset-id={dataset.id}>{dataset.title}</div>
  ),
  DatasetGroupRow: () => null,
}));
jest.mock("../../utils/saveOutputDataset", () => ({ buildSaveableLiveOutputs: () => undefined }));

import { DatasetsPaletteDropdown } from "../../components/menus/nodes/datasetPalette/DatasetsPaletteDropdown";
import { useDatasetCatalogDrawer } from "../../components/datasets/catalog/useDatasetCatalogDrawer";
import { DatasetCatalogDrawerProvider } from "../../providers/datasetCatalog";
import { DatasetPaletteProvider, useDatasetPalette } from "../../providers/DatasetPaletteContext";
import { clearCurrentProject, setCurrentProject } from "../../registry/projectPackagesStore";
import {
  datasetCatalogApi,
  invalidateDatasetCatalogCache,
  type DatasetCatalogQuery,
  type DatasetCatalogResponse,
} from "../../services/datasetCatalog";

const ALICES = "alices-dataflow";

/** A dataset of alice's that her dataflow lists: a listing of the dataflow
 *  marks it installed. */
const STREET_TREES = {
  id: "imported.xstreettrees",
  title: "Street trees",
  origin: "imported",
  format: "csv",
  dirName: "imported.xstreettrees@1",
  installed: true,
  consumerNodeIds: [],
  tags: [],
  updatedAt: "2026-10-29T00:00:00Z",
};
/** One of the reader's own, which the reader adds to every project of theirs. */
const BUS_STOPS = {
  id: "imported.xbusstops",
  title: "Bus stops",
  origin: "imported",
  format: "csv",
  dirName: "imported.xbusstops@1",
  inAllProjects: true,
  consumerNodeIds: [],
  tags: [],
  updatedAt: "2026-10-28T00:00:00Z",
};
const NO_FACETS = {
  origin: { source_node: 0, computed: 0, imported: 0, hub: 0 },
  format: {},
};

/** What the backend lists: of alice's dataflow, the dataset it lists; beside
 *  it, unless the listing leaves them out (`includeHub: false`), the reader's
 *  own. */
function listing(query: DatasetCatalogQuery = {}): DatasetCatalogResponse {
  const ofTheDataflow = query.dataflowId === ALICES ? [STREET_TREES] : [];
  const own = query.includeHub === false ? [] : [BUS_STOPS];
  return { items: [...ofTheDataflow, ...own], facets: NO_FACETS } as unknown as DatasetCatalogResponse;
}

type Canvas = "owner" | "editor" | "watcher";

/** Three tabs on alice's dataflow, each opened from its route. Only hers saves
 *  it, so only hers has the flow state's `projectId`. */
const CANVASES: Record<Canvas, { flow: Record<string, unknown>; role: string | null }> = {
  owner: { flow: { projectId: ALICES, viewerMode: "owner" }, role: "owner" },
  editor: { flow: { projectId: null, viewerMode: "shared" }, role: "editor" },
  watcher: { flow: { projectId: null, viewerMode: "shared" }, role: "watcher" },
};

let listCatalog: jest.SpyInstance;

beforeEach(() => {
  listCatalog = jest
    .spyOn(datasetCatalogApi, "listCatalog")
    .mockImplementation(async (query?: DatasetCatalogQuery) => listing(query));
});

afterEach(() => {
  listCatalog.mockRestore();
  clearCurrentProject();
  mockFlow = {};
  mockRole = null;
});

/** *read* on each canvas in turn, from an empty catalog cache. */
async function onEachCanvas<T>(read: () => Promise<T>): Promise<Record<Canvas, T>> {
  const seen = {} as Record<Canvas, T>;
  for (const canvas of Object.keys(CANVASES) as Canvas[]) {
    mockFlow = CANVASES[canvas].flow;
    mockRole = CANVASES[canvas].role;
    setCurrentProject(ALICES, []);
    invalidateDatasetCatalogCache();
    listCatalog.mockClear();
    seen[canvas] = await read();
  }
  return seen;
}

/** Until every listing asked for so far has answered. */
async function listingsAnswered(): Promise<void> {
  await act(async () => {
    await Promise.all(listCatalog.mock.results.map((result) => result.value));
  });
}

/** The dataflows the listings asked for named, each once: null for none. */
function askedFor(): Array<string | null> {
  return Array.from(
    new Set(listCatalog.mock.calls.map(([query]) => (query as DatasetCatalogQuery | undefined)?.dataflowId ?? null)),
  );
}

/** The palette, inside the two providers the canvas mounts it in. */
async function openPalette(): Promise<{ asked: Array<string | null>; inProject: string[] }> {
  const view = render(
    <DatasetCatalogDrawerProvider>
      <DatasetPaletteProvider>
        <DatasetsPaletteDropdown open setOpen={() => undefined} />
      </DatasetPaletteProvider>
    </DatasetCatalogDrawerProvider>,
  );
  await listingsAnswered();
  const group = () => screen.getByText("Datasets in project").closest("details") as HTMLElement;
  const rows = () => Array.from(group().querySelectorAll("[data-dataset-id]"));
  await waitFor(() => expect(rows().length).toBeGreaterThan(0));
  const seen = { asked: askedFor(), inProject: rows().map((row) => row.textContent ?? "") };
  view.unmount();
  return seen;
}

/** The drawer, on its In project tab. */
async function openDrawer(): Promise<{ asked: Array<string | null>; inProject: string[] }> {
  const view = renderHook(() => useDatasetCatalogDrawer(true));
  act(() => view.result.current.setTab("installed"));
  await listingsAnswered();
  await waitFor(() => expect(view.result.current.items.length).toBeGreaterThan(0));
  const seen = { asked: askedFor(), inProject: view.result.current.items.map((dataset) => dataset.title) };
  view.unmount();
  return seen;
}

describe("the Data Catalog palette", () => {
  test("asks for the dataflow's listing on the owner's canvas and an editor's, and for none on a watcher's", async () => {
    const seen = await onEachCanvas(openPalette);
    expect({
      owner: seen.owner.asked,
      editor: seen.editor.asked,
      watcher: seen.watcher.asked,
    }).toEqual({ owner: [ALICES], editor: [ALICES], watcher: [null] });
  });

  test("lists the dataflow's datasets under Datasets in project on the owner's canvas and an editor's", async () => {
    const seen = await onEachCanvas(openPalette);
    expect({
      owner: seen.owner.inProject,
      editor: seen.editor.inProject,
      watcher: seen.watcher.inProject,
    }).toEqual({
      owner: ["Street trees"],
      // The editor's own datasets of every project are not alice's dataflow's.
      editor: ["Street trees"],
      // No dataflow: the watcher's own, a save away, as on a dataflow never saved.
      watcher: ["Bus stops"],
    });
  });

  test("names, on a node's dataset pill, the datasets of the dataflow on the owner's canvas and an editor's", async () => {
    const Names = () => {
      const { datasetsById } = useDatasetPalette();
      return <div data-testid="names">{Array.from(datasetsById?.values() ?? []).map((d) => d.title).join(",")}</div>;
    };
    const seen = await onEachCanvas(async () => {
      const view = render(
        <DatasetPaletteProvider>
          <Names />
        </DatasetPaletteProvider>,
      );
      await listingsAnswered();
      const names = screen.getByTestId("names").textContent;
      view.unmount();
      return names;
    });
    expect(seen).toEqual({ owner: "Street trees", editor: "Street trees", watcher: "" });
  });
});

describe("the Data Catalog drawer", () => {
  test("asks for the dataflow's listing on the owner's canvas and an editor's, and for none on a watcher's", async () => {
    const seen = await onEachCanvas(openDrawer);
    expect({
      owner: seen.owner.asked,
      editor: seen.editor.asked,
      watcher: seen.watcher.asked,
    }).toEqual({ owner: [ALICES], editor: [ALICES], watcher: [null] });
  });

  test("lists the dataflow's datasets in its In project tab on the owner's canvas and an editor's", async () => {
    const seen = await onEachCanvas(openDrawer);
    expect({
      owner: seen.owner.inProject,
      editor: seen.editor.inProject,
      watcher: seen.watcher.inProject,
    }).toEqual({ owner: ["Street trees"], editor: ["Street trees"], watcher: ["Bus stops"] });
  });

  test("warms both listings of the dataflow on the owner's canvas and an editor's, and none on a watcher's", async () => {
    const seen = await onEachCanvas(async () => {
      const view = render(
        <DatasetCatalogDrawerProvider>
          <div />
        </DatasetCatalogDrawerProvider>,
      );
      await listingsAnswered();
      const warmed = listCatalog.mock.calls.map(([query]) => {
        const { dataflowId, includeHub } = (query ?? {}) as DatasetCatalogQuery;
        return `${dataflowId ?? "none"} includeHub=${String(includeHub)}`;
      });
      view.unmount();
      return warmed;
    });
    expect(seen).toEqual({
      owner: [`${ALICES} includeHub=true`, `${ALICES} includeHub=false`],
      editor: [`${ALICES} includeHub=true`, `${ALICES} includeHub=false`],
      watcher: [],
    });
  });
});
