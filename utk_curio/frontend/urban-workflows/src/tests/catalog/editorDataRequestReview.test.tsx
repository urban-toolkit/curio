/**
 * What bob, an editor alice invited, asked her to add to her dataflow, as the
 * canvas shows it once the server lists the request:
 *
 * - alice's Data Catalog drawer shows his request on the review card an
 *   install an agent asks for has, under his name, with Apply and Dismiss, and
 *   her canvas tells her of it; her Apply and Dismiss go to the request;
 * - on bob's canvas the same card says it waits for the dataflow's owner;
 * - a node that loads the dataset asked for says on its dataset pill that it
 *   waits for the owner, on both canvases.
 *
 * The canvas reads the requests through `fetch`, which answers here.
 */
import React from "react";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import { ReactFlowProvider } from "reactflow";

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
jest.mock("../../providers/DatasetPaletteContext", () => ({
  useDatasetPalette: () => ({
    datasetRevealId: null,
    setDatasetRevealId: () => undefined,
    installedComputedByProducer: new Map(),
    datasetsById: new Map(),
  }),
}));

import { DatasetCatalogDrawer } from "../../components/datasets/catalog/DatasetCatalogDrawer";
import { DatasetMetaHeader } from "../../components/datasets/DatasetMetaHeader";
import { DatasetCatalogDrawerProvider } from "../../providers/datasetCatalog";
import { clearCurrentProject, setCurrentProject } from "../../registry/projectPackagesStore";
import { invalidateDatasetCatalogCache } from "../../services/datasetCatalog";

const ALICES = "alices-dataflow";
/** bob's request for his bus stops, as the server lists it. */
const BOBS_REQUEST = {
  proposalId: "req-bus-stops",
  tool: "dataset.install",
  status: "pending",
  summary: "Add dataset · Bus stops",
  preview: "Bus stops · CSV · from Bob's Data Catalog",
  datasetId: "imported.xbusstops",
  datasetName: "Bus stops",
  format: "csv",
  by: { kind: "person", account: "2", name: "Bob" },
  nodeIds: ["bus-loader"],
};
const NO_FACETS = { origin: { source_node: 0, computed: 0, imported: 0, hub: 0 }, format: {} };

type Canvas = "owner" | "editor";
const CANVASES: Record<Canvas, { flow: Record<string, unknown>; role: string }> = {
  owner: { flow: { projectId: ALICES, viewerMode: "owner" }, role: "owner" },
  editor: { flow: { projectId: null, viewerMode: "shared" }, role: "editor" },
};

let sent: Array<{ method: string; path: string }> = [];

function answer(method: string, path: string): unknown {
  if (path.startsWith(`/api/dataflows/${ALICES}/datasets/requests`) && method === "GET") {
    return { requests: [BOBS_REQUEST] };
  }
  if (path.endsWith("/apply")) {
    return { proposalId: BOBS_REQUEST.proposalId, status: "applied", installedDataset: { id: BOBS_REQUEST.datasetId, name: "Bus stops" } };
  }
  if (method === "DELETE") return { proposalId: BOBS_REQUEST.proposalId, status: "dismissed" };
  if (path.startsWith("/api/datasets/catalog")) return { items: [], facets: NO_FACETS };
  return {};
}

