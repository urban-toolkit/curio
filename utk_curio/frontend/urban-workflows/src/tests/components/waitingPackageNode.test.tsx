/**
 * A node of a package bob, an editor alice invited, asked her to add, on a
 * canvas whose account does not hold the package: hers until she reviews his
 * request, or another editor's. The card says it waits for her review, in
 * place of the Missing node package card, whose Install leads nowhere: his
 * package is in no catalog she can add it from. On her canvas the card says
 * who asks and opens her review in the Node Catalog drawer; on another
 * editor's it says it waits for her.
 *
 * The canvas reads the requests through `fetch`, which answers here.
 */
import React from "react";
import { act, render, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";
import { ReactFlowProvider } from "reactflow";

jest.mock("vega", () => ({}), { virtual: true });
jest.mock("vega-lite", () => ({}), { virtual: true });

const mockOpenDrawer = jest.fn();
jest.mock("../../providers/packages/NodeCatalogDrawerProvider", () => ({
  useNodeCatalogDrawer: () => ({
    openNodeCatalogDrawer: mockOpenDrawer,
    closeNodeCatalogDrawer: jest.fn(),
    isNodeCatalogDrawerOpen: false,
  }),
}));
let mockFlow: Record<string, unknown> = {};
jest.mock("../../providers/FlowProvider", () => ({
  useFlowContext: () => ({
    projectId: null,
    viewerMode: "owner",
    projectName: "Bus plan",
    outputs: [],
    nodes: [],
    pendingInstalls: [],
    ensureProjectId: async () => null,
    ...mockFlow,
  }),
}));
let mockRole: string | null = null;
jest.mock("../../providers/CollaborationProvider", () => ({
  useCollab: () => ({ connected: true, users: [], lockedNodes: {}, role: mockRole, onRemote: () => () => undefined }),
}));
jest.mock("../../providers/ToastProvider", () => ({
  useToastContext: () => ({ showToast: jest.fn() }),
}));
jest.mock("../../components/apiSettings/useHostedGuest", () => ({
  useHostedGuest: () => false,
  hostedGuestSignInNote: (action: string) => `Sign in to ${action}.`,
}));

import { UnresolvedNode } from "../../components/UnresolvedNode";
import { DatasetCatalogDrawerProvider } from "../../providers/datasetCatalog";
import { clearCurrentProject, setCurrentProject } from "../../registry/projectPackagesStore";
import { invalidateDatasetCatalogCache } from "../../services/datasetCatalog";

const ALICES = "alices-dataflow";
const BUS_NODE = "test.bus-counts/count@1";
/** bob's request for his package, as the server lists it. */
const BOBS_REQUEST = {
  proposalId: "req-bus-counts",
  kind: "packages",
  tool: "package.install",
  status: "pending",
  summary: "Add package · Bus counts",
  preview: "Bus counts · v1.0.0 · Bob Test · from Bob Test's Node Catalog",
  dirName: "test.bus-counts@1",
  packageName: "Bus counts",
  packageKind: "node",
  version: "1.0.0",
  publisher: "Bob Test",
  permissions: [],
  shared: false,
  by: { kind: "person", account: "2", name: "Bob Test" },
  nodeIds: ["bus-node"],
};

const realFetch = global.fetch;
beforeEach(() => {
  global.fetch = jest.fn(async (url: RequestInfo | URL) => {
    const path = String(url).replace(/^.*?(?=\/api\/)/, "");
    const body = path === `/api/dataflows/${ALICES}/packages/requests` ? { requests: [BOBS_REQUEST] } : { requests: [] };
    return { ok: true, status: 200, json: async () => body } as unknown as Response;
  }) as unknown as typeof fetch;
});

afterEach(() => {
  global.fetch = realFetch;
  clearCurrentProject();
  mockFlow = {};
  mockRole = null;
});

function on(canvas: "owner" | "editor"): void {
  mockFlow = canvas === "owner" ? { projectId: ALICES, viewerMode: "owner" } : { projectId: null, viewerMode: "shared" };
  mockRole = canvas;
  setCurrentProject(ALICES, []);
  invalidateDatasetCatalogCache();
}

function renderNode() {
  return render(
    <ReactFlowProvider>
      <DatasetCatalogDrawerProvider>
        <UnresolvedNode nodeId="bus-node" nodeType={BUS_NODE} registryReady />
      </DatasetCatalogDrawerProvider>
    </ReactFlowProvider>,
  );
}

describe("a node of a package bob asked alice to add", () => {
  test("on her canvas says he asks her, and opens her review in the Node Catalog", async () => {
    on("owner");
    const reviews: unknown[] = [];
    const listen = (event: Event) => reviews.push((event as CustomEvent).detail);
    window.addEventListener("curio:review-editor-requests", listen);
    const view = renderNode();
    try {
      await waitFor(() =>
        expect(view.container).toHaveTextContent(
          "Bob Test asks you to add Bus counts to this dataflow: review it in the Node Catalog.",
        ),
      );
      expect(view.container).toHaveTextContent("Waiting for your review");
      expect(view.container).not.toHaveTextContent("Missing node package");

      await act(async () => {
        view.getByRole("button", { name: "Review…" }).click();
      });
      expect(reviews).toEqual(["node"]);
    } finally {
      window.removeEventListener("curio:review-editor-requests", listen);
      view.unmount();
    }
  });

  test("on another editor's canvas says it waits for her, with nothing to install", async () => {
    on("editor");
    const view = renderNode();

    await waitFor(() =>
      expect(view.container).toHaveTextContent("Waits for the dataflow's owner to add Bus counts to it."),
    );
    expect(view.container).toHaveTextContent("Waiting for the owner");
    expect(view.queryByRole("button")).toBeNull();
    view.unmount();
  });
});
