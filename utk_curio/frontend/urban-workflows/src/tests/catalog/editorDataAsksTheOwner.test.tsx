/**
 * An invited editor's own data on the owner's dataflow asks the owner: his Add
 * to project in the Data Catalog drawer, and a file he drops on the canvas or
 * a node, each send a request to her install review, never an install into
 * her dataflow; and his Remove from project removes the dataset from the
 * dataflow his link opened, without saying any file is deleted. The owner's
 * canvas adds and removes as before.
 *
 * Each test runs the hook a surface uses on alice's canvas and on bob's, and
 * reads what reached the server through `fetch`.
 */
import { act, renderHook } from "@testing-library/react";

let mockFlow: Record<string, unknown> = {};
const mockEnsureProjectId = jest.fn(async (): Promise<string | null> => null);
jest.mock("../../providers/FlowProvider", () => ({
  useFlowContext: () => ({
    projectId: null,
    viewerMode: "owner",
    projectName: "Street trees",
    outputs: [],
    nodes: [],
    defaultSaveOutputDataset: false,
    pendingInstalls: [],
    ensureProjectId: mockEnsureProjectId,
    setDataflowDatasets: () => undefined,
    beginPendingInstall: () => undefined,
    endPendingInstall: () => undefined,
    ...mockFlow,
  }),
}));
// The tab's role in the dataflow's room.
let mockRole: string | null = null;
jest.mock("../../providers/CollaborationProvider", () => ({
  useCollab: () => ({ connected: true, users: [], lockedNodes: {}, role: mockRole, onRemote: () => () => undefined }),
}));
const mockShowToast = jest.fn();
jest.mock("../../providers/ToastProvider", () => ({
  useToastContext: () => ({ showToast: mockShowToast }),
}));
jest.mock("../../components/apiSettings/useHostedGuest", () => ({
  useHostedGuest: () => false,
  hostedGuestSignInNote: (action: string) => `Sign in to ${action}.`,
}));
jest.mock("../../utils/saveOutputDataset", () => ({ buildSaveableLiveOutputs: () => undefined }));

import { useDatasetCatalogDrawer } from "../../components/datasets/catalog/useDatasetCatalogDrawer";
import { useDataFileImport } from "../../components/datasets/useDataFileImport";
import { clearCurrentProject, setCurrentProject } from "../../registry/projectPackagesStore";
import { invalidateDatasetCatalogCache } from "../../services/datasetCatalog";

const ALICES = "alices-dataflow";
/** One of bob's own datasets, which only his store holds. */
const BUS_STOPS = {
  id: "imported.xbusstops",
  title: "Bus stops",
  origin: "imported",
  format: "csv",
  dirName: "imported.xbusstops@1",
  uri: "curio://datasets/imported.xbusstops@1",
  consumerNodeIds: [],
  tags: [],
  updatedAt: "2026-10-29T00:00:00Z",
};
/** alice's upload, which her dataflow lists. */
const STREET_TREES = {
  ...BUS_STOPS,
  id: "imported.xstreettrees",
  title: "Street trees",
  dirName: "imported.xstreettrees@1",
  uri: "curio://datasets/imported.xstreettrees@1",
  installed: true,
};
const NO_FACETS = { origin: { source_node: 0, computed: 0, imported: 0, hub: 0 }, format: {} };

type Canvas = "owner" | "editor";
/** alice's canvas of her dataflow, and bob's, opened from its route. Only hers
 *  saves it: on bob's, `ensureProjectId` answers no dataflow, as the shared
 *  view's read-only refusal does. */
const CANVASES: Record<Canvas, { flow: Record<string, unknown>; role: string; saves: string | null }> = {
  owner: { flow: { projectId: ALICES, viewerMode: "owner" }, role: "owner", saves: ALICES },
  editor: { flow: { projectId: null, viewerMode: "shared" }, role: "editor", saves: null },
};

/** Each request the page sent, in order. */
let sent: Array<{ method: string; path: string; body: unknown; dataflowField: unknown }> = [];

function answer(method: string, path: string): unknown {
  if (path.includes("/datasets/requests") && method === "POST") {
    return { requested: true, request: { proposalId: "req-1", datasetId: BUS_STOPS.id } };
  }
  if (path.includes("/datasets/requests")) return { requests: [] };
  if (path.includes("/datasets/install")) return { ...BUS_STOPS, installed: true };
  if (path.startsWith("/api/datasets/import")) return BUS_STOPS;
  if (path.startsWith("/api/datasets/catalog")) return { items: [], facets: NO_FACETS };
  if (path.includes("/usage")) return { dataflows: [{ id: ALICES, name: "Street trees", nodeCount: 0 }] };
  if (method === "DELETE") return { datasets: [] };
  return BUS_STOPS;
}

