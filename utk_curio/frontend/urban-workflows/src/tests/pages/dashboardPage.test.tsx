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
import { act, fireEvent, render, screen } from "@testing-library/react";
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
}));
jest.mock("reactflow/dist/style.css", () => ({}), { virtual: true });
jest.mock("../../components/UniversalNode", () => ({ __esModule: true, default: () => null }));
jest.mock("../../components/edges/BiDirectionalEdge", () => ({ __esModule: true, default: () => null }));
jest.mock("../../components/edges/UniDirectionalEdge", () => ({ __esModule: true, default: () => null }));
jest.mock("../../components/VersionBadge", () => ({ __esModule: true, default: () => null }));
jest.mock("../../components/login/Loading", () => ({ Loading: () => <div data-testid="loading" /> }));
jest.mock("../../components/login/UserMenu", () => ({ UserMenu: () => <div data-testid="user-menu" /> }));
jest.mock("../../components/menus/top/ShareMenu", () => ({
  __esModule: true,
  default: (props: any) => (
    <div data-testid="share-menu" data-id={props.id} data-open-dashboard={String(props.includeOpenDashboard)} />
  ),
}));
jest.mock("../../components/ProjectLoader", () => ({
  useProjectLoadState: () => mockLoadState,
}));
jest.mock("../../utils/fitViewWithMenuOffset", () => ({ fitViewWithMenuOffset: () => true }));
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
  LOAD_FAILED_TITLE,
  NOTHING_PINNED_TITLE,
} from "../../pages/dashboard/DashboardPage";

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
  test("is the dataflow bar's bar, holding only dashboard actions", async () => {
    const { container } = await renderPage();

    // The same stylesheet as the dataflow's bar (identity-obj-proxy maps class
    // names to themselves), so the two look like one product.
    const bar = container.querySelector(".menuBar");
    expect(bar).not.toBeNull();
    expect(bar!.querySelector(".logo")).not.toBeNull();
    expect(screen.getByRole("heading", { name: "Chicago trips" })).toBeTruthy();
    expect(screen.getByTestId("user-menu")).toBeTruthy();
    // None of the editor's menus.
    for (const menu of ["File", "View", "Data", "Provenance", "Help"]) {
      expect(screen.queryByText(new RegExp(`^${menu}`))).toBeNull();
    }
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

describe("the canvas", () => {
  test("is locked by default: no drag, no pan, no zoom", async () => {
    await renderPage();

    expect(mockReactFlowProps.nodesDraggable).toBe(false);
    expect(mockReactFlowProps.panOnDrag).toBe(false);
    expect(mockReactFlowProps.zoomOnScroll).toBe(false);
    expect(mockReactFlowProps.nodesConnectable).toBe(false);
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

  test("a link that does not open says so", async () => {
    mockLoadState = "failed";
    mockFlow = flow({ nodes: [], dashboardPins: {} });
    await renderPage();

    expect(screen.getByText(LOAD_FAILED_TITLE)).toBeTruthy();
    expect(screen.queryByText(NOTHING_PINNED_TITLE)).toBeNull();
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
