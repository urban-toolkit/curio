/**
 * A package or a model of bob's own, bob an editor alice invited, asked of
 * alice for her dataflow, as the canvas sends and shows it:
 *
 * - his Add to project in his Node Catalog drawer asks her, once he confirms,
 *   and installs nothing; his Import package puts the package in his own
 *   account and asks her;
 * - his drop of the card of a package her dataflow does not use makes its node
 *   at once and asks her, naming the node;
 * - a model of his dropped on a node is the model package its card names;
 * - alice's Node Catalog drawer shows his request on the review card an
 *   agent's package install has: its name, version, publisher and what it may
 *   do, and what her Apply does; her canvas tells her of it. Her Apply first
 *   opens the review her own Add opens, and only its confirm applies it;
 * - the PACKAGE pill of a node of it says it waits for her, on his canvas and
 *   on hers.
 *
 * The canvas reads the requests through `fetch`, which answers here. Code main
 * lacks is reached through `require`, so main fails test by test.
 */
import React from "react";
import { act, fireEvent, render, renderHook, screen, waitFor, within } from "@testing-library/react";
import "@testing-library/jest-dom";
import { MemoryRouter } from "react-router-dom";

// The drawers reach the node registry, whose built-in behaviors load Vega's
// ESM build: mocked virtually, as testing-gotchas prescribes.
jest.mock("vega", () => ({}), { virtual: true });
jest.mock("vega-lite", () => ({}), { virtual: true });