const realFetch = global.fetch;
beforeEach(() => {
  sent = [];
  mockShowToast.mockClear();
  global.fetch = jest.fn(async (url: RequestInfo | URL, opts: RequestInit = {}) => {
    const path = String(url).replace(/^https?:\/\/[^/]+/, "");
    const method = (opts.method ?? "GET").toUpperCase();
    const form = opts.body instanceof FormData ? opts.body : null;
    sent.push({
      method,
      path,
      body: typeof opts.body === "string" ? JSON.parse(opts.body) : null,
      dataflowField: form ? form.get("dataflowId") : undefined,
    });
    return { ok: true, status: 200, json: async () => answer(method, path) } as unknown as Response;
  }) as unknown as typeof fetch;
});

afterEach(() => {
  global.fetch = realFetch;
  clearCurrentProject();
  mockFlow = {};
  mockRole = null;
});

function on(canvas: Canvas): void {
  mockFlow = CANVASES[canvas].flow;
  mockRole = CANVASES[canvas].role;
  mockEnsureProjectId.mockResolvedValue(CANVASES[canvas].saves);
  setCurrentProject(ALICES, []);
  invalidateDatasetCatalogCache();
  sent = [];
}

/** What the page asked the server to change: each request but a read. */
function writes(): string[] {
  return sent.filter((request) => request.method !== "GET").map((request) => `${request.method} ${request.path.split("?")[0]}`);
}

describe("an editor's own data asks the owner", () => {
  test("his Add to project sends a request to her review and installs nothing; hers adds the dataset", async () => {
    const seen = {} as Record<Canvas, { writes: string[]; body: unknown }>;
    for (const canvas of Object.keys(CANVASES) as Canvas[]) {
      on(canvas);
      const view = renderHook(() => useDatasetCatalogDrawer(true));
      await act(async () => {
        await view.result.current.onInstall(BUS_STOPS as never);
      });
      const confirm = view.result.current.confirmAction;
      expect(confirm).not.toBeNull();
      await act(async () => {
        await confirm!.run();
      });
      const request = sent.find((s) => s.method === "POST");
      seen[canvas] = { writes: writes(), body: request?.body ?? null };
      view.unmount();
    }
    expect(seen.editor).toEqual({
      writes: [`POST /api/dataflows/${ALICES}/datasets/requests`],
      body: { datasetId: BUS_STOPS.id, add: true },
    });
    expect(seen.owner.writes).toEqual([`POST /api/dataflows/${ALICES}/datasets/install`]);
  });

  test("his dropped file goes into his own Data Catalog and asks the owner; hers is added to her dataflow", async () => {
    const seen = {} as Record<Canvas, { writes: string[]; dataflowField: unknown; loads: string | null }>;
    for (const canvas of Object.keys(CANVASES) as Canvas[]) {
      on(canvas);
      const view = renderHook(() => useDataFileImport());
      let payload: { datasetId: string } | null = null;
      await act(async () => {
        payload = await view.result.current([new File(["stop,routes\nClark,22\n"], "bus_stops.csv", { type: "text/csv" })]);
      });
      const imported = sent.find((s) => s.path.startsWith("/api/datasets/import"));
      seen[canvas] = {
        writes: writes(),
        dataflowField: imported ? imported.dataflowField : "no import",
        loads: (payload as { datasetId: string } | null)?.datasetId ?? null,
      };
      view.unmount();
    }
    expect(seen.editor).toEqual({
      writes: ["POST /api/datasets/import", `POST /api/dataflows/${ALICES}/datasets/requests`],
      // His own Data Catalog: the import names no dataflow of hers.
      dataflowField: null,
      // The drop then makes the Data Loading node, or sets the node's widget.
      loads: BUS_STOPS.id,
    });
    expect(seen.owner).toEqual({
      writes: ["POST /api/datasets/import", `POST /api/dataflows/${ALICES}/datasets/install`],
      dataflowField: ALICES,
      loads: BUS_STOPS.id,
    });
  });

  test("his Remove from project takes the dataset out of the dataflow his link opened and says no file is deleted", async () => {
    const seen = {} as Record<Canvas, { writes: string[]; asked: string }>;
    for (const canvas of Object.keys(CANVASES) as Canvas[]) {
      on(canvas);
      const view = renderHook(() => useDatasetCatalogDrawer(true));
      await act(async () => {
        await view.result.current.onUninstall(STREET_TREES as never);
      });
      const confirm = view.result.current.confirmAction;
      expect(confirm).not.toBeNull();
      const asked = `${confirm!.body} [${confirm!.confirmLabel}]`;
      sent = [];
      await act(async () => {
        await confirm!.run();
      });
      seen[canvas] = { writes: writes(), asked };
      view.unmount();
    }
    expect(seen.editor.writes).toEqual([`DELETE /api/dataflows/${ALICES}/datasets/${STREET_TREES.id}`]);
    expect(seen.editor.asked).not.toMatch(/delete/i);
    expect(seen.editor.asked).toContain("owner");
    // alice's own upload, which no other dataflow of hers uses: her removal
    // deletes it, and says so.
    expect(seen.owner.writes).toEqual([`DELETE /api/dataflows/${ALICES}/datasets/${STREET_TREES.id}`]);
    expect(seen.owner.asked).toContain("[Remove and delete]");
  });
});