const realFetch = global.fetch;
beforeEach(() => {
  sent = [];
  mockShowToast.mockClear();
  global.fetch = jest.fn(async (url: RequestInfo | URL, opts: RequestInit = {}) => {
    // The route, whatever backend address the page was built with.
    const path = String(url).replace(/^.*?(?=\/api\/)/, "");
    const method = (opts.method ?? "GET").toUpperCase();
    sent.push({ method, path });
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
  setCurrentProject(ALICES, []);
  invalidateDatasetCatalogCache();
}

/** The canvas's Data Catalog drawer, open, inside the provider that reads the requests. */
function openDrawer() {
  return render(
    <DatasetCatalogDrawerProvider>
      <DatasetCatalogDrawer presented onRequestClose={() => undefined} onExitComplete={() => undefined} />
    </DatasetCatalogDrawerProvider>,
  );
}

async function bobsCard(): Promise<HTMLElement> {
  return screen.findByRole("group", { name: `Review proposal: ${BOBS_REQUEST.summary}` });
}

describe("bob's request in alice's review", () => {
  test("alice's drawer shows it under his name with Apply and Dismiss, and her canvas tells her of it", async () => {
    on("owner");
    const view = openDrawer();
    const card = await bobsCard();

    expect(screen.getByText("Asked by Bob")).toBeInTheDocument();
    expect(within(card).getByText(BOBS_REQUEST.preview)).toBeInTheDocument();
    expect(within(card).getByRole("button", { name: "Dismiss" })).toBeInTheDocument();
    expect(mockShowToast).toHaveBeenCalledWith(
      "Bob asks you to add Bus stops to this dataflow.",
      "info",
      expect.objectContaining({ action: expect.objectContaining({ label: "Review" }) }),
    );

    await act(async () => {
      within(card).getByRole("button", { name: "Apply" }).click();
    });
    await waitFor(() =>
      expect(sent.map((s) => `${s.method} ${s.path}`)).toContain(
        `POST /api/dataflows/${ALICES}/datasets/requests/${BOBS_REQUEST.proposalId}/apply`,
      ),
    );
    view.unmount();
  });

  test("alice's Dismiss goes to the request", async () => {
    on("owner");
    const view = openDrawer();
    const card = await bobsCard();

    await act(async () => {
      within(card).getByRole("button", { name: "Dismiss" }).click();
    });
    await waitFor(() =>
      expect(sent.map((s) => `${s.method} ${s.path}`)).toContain(
        `DELETE /api/dataflows/${ALICES}/datasets/requests/${BOBS_REQUEST.proposalId}`,
      ),
    );
    view.unmount();
  });

  test("on bob's canvas the card says it waits for the dataflow's owner, with no Apply or Dismiss", async () => {
    on("editor");
    const view = openDrawer();
    const card = await bobsCard();

    // Found once bob's canvas has read the requests.
    expect(await within(card).findByText("Waits for the dataflow's owner to review it: an install changes their account."))
      .toBeInTheDocument();
    expect(within(card).queryByRole("button", { name: "Apply" })).toBeNull();
    expect(within(card).queryByRole("button", { name: "Dismiss" })).toBeNull();
    expect(mockShowToast).not.toHaveBeenCalledWith(expect.stringContaining("asks you"), expect.anything(), expect.anything());
    view.unmount();
  });
});

describe("the node that loads the dataset bob asked for", () => {
  test.each([
    ["editor", "Waits for the dataflow's owner to add Bus stops to it."],
    ["owner", "Bob asks you to add Bus stops to this dataflow: review it in the Data Catalog."],
  ] as const)("says on %s's canvas that it waits for the owner", async (canvas, says) => {
    on(canvas);
    const view = render(
      <ReactFlowProvider>
        <DatasetCatalogDrawerProvider>
          <DatasetMetaHeader
            source={{ datasetId: BOBS_REQUEST.datasetId, title: "Bus stops", format: "csv", origin: "imported" }}
          />
        </DatasetCatalogDrawerProvider>
      </ReactFlowProvider>,
    );

    // Waited for until this canvas has read the requests.
    const pill = await waitFor(() => {
      const waiting = view.container.querySelector('[data-curio-waits-for-owner="true"]');
      expect(waiting?.getAttribute("data-tooltip") ?? "").toContain(says);
      return waiting as HTMLElement;
    });
    expect(pill).toHaveTextContent("WAITING");
    view.unmount();
  });

  test("a node that loads a dataset no one asked for keeps its DATASET pill", async () => {
    on("editor");
    const view = render(
      <ReactFlowProvider>
        <DatasetCatalogDrawerProvider>
          <DatasetMetaHeader
            source={{ datasetId: "imported.xstreettrees", title: "Street trees", format: "csv", origin: "imported" }}
          />
        </DatasetCatalogDrawerProvider>
      </ReactFlowProvider>,
    );
    await waitFor(() => expect(sent.some((s) => s.path.includes("/datasets/requests"))).toBe(true));
    expect(screen.getByRole("button")).toHaveTextContent("DATASET");
    expect(view.container.querySelector("[data-curio-waits-for-owner]")).toBeNull();
    view.unmount();
  });
});
