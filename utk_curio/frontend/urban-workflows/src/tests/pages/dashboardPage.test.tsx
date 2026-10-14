/**
 * The dashboard page: its bar, its states, and what it refuses to do.
 *
 * The page is a view someone may open from a link, so most of what matters here
 * is restraint: it offers no editor chrome, it cannot delete a node, it only
 * moves tiles for the owner, and its only write (Save layout) leaves the
 * dataflow's recorded outputs alone. The rest is being legible about which of
 * three empty-looking states it is in: still loading, nothing pinned, or a link
 * that does not open.
 */
import React from "react";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";

class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
(global as any).ResizeObserver = ResizeObserverStub;

const ID = "11111111-2222-3333-4444-555555555555";

let mockLoadState = "loaded";
let mockFlow: any = {};
let mockUser: any = { user: { name: "Owner", is_guest: false }, enableUserAuth: true };
let mockReactFlowProps: any = null;
let mockViewport = { x: 0, y: 0, zoom: 1 };
const mockShowToast = jest.fn();
const mockReactFlowInstance = {
  getNode: (id: string) => ({ id, data: { nodeId: id, comments: [{ text: "kept" }] } }),
  getNodes: () => [],
  fitView: jest.fn(),
  setViewport: jest.fn(),
};

jest.mock("reactflow", () => ({
  __esModule: true,
  default: (props: any) => {
    mockReactFlowProps = props;
    return <div data-testid="react-flow" />;
  },
  ConnectionMode: { Loose: "loose" },
  useReactFlow: () => mockReactFlowInstance,
  useViewport: () => mockViewport,
  // useViewportMotionHint reads the flow's wrapper from the store.
  useStoreApi: () => ({ getState: () => ({ domNode: null }) }),
}));
jest.mock("reactflow/dist/style.css", () => ({}), { virtual: true });
jest.mock("../../components/UniversalNode", () => ({ __esModule: true, default: () => null }));
jest.mock("../../components/edges/BiDirectionalEdge", () => ({ __esModule: true, default: () => null }));
jest.mock("../../components/edges/UniDirectionalEdge", () => ({ __esModule: true, default: () => null }));
jest.mock("../../components/VersionBadge", () => ({ __esModule: true, default: () => null }));
jest.mock("../../components/login/Loading", () => ({ Loading: () => <div data-testid="loading" /> }));
jest.mock("../../components/menus/top/ShareMenu", () => ({
  __esModule: true,
  default: (props: any) => (
    <div data-testid="share-menu" data-id={props.id} data-open-dashboard={String(props.includeOpenDashboard)} />
  ),
}));
jest.mock("../../components/ProjectLoader", () => ({
  useProjectLoadState: () => mockLoadState,
}));
jest.mock("../../utils/fitViewWithMenuOffset", () => ({
  fitViewWithMenuOffset: () => true,
  fitViewWithMenuOffsetNow: () => ({ x: 0, y: 0, zoom: 1 }),
}));
jest.mock("../../providers/FlowProvider", () => ({
  useFlowContext: () => mockFlow,
  useNodeActionsContext: () => ({ workflowName: "Chicago trips" }),
}));
jest.mock("../../providers/ToastProvider", () => ({
  useToastContext: () => ({ showToast: mockShowToast }),
}));
jest.mock("../../providers/UserProvider", () => ({
  useUserContext: () => mockUser,
}));

import DashboardPage, {
  LOAD_FAILED_BODY,
  LOAD_FAILED_TITLE,
  NOTHING_PINNED_TITLE,
} from "../../pages/dashboard/DashboardPage";
import { resetEmbeddedDashboardForTests } from "../../standalone/dashboardPayload";

function flow(over: Record<string, unknown> = {}) {
  return {
    nodes: [{ id: "chart", position: { x: 0, y: 0 }, data: {} }],
    edges: [],
    onNodesChange: jest.fn(),
    onEdgesChange: jest.fn(),
    dashboardPins: { chart: true },
    dashboardLocked: true,
    setDashboardLocked: jest.fn(),
    updateDataNode: jest.fn(),
    markDirty: jest.fn(),
    viewerMode: "owner",
    projectId: ID,
    projectName: "Chicago trips",
    projectDirty: false,
    saveCurrentProject: jest.fn().mockResolvedValue({}),
    ...over,
  };
}

async function renderPage() {
  let utils: ReturnType<typeof render>;
  await act(async () => {
    utils = render(
      <MemoryRouter initialEntries={[`/dashboard/${ID}`]}>
        <Routes>
          <Route path="/dashboard/:id" element={<DashboardPage />} />
          <Route path="/dataflow/:id" element={<div data-testid="canvas" />} />
          <Route path="/projects" element={<div data-testid="projects" />} />
        </Routes>
      </MemoryRouter>,
    );
  });
  return utils!;
}