let mockFlow: Record<string, unknown> = {};
jest.mock("../../providers/FlowProvider", () => ({
  useFlowContext: () => ({
    projectId: null,
    viewerMode: "owner",
    projectName: "Bus plan",
    packages: [],
    nodes: [],
    outputs: [],
    projectDirty: false,
    pendingInstalls: [],
    ensureProjectId: async () => null,
    whenChangesKept: async () => undefined,
    setDataflowDatasets: () => undefined,
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
jest.mock("../../registry/packageRegistryBootstrap", () => ({
  refreshPackageRegistry: jest.fn().mockResolvedValue(undefined),
}));

import { NodeCatalogDrawer } from "../../components/packages/publishing/NodeCatalogDrawer";
import { PackageMetaHeader } from "../../components/packages/editing/PackageMetaHeader";
import { DatasetCatalogDrawerProvider } from "../../providers/datasetCatalog";
import { PackagePaletteProvider } from "../../providers/packages/PackagePaletteContext";
import { clearCurrentProject, setCurrentProject } from "../../registry/projectPackagesStore";
import { invalidateDatasetCatalogCache } from "../../services/datasetCatalog";
import { endModelCardDrag, writeModelCardDrag, type PackagePayload } from "../../services/packages";
import { template } from "../_support/modelPackages";

const ALICES = "alices-dataflow";
const BUS_DIR = "test.bus-counts@1";
const MODEL_DIR = "test.bus-model@1";

function row(fields: Record<string, unknown>): PackagePayload {
  return {
    major: 1,
    version: "1.0.0",
    publisher: "Bob Test",
    description: "",
    license: "MIT",
    permissions: [],
    dependencies: { packages: {}, python: {}, js: {} },
    templates: [],
    lineage: null,
    channel: "stable",
    createdAtMs: 0,
    modules: [],
    kind: "node",
    ...fields,
    familyKey: fields.dirName,
  } as unknown as PackagePayload;
}

/** bob's package, as his store lists it. */
const BUS = row({
  packageId: "test.bus-counts",
  dirName: BUS_DIR,
  name: "Bus counts",
  permissions: ["server-network"],
  templates: [template({ id: "test.bus-counts/count@1", templateId: "count", label: "Count" })],
});
/** bob's model, as his store lists it. */
const BUS_MODEL = row({
  packageId: "test.bus-model",
  dirName: MODEL_DIR,
  name: "Bus model",
  kind: "model",
  templates: [template({ id: "test.bus-model/run@1", templateId: "run", label: "Run" })],
  model: { type: "node-regression", runtime: "onnx", entry: "models/w.onnx" },
});
/** bob's request for his package, as the server lists it. */
const BOBS_REQUEST = {
  proposalId: "req-bus-counts",
  kind: "packages",
  tool: "package.install",
  status: "pending",
  summary: "Add package · Bus counts",
  preview: "Bus counts · v1.0.0 · Bob Test · from Bob Test's Node Catalog",
  dirName: BUS_DIR,
  packageName: "Bus counts",
  packageKind: "node",
  version: "1.0.0",
  publisher: "Bob Test",
  permissions: ["server-network"],
  shared: false,
  by: { kind: "person", account: "2", name: "Bob Test" },
  nodeIds: ["bus-node"],
};
/** What alice's Apply does, as her card says it. */
const OWNERS_APPLY =
  "Applying opens its review (permissions, libraries, conflicts). Confirming there checks its files, copies " +
  "the package into your Node Catalog unless it is there already, installs its libraries under your account " +
  "and adds it to this dataflow.";

type Canvas = "owner" | "editor";
const CANVASES: Record<Canvas, { flow: Record<string, unknown>; role: string }> = {
  owner: { flow: { projectId: ALICES, viewerMode: "owner" }, role: "owner" },
  editor: { flow: { projectId: null, viewerMode: "shared" }, role: "editor" },
};

let sent: Array<{ method: string; path: string; body: unknown }> = [];

function answer(method: string, path: string): unknown {
  if (path === `/api/dataflows/${ALICES}/packages/requests` && method === "GET") return { requests: [BOBS_REQUEST] };
  if (path === `/api/dataflows/${ALICES}/packages/requests` && method === "POST") {
    return { requested: true, request: BOBS_REQUEST };
  }
  if (path.startsWith("/api/packages/upload")) {
    return { package: BUS, integrity: {}, replacedExisting: false, importErrors: {} };
  }
  if (path.endsWith("/review")) return { package: BUS, conflicts: [] };
  if (path.endsWith("/apply")) return { proposalId: BOBS_REQUEST.proposalId, status: "applied" };
  if (path.includes("/datasets/requests")) return { requests: [] };
  if (path.startsWith("/api/packages/catalog")) return { packages: [], families: [], catalogCollisions: [] };
  if (path.startsWith("/api/packages/factory/capabilities")) return { catalogPublish: false };
  if (path.startsWith("/api/packages/projects/")) return { packages: [] };
  if (path.split("?")[0] === "/api/packages") return { packages: [BUS, BUS_MODEL] };
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
    sent.push({ method, path, body: typeof opts.body === "string" ? JSON.parse(opts.body) : null });
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

/** What the page asked the server to change: each request but a read. */
function writes(): string[] {
  return sent.filter((request) => request.method !== "GET").map((request) => `${request.method} ${request.path}`);
}

/** The canvas's Node Catalog drawer, open, inside the provider that reads the requests. */
function openNodeDrawer() {
  return render(
    <MemoryRouter>
      <DatasetCatalogDrawerProvider>
        <NodeCatalogDrawer presented onRequestClose={() => undefined} onExitComplete={() => undefined} />
      </DatasetCatalogDrawerProvider>
    </MemoryRouter>,
  );
}

describe("bob's own package asks alice", () => {
  test("his Add to project asks her once he confirms, and installs nothing", async () => {
    on("editor");
    const view = openNodeDrawer();
    const card = await waitFor(() => {
      const found = document.querySelector(`article[data-pkg-dir="${BUS_DIR}"]`);
      expect(found).not.toBeNull();
      return found as HTMLElement;
    });

    await act(async () => {
      within(card).getByRole("button", { name: "Add to project" }).click();
    });
    await waitFor(() => expect(screen.queryByText("Ask to add Bus counts?")).toBeInTheDocument());
    await act(async () => {
      screen.getByRole("button", { name: "Ask the owner" }).click();
    });

    await waitFor(() => expect(writes()).toEqual([`POST /api/dataflows/${ALICES}/packages/requests`]));
    expect(sent.find((request) => request.method === "POST")?.body).toEqual({ dirName: BUS_DIR, add: true });
    expect(mockShowToast).toHaveBeenCalledWith("Asked the dataflow's owner to add Bus counts to it.", "info");
    view.unmount();
  });

  test("his Import package puts it in his own account and asks her to add it", async () => {
    on("editor");
    const view = openNodeDrawer();
    const input = await waitFor(() => {
      const found = document.querySelector('[data-curio-node-catalog-drawer="true"] input[type="file"]');
      expect(found).not.toBeNull();
      return found as HTMLInputElement;
    });

    await act(async () => {
      fireEvent.change(input, { target: { files: [new File(["zip"], "bus.curio.zip", { type: "application/zip" })] } });
    });

    await waitFor(() =>
      expect(writes()).toEqual(["POST /api/packages/upload", `POST /api/dataflows/${ALICES}/packages/requests`]),
    );
    // The ask is the POST: the drawer reads the requests too, with a GET.
    const ask = sent.find((request) => request.method === "POST" && request.path.endsWith("/packages/requests"));
    expect(ask?.body).toEqual({ dirName: BUS_DIR, add: true });
    view.unmount();
  });

  test("his drop of its card makes its node at once and asks her, naming the node", () => {
    // eslint-disable-next-line @typescript-eslint/no-var-requires
    const { usePackageCardDrop } = require("../../components/packages/usePackageCardDrop");
    const createNode = jest.fn(() => "bus-node");
    const askTheOwner = jest.fn(async () => true);
    const card = { dirName: BUS_DIR, name: "Bus counts", kind: "node", nodes: [{ nodeType: "test.bus-counts/count@1", label: "Count" }] };
    const hook = renderHook(() =>
      usePackageCardDrop({ dataflowPackages: [], hostedGuest: false, createNode, showToast: mockShowToast, askTheOwner }),
    );

    act(() => hook.result.current.drop({ card, position: { x: 10, y: 20 }, at: { x: 0, y: 0 } }));

    expect(createNode).toHaveBeenCalledWith(card.nodes[0], { x: 10, y: 20 });
    expect(askTheOwner).toHaveBeenCalledWith({ dirName: BUS_DIR, name: "Bus counts" }, { nodeId: "bus-node" });
  });

  test("a model of his dropped on a node is the model package its card names", () => {
    // eslint-disable-next-line @typescript-eslint/no-var-requires
    const packages = require("../../services/packages");
    expect(typeof packages.modelDropRequest).toBe("function");
    const store = new Map<string, string>();
    const dataTransfer = {
      effectAllowed: "",
      dropEffect: "",
      get types() {
        return Array.from(store.keys());
      },
      setData: (type: string, value: string) => void store.set(type, value),
      getData: (type: string) => store.get(type) ?? "",
    } as unknown as DataTransfer;
    writeModelCardDrag(dataTransfer, BUS_MODEL);
    try {
      expect(packages.modelDropRequest(dataTransfer)).toEqual({ dirName: MODEL_DIR, name: "Bus model" });
    } finally {
      endModelCardDrag();
    }
  });
});

describe("bob's request in alice's review", () => {
  test("her Node Catalog drawer shows it on an install's card, and her Apply opens her own Add's review first", async () => {
    on("owner");
    const view = openNodeDrawer();
    const card = await waitFor(() => {
      const found = screen.queryByRole("group", { name: `Review proposal: ${BOBS_REQUEST.summary}` });
      expect(found).not.toBeNull();
      return found as HTMLElement;
    });

    expect(screen.getByText("Asked by Bob Test")).toBeInTheDocument();
    expect(within(card).getByText(/Bus counts · v1\.0\.0 · Bob Test · from Bob Test's Node Catalog/)).toBeInTheDocument();
    expect(
      within(card).getByText(/Permissions requested: server-network \(its server-side code may reach the network\)/),
    ).toBeInTheDocument();
    expect(within(card).getByText(OWNERS_APPLY)).toBeInTheDocument();
    expect(mockShowToast).toHaveBeenCalledWith(
      "Bob Test asks you to add Bus counts to this dataflow.",
      "info",
      expect.objectContaining({ action: expect.objectContaining({ label: "Review" }) }),
    );

    await act(async () => {
      within(card).getByRole("button", { name: "Apply" }).click();
    });
    const review = await waitFor(() => {
      const found = document.querySelector('[data-curio-add-review="true"]');
      expect(found).not.toBeNull();
      return found as HTMLElement;
    });
    expect(review).toHaveTextContent('Add "Bus counts"');
    expect(review).toHaveTextContent("Bob Test · v1.0.0");
    expect(writes()).toEqual([]);

    await act(async () => {
      within(review).getByRole("button", { name: "Add to project" }).click();
    });
    await waitFor(() =>
      expect(writes()).toEqual([`POST /api/dataflows/${ALICES}/packages/requests/${BOBS_REQUEST.proposalId}/apply`]),
    );
    view.unmount();
  });
});

describe("a node of bob's package", () => {
  // `nodeId` is a prop main's pill does not take.
  const Header = PackageMetaHeader as unknown as React.FC<Record<string, unknown>>;

  test.each([
    ["editor", "Waits for the dataflow's owner to add Bus counts to it."],
    ["owner", "Bob Test asks you to add Bus counts to this dataflow: review it in the Node Catalog."],
  ] as const)("says on %s's canvas that it waits for the owner", async (canvas, says) => {
    on(canvas);
    const view = render(
      <PackagePaletteProvider>
        <DatasetCatalogDrawerProvider>
          <Header
            pkg={{ packageId: "test.bus-counts", major: 1, version: "1.0.0", name: "Bus counts" }}
            category="computation"
            suggestionActive={false}
            nodeId="bus-node"
          />
        </DatasetCatalogDrawerProvider>
      </PackagePaletteProvider>,
    );

    const pill = await waitFor(() => {
      const waiting = view.container.querySelector('[data-curio-waits-for-owner="true"]');
      expect(waiting?.getAttribute("data-tooltip") ?? "").toContain(says);
      return waiting as HTMLElement;
    });
    expect(pill).toHaveTextContent("WAITING");
    view.unmount();
  });
});