beforeEach(() => {
  jest.clearAllMocks();
  mockLoadState = "loaded";
  mockFlow = flow();
  mockUser = { user: { name: "Owner", is_guest: false }, enableUserAuth: true };
  mockReactFlowProps = null;
});

describe("the bar", () => {
  test("is the shared top bar, holding only dashboard actions", async () => {
    const { container } = await renderPage();

    // The same GlobalPageHeader as the dataflow's bar and every section page
    // (identity-obj-proxy maps class names to themselves), so they look like
    // one product.
    const bar = container.querySelector("header.header[data-curio-menu-bar]");
    expect(bar).not.toBeNull();
    expect(bar!.querySelector(".logo")).not.toBeNull();
    expect(screen.getByRole("heading", { name: "Chicago trips" })).toBeTruthy();
    expect(screen.getByTestId("user-menu")).toBeTruthy();
    // None of the editor's menus, and none of its catalogs.
    for (const menu of ["File", "View", "Data", "Provenance"]) {
      expect(screen.queryByText(new RegExp(`^${menu}`))).toBeNull();
    }
    expect(screen.queryByRole("button", { name: /Catalog$/ })).toBeNull();
  });

  test("links back to the dataflow", async () => {
    await renderPage();

    const link = screen.getByTestId("open-dataflow-link");
    expect(link.getAttribute("href")).toBe(`/dataflow/${ID}`);
  });

  test("shares both links but does not offer to open itself", async () => {
    await renderPage();

    const share = screen.getByTestId("share-menu");
    expect(share.getAttribute("data-id")).toBe(ID);
    expect(share.getAttribute("data-open-dashboard")).toBe("false");
  });
});

describe("editing the layout", () => {
  test("the owner can unlock it", async () => {
    await renderPage();

    fireEvent.click(screen.getByTestId("edit-layout-btn"));

    expect(mockFlow.setDashboardLocked).toHaveBeenCalledWith(false);
  });

  test("saving writes the layout and leaves the outputs alone", async () => {
    mockFlow = flow({ dashboardLocked: false });
    await renderPage();

    await act(async () => { fireEvent.click(screen.getByTestId("save-layout-btn")); });

    expect(mockFlow.saveCurrentProject).toHaveBeenCalledWith(undefined, { omitOutputs: true });
    expect(mockFlow.setDashboardLocked).toHaveBeenCalledWith(true);
    expect(mockShowToast).toHaveBeenCalledWith("Dashboard layout saved.", "success");
  });

  test("a failed save says so and stays unlocked", async () => {
    mockFlow = flow({
      dashboardLocked: false,
      saveCurrentProject: jest.fn().mockRejectedValue(new Error("disk full")),
    });
    await renderPage();

    await act(async () => { fireEvent.click(screen.getByTestId("save-layout-btn")); });

    expect(mockShowToast).toHaveBeenCalledWith("disk full", "error");
    expect(mockFlow.setDashboardLocked).not.toHaveBeenCalled();
  });

  test("a visitor on a share link gets no edit controls, and is told why", async () => {
    mockFlow = flow({ viewerMode: "shared", projectId: null });
    await renderPage();

    expect(screen.queryByTestId("edit-layout-btn")).toBeNull();
    // The page looks editable and is not, so it says so, the way the canvas does.
    expect(screen.getByTestId("shared-view-banner").textContent).toContain("read-only");
  });

  test("a guest under auth gets no edit controls", async () => {
    mockUser = { user: { name: "Guest", is_guest: true }, enableUserAuth: true };
    await renderPage();

    expect(screen.queryByTestId("edit-layout-btn")).toBeNull();
  });

  test("the shared guest of a no-auth install can edit its own dataflow", async () => {
    // Everyone is the one guest there, and it owns the dataflows it saves.
    mockUser = { user: { name: "Guest", is_guest: true }, enableUserAuth: false };
    await renderPage();

    expect(screen.getByTestId("edit-layout-btn")).toBeTruthy();
  });
});

describe("a dashboard with scenarios", () => {
  // A loader the two scenarios share, each scenario's one tile, all pinned.
  const tile = (id: string, x: number, y: number) => ({
    id,
    position: { x, y },
    data: { nodeId: id, nodeType: "curio.builtin/computation-analysis", code: "return arg", title: id },
  });
  const withScenarios = (over: Record<string, unknown> = {}) =>
    flow({
      nodes: [tile("load", 0, 0), tile("a", 600, 0), tile("b", 600, 600)],
      edges: [
        { id: "e1", source: "load", target: "a", sourceHandle: "out", targetHandle: "in" },
        { id: "e2", source: "load", target: "b", sourceHandle: "out", targetHandle: "in" },
      ],
      dashboardPins: { load: true, a: true, b: true },
      scenarios: [
        { id: "base", name: "Baseline", color: "#2a9d8f", nodes: ["a"] },
        { id: "tall", name: "Twice as tall", color: "#e86a3c", nodes: ["b"] },
      ],
      ...over,
    });

  test("offers no Arrange by scenario, even while the owner edits a dashboard with a scenario's tiles", async () => {
    mockFlow = withScenarios({ dashboardLocked: false });
    await renderPage();
    expect(screen.queryByTestId("save-layout-btn")).toBeTruthy();
    expect(screen.queryByTestId("arrange-by-scenario-btn")).toBeNull();
    expect(screen.queryByText("Arrange by scenario")).toBeNull();
  });
});

describe("the canvas", () => {
  test("is locked by default: no drag, no pan, no zoom", async () => {
    await renderPage();

    expect(mockReactFlowProps.nodesDraggable).toBe(false);
    expect(mockReactFlowProps.panOnDrag).toBe(false);
    expect(mockReactFlowProps.zoomOnScroll).toBe(false);
    expect(mockReactFlowProps.nodesConnectable).toBe(false);
  });

  test("locked, its tiles still take the pointer, so their inputs can be set", async () => {
    await renderPage();

    // React Flow only keeps pointer events on a node it cannot drag or select
    // when a node handler is passed.
    expect(mockReactFlowProps.elementsSelectable).toBe(false);
    expect(typeof mockReactFlowProps.onNodeClick).toBe("function");
  });

  test("never enlarges a tile past its authored size", async () => {
    await renderPage();

    expect(mockReactFlowProps.maxZoom).toBe(1);
  });

  test("cannot delete a node, by key or by change", async () => {
    await renderPage();

    // React Flow's default is Backspace, and the provider would apply it.
    expect(mockReactFlowProps.deleteKeyCode).toBeNull();
    act(() => {
      mockReactFlowProps.onNodesChange([
        { type: "remove", id: "chart" },
        { type: "select", id: "chart", selected: true },
      ]);
    });
    expect(mockFlow.onNodesChange).toHaveBeenCalledWith([
      { type: "select", id: "chart", selected: true },
    ]);
  });

  test("moving a tile is an edit", async () => {
    mockFlow = flow({ dashboardLocked: false });
    await renderPage();

    act(() => {
      mockReactFlowProps.onNodesChange([
        { type: "position", id: "chart", position: { x: 5, y: 6 }, dragging: true },
      ]);
    });

    expect(mockFlow.markDirty).toHaveBeenCalled();
  });

  test("dropping a tile records its slot, keeping the rest of the node", async () => {
    mockFlow = flow({ dashboardLocked: false });
    await renderPage();

    act(() => {
      mockReactFlowProps.onNodeDragStop({}, { id: "chart", position: { x: 40, y: 80 }, data: {} });
    });

    // Read from the live node, so a comment or an input added meanwhile is not
    // clobbered by a stale copy.
    expect(mockFlow.updateDataNode).toHaveBeenCalledWith("chart", {
      nodeId: "chart",
      comments: [{ text: "kept" }],
      dashboardX: 40,
      dashboardY: 80,
    });
  });

  test("the test hooks the Playwright helpers read are exposed", async () => {
    await renderPage();

    expect((window as any).__curio_reactFlow).toBe(mockReactFlowInstance);
    expect(typeof (window as any).__curio_fitViewWithMenuOffset).toBe("function");
  });
});

describe("the states", () => {
  test("loading shows a spinner, not the empty message", async () => {
    mockLoadState = "loading";
    mockFlow = flow({ nodes: [], dashboardPins: {} });
    await renderPage();

    expect(screen.getByTestId("loading")).toBeTruthy();
    expect(screen.queryByText(NOTHING_PINNED_TITLE)).toBeNull();
  });

  test("nothing pinned says so, with a way to the dataflow", async () => {
    mockFlow = flow({ dashboardPins: {} });
    await renderPage();

    expect(screen.getByText(NOTHING_PINNED_TITLE)).toBeTruthy();
    expect(screen.getByText("Open the dataflow").getAttribute("href")).toBe(`/dataflow/${ID}`);
  });

  test("the empty state's way out asks before dropping an unsaved layout", async () => {
    // The top bar's "Open dataflow" always asked; this link, to the same place,
    // did not, so the same unsaved layout was protected on one control only.
    mockFlow = flow({ dashboardPins: {}, dashboardLocked: false, projectDirty: true });
    await renderPage();

    fireEvent.click(screen.getByText("Open the dataflow"));
    expect(screen.getByRole("dialog", { name: "Discard unsaved layout?" })).toBeTruthy();
    expect(screen.queryByTestId("canvas")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Stay here" }));
    expect(screen.queryByRole("dialog", { name: "Discard unsaved layout?" })).toBeNull();
    expect(screen.queryByTestId("canvas")).toBeNull();

    fireEvent.click(screen.getByText("Open the dataflow"));
    fireEvent.click(screen.getByRole("button", { name: "Discard and continue" }));
    expect(screen.getByTestId("canvas")).toBeTruthy();
  });

  test("with nothing unsaved, the empty state's link simply goes", async () => {
    mockFlow = flow({ dashboardPins: {} });
    await renderPage();

    fireEvent.click(screen.getByText("Open the dataflow"));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.getByTestId("canvas")).toBeTruthy();
  });

  test("a link that does not open says so", async () => {
    mockLoadState = "failed";
    mockFlow = flow({ nodes: [], dashboardPins: {} });
    await renderPage();

    expect(screen.getByText(LOAD_FAILED_TITLE)).toBeTruthy();
    expect(screen.queryByText(NOTHING_PINNED_TITLE)).toBeNull();
  });

  describe("a dashboard the server refused", () => {
    // The backend would not build it as a page of its own, so the page server
    // carried the backend's reason instead of the data (cli/static_server.py).
    const REASON = [
      "This dashboard needs 31.0 MB of data embedded in the page, over the 25.0 MB limit.",
      "",
      "Heaviest outputs:",
      "  trips-by-hour  31.0 MB  dataframe",
      "",
      "Aggregate or filter upstream of these nodes, or unpin the tiles that use them.",
    ].join("\n");

    beforeEach(() => {
      const el = document.createElement("script");
      el.id = "curio-dashboard-payload";
      el.type = "application/json";
      el.textContent = JSON.stringify({
        meta: { projectId: ID, name: "Chicago trips" },
        refused: { status: 413, message: REASON },
      });
      document.body.appendChild(el);
      resetEmbeddedDashboardForTests();
    });

    afterEach(() => {
      document.getElementById("curio-dashboard-payload")?.remove();
      resetEmbeddedDashboardForTests();
    });

    test("says why, in the server's own words", async () => {
      mockLoadState = "failed";
      mockFlow = flow({ nodes: [], dashboardPins: {} });
      await renderPage();

      const failed = screen.getByTestId("dashboard-load-failed");
      expect(failed.textContent).toContain(LOAD_FAILED_TITLE);
      // The whole reason, rows and all: the heaviest node is the thing to fix.
      expect(failed.textContent).toContain(REASON);
      expect(screen.queryByText(LOAD_FAILED_BODY)).toBeNull();
      expect(screen.queryByText(NOTHING_PINNED_TITLE)).toBeNull();
    });

    test("opens the dataflow as a page of its own, not inside this one", async () => {
      // The refused page carries nothing to open the dataflow with: routed to
      // within this document, the canvas would come up empty, as the page's
      // signed-out viewer. A full load of the link is the dataflow itself.
      mockLoadState = "failed";
      mockFlow = flow({ nodes: [], dashboardPins: {} });
      await renderPage();

      const link = screen.getByTestId("open-dataflow-link");
      expect(link.getAttribute("href")).toBe(`/dataflow/${ID}`);
      fireEvent.click(link);

      expect(screen.queryByTestId("canvas")).toBeNull();
    });
  });

  test("the owner gets no read-only notice", async () => {
    await renderPage();

    expect(screen.queryByTestId("shared-view-banner")).toBeNull();
  });

  test("the notice waits for the load, so it cannot flash on a page that fails", async () => {
    mockLoadState = "loading";
    mockFlow = flow({ viewerMode: "shared", projectId: null });
    await renderPage();

    expect(screen.queryByTestId("shared-view-banner")).toBeNull();
  });

  test("pinned tiles show no state overlay", async () => {
    await renderPage();

    expect(screen.queryByTestId("dashboard-empty")).toBeNull();
    expect(screen.queryByTestId("dashboard-load-failed")).toBeNull();
    expect(screen.queryByTestId("loading")).toBeNull();
  });
});

describe("the Run button", () => {
  const tile = () => screen.queryByTestId("dashboard-run-tile") as HTMLElement | null;
  const placeOf = () => ({ left: tile()!.style.left, top: tile()!.style.top });

  beforeEach(() => {
    mockViewport = { x: 0, y: 0, zoom: 1 };
  });

  test("is drawn over the canvas, never as a node of the graph", async () => {
    await renderPage();
    expect(tile()).not.toBeNull();
    expect(mockReactFlowProps.nodes).toBe(mockFlow.nodes);
    expect(Object.keys(mockReactFlowProps.nodeTypes)).toHaveLength(1);
  });

  test("stands above the top-left tile until it is moved, carried through the viewport", async () => {
    mockFlow = flow({
      nodes: [
        { id: "chart", position: { x: 200, y: 300 }, data: {} },
        { id: "map", position: { x: 80, y: 500 }, data: {} },
      ],
      dashboardPins: { chart: true, map: true },
    });
    mockViewport = { x: 10, y: -100, zoom: 0.5 };
    await renderPage();
    // (80, 300 - 64) in the page, at half size, panned by (10, -100).
    expect(placeOf()).toEqual({ left: "50px", top: "18px" });
  });

  test("stands where dataflow.dashboard.runButton says, kept on the canvas", async () => {
    mockFlow = flow({ dashboardSettings: { runButton: { x: 640, y: 120 } } });
    await renderPage();
    expect(placeOf()).toEqual({ left: "640px", top: "120px" });
    cleanup();

    mockFlow = flow({ dashboardSettings: { runButton: { x: -500, y: -500 } } });
    await renderPage();
    expect(placeOf()).toEqual({ left: "8px", top: "8px" });
  });

  test("moves only while the layout is edited, and the drop saves where it stands", async () => {
    await renderPage();
    expect(screen.queryByTestId("dashboard-run-resize")).toBeNull();
    cleanup();

    const setDashboardRunButton = jest.fn();
    mockFlow = flow({ dashboardLocked: false, setDashboardRunButton, dashboardSettings: { runButton: { x: 100, y: 100 } } });
    mockViewport = { x: 0, y: 0, zoom: 2 };
    await renderPage();
    const card = screen.getByTestId("dashboard-run-tile");
    fireEvent.pointerDown(card, { button: 0, clientX: 300, clientY: 300, pointerId: 1 });
    fireEvent.pointerMove(card, { button: 0, clientX: 340, clientY: 320, pointerId: 1 });
    // It follows the pointer at the zoom: 40px right is 20 in the page.
    expect(placeOf()).toEqual({ left: "240px", top: "220px" });
    fireEvent.pointerUp(card, { button: 0, clientX: 340, clientY: 320, pointerId: 1 });
    expect(setDashboardRunButton).toHaveBeenCalledWith({ x: 120, y: 110, width: 56, height: 44 });
    expect(mockFlow.updateDataNode).not.toHaveBeenCalled();
    expect(mockFlow.onNodesChange).not.toHaveBeenCalled();
  });

  test("a hosted guest runs its own dataflow from the page, but cannot move the button", async () => {
    mockUser = { user: { name: "Guest", is_guest: true }, enableUserAuth: true };
    mockFlow = flow({ dashboardLocked: false });
    await renderPage();
    expect(screen.queryByTestId("edit-layout-btn")).toBeNull();
    expect(tile()).not.toBeNull();
    expect(tile()!.getAttribute("data-editing")).toBeNull();
    expect(screen.queryByTestId("dashboard-run-resize")).toBeNull();
  });

  test("is not offered to a visitor, nor on a dashboard with nothing pinned", async () => {
    mockFlow = flow({ viewerMode: "shared" });
    await renderPage();
    expect(tile()).toBeNull();
    cleanup();

    mockFlow = flow({ dashboardPins: {} });
    await renderPage();
    expect(tile()).toBeNull();
  });
});

describe("a published dashboard's visitor", () => {
  test("runs it from the page, cannot move the button, and is told their runs are not saved", async () => {
    mockFlow = flow({ viewerMode: "shared", runsPublished: true });
    await renderPage();
    expect(screen.getByTestId("dashboard-run-tile")).not.toBeNull();
    expect(screen.queryByTestId("dashboard-run-resize")).toBeNull();
    expect(screen.getByTestId("shared-view-banner").textContent).toContain("Your runs are not saved");
  });

  test("without the run link, a visitor still has no Run button", async () => {
    mockFlow = flow({ viewerMode: "shared", runsPublished: false });
    await renderPage();
    expect(screen.queryByTestId("dashboard-run-tile")).toBeNull();
    expect(screen.getByTestId("shared-view-banner").textContent).toContain("read-only");
  });
});
