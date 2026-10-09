/**
 * A Shift+drag over the canvas is React Flow's box selection, and MainCanvas
 * keeps no state of its own for it: the drag draws React Flow's selection box
 * and leaves MainCanvas unrendered, however many times the pointer moves, and
 * a drag around a node still selects that node and no other.
 *
 * MainCanvas is drawn with React Flow itself (`selectionKeyCode="Shift"`), its
 * providers, menus and panels stubbed. It reads the flow context once per
 * render, so the stub counts its renders. The nodes carry their size, which
 * jsdom cannot measure, so the selection box tests them by their bounds.
 */
import React from "react";
import { fireEvent, render } from "@testing-library/react";
import { ReactFlowProvider, type Node, type NodeChange } from "reactflow";

let mockCanvasRenders = 0;
let mockFlow: any = null;
const mockSetActivePackageKey = jest.fn();
const mockCollab = { broadcastNodeUpdated: jest.fn() };
const mockMotionHint = { onMoveStart: jest.fn(), onMove: jest.fn(), onMoveEnd: jest.fn() };
const mockDropScenario = jest.fn();

jest.mock("../../providers/FlowProvider", () => ({
  useFlowContext: () => {
    mockCanvasRenders += 1;
    return mockFlow;
  },
}));
jest.mock("../../providers/CollaborationProvider", () => ({ useCollab: () => mockCollab }));
jest.mock("../../providers/packages/PackagePaletteContext", () => ({
  usePackagePalette: () => ({ setActivePackageKey: mockSetActivePackageKey }),
}));
jest.mock("../../providers/ToastProvider", () => ({ useToastContext: () => ({ showToast: jest.fn() }) }));
jest.mock("../../providers/StarterProvider", () => ({ useStarterContext: () => ({ getStarters: jest.fn() }) }));
jest.mock("../../providers/agents", () => ({ AgentAttachmentsProvider: ({ children }: any) => <>{children}</> }));
jest.mock("../../components/datasets/catalog/datasetDetailsContext", () => ({
  useDatasetDetails: () => ({ openDatasetDetails: jest.fn() }),
  viewDatasetDetailsToast: jest.fn(),
}));
jest.mock("../../hook/useGraphEditGates", () => ({
  useGraphEditGates: () => ({ connect: true, drop: true, delete: true }),
}));
jest.mock("../../hook/usePosition", () => ({ usePosition: () => ({ getPosition: () => ({ x: 0, y: 0 }) }) }));
jest.mock("../../hook/useRunSelectedNodeShortcut", () => ({ useRunSelectedNodeShortcut: () => undefined }));
jest.mock("../../hook/useViewportMotionHint", () => ({ useViewportMotionHint: () => mockMotionHint }));
jest.mock("../../hook/useCode", () => ({ useCode: () => ({ createCodeNode: jest.fn() }) }));
jest.mock("../../hook/useSharedView", () => ({ useSharedView: () => false }));
jest.mock("../../components/UniversalNode", () => ({
  __esModule: true,
  default: ({ id }: any) => <div data-testid={`node-${id}`} />,
}));
jest.mock("../../components/edges/BiDirectionalEdge", () => ({ __esModule: true, default: () => null }));
jest.mock("../../components/edges/UniDirectionalEdge", () => ({ __esModule: true, default: () => null }));
jest.mock("../../components/VersionBadge", () => ({ __esModule: true, default: () => null }));
jest.mock("../../components/menus", () => ({ ToolsMenu: () => null, UpMenu: () => null }));
jest.mock("../../components/notebook/NotebookRunAll", () => ({ NotebookRunAll: () => null }));
jest.mock("../../components/collab/CollaborationSidePanel", () => ({ CollaborationSidePanel: () => null }));
jest.mock("../../components/layout/CanvasSidePanels", () => ({ CanvasSidePanels: () => null }));
jest.mock("../../components/agents/attach/AgentDockOverlay", () => ({ AgentDockOverlay: () => null }));
jest.mock("../../components/scenarios/useScenarioDrop", () => ({ useScenarioDrop: () => mockDropScenario }));
jest.mock("../../components/scenarios/ScenarioLayers", () => ({ BOX_WIDTH: 0, boxLayout: () => ({ height: 0 }) }));
jest.mock("../../components/scenarios/CanvasScenarioLayers", () => ({ CanvasScenarioLayers: () => null }));
jest.mock("../../components/scenarios/ScenariosPanel", () => ({ ScenariosPanel: () => null }));
jest.mock("../../services/datasetCatalog", () => ({
  buildDatasetLoaderNodeOptions: jest.fn(),
  hasDatasetDrag: () => false,
  readDatasetDragPayload: () => null,
}));
jest.mock("../../services/modelCatalog", () => ({
  hasModelDrag: () => false,
  modelNodeForCanvas: () => null,
  readModelDragPayload: () => null,
}));
jest.mock("../../services/scenarioCatalog/scenarioDrag", () => ({
  endScenarioDrag: jest.fn(),
  hasScenarioDrag: () => false,
  readScenarioDragPayload: () => null,
}));
jest.mock("../../services/agents", () => ({
  agentsApi: {},
  readAgentDragCoord: () => null,
  notifyAgentDockRefresh: jest.fn(),
  resolveAgentDropTarget: jest.fn(),
  hasAgentDrag: () => false,
}));
jest.mock("../../adapters/node/packageNodeBehavior", () => ({ packageStarterCode: jest.fn() }));
jest.mock("../../registry/nodeRegistry", () => ({ getAllNodeTypes: () => [], getPaletteNodeTypes: () => [] }));
jest.mock("../../registry/packageKeys", () => ({ packageKeyFromCanonicalNodeType: () => null }));
jest.mock("../../utils/flowNodeCanonicalType", () => ({ getFlowNodeCanonicalType: () => "" }));
jest.mock("../../utils/agentDropHover", () => ({ clearAgentDropHover: jest.fn(), setAgentDropHoverEdgeId: jest.fn() }));
jest.mock("../../utils/agentDropAttach", () => ({ attachAgentOnDrop: jest.fn() }));
jest.mock("../../utils/focusDatasetNodes", () => ({ frameNodesInView: jest.fn() }));
jest.mock("../../utils/scenarios/scenarioCanvasView", () => ({
  scenarioCanvasView: (nodes: unknown, edges: unknown) => ({ nodes, edges, boxes: [] }),
}));
// Wide enough that React Flow keeps the view where it starts: zoom 1, no pan.
jest.mock("../../utils/canvasExtent", () => ({
  computeTranslateExtent: () => [[-100000, -100000], [100000, 100000]],
}));
jest.mock("../../utils/notebookLayout", () => ({ notebookFlowProps: () => ({}) }));
jest.mock("../../utils/fitViewWithMenuOffset", () => ({
  CANVAS_TITLE_ATTR: "data-curio-canvas-title",
  fitViewWithMenuOffset: jest.fn(),
  fitViewWithMenuOffsetNow: jest.fn(),
  topOverlayBottom: () => null,
}));

import { CURIO_UNIVERSAL_NODE_TYPE } from "../../constants";
import { MainCanvas } from "../../components/MainCanvas";

// jsdom polyfills React Flow needs (as in mainCanvasNodeDoubleClick).
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
(global as any).ResizeObserver = ResizeObserverStub;
if (!(global as any).DOMMatrixReadOnly) {
  (global as any).DOMMatrixReadOnly = class { m22 = 1; constructor() {} };
}

/** Two nodes, 100 x 60: "a" at (100, 100) and "b" at (400, 300). */
function twoNodes(): Node[] {
  return [
    { id: "a", type: CURIO_UNIVERSAL_NODE_TYPE, position: { x: 100, y: 100 }, width: 100, height: 60, data: {} },
    { id: "b", type: CURIO_UNIVERSAL_NODE_TYPE, position: { x: 400, y: 300 }, width: 100, height: 60, data: {} },
  ];
}

beforeEach(() => {
  mockCanvasRenders = 0;
  mockFlow = {
    nodes: twoNodes(),
    edges: [],
    loading: false,
    projectId: "project",
    onNodesChange: jest.fn(),
    onEdgesChange: jest.fn(),
    onConnect: jest.fn(),
    isValidConnection: () => true,
    onEdgesDelete: jest.fn(),
    onNodesDelete: jest.fn(),
    markDirty: jest.fn(),
    saveCurrentProject: jest.fn(),
    notebookOn: false,
    notebookContentHeight: 0,
    setNotebookPane: jest.fn(),
    registerNotebookScroller: jest.fn(),
    revealNodes: jest.fn(),
    scenarios: [],
  };
});

function drawCanvas() {
  const view = render(
    <ReactFlowProvider>
      <MainCanvas />
    </ReactFlowProvider>,
  );
  const pane = view.container.querySelector(".react-flow__pane") as HTMLElement;
  return { container: view.container, pane };
}

/**
 * Shift held, a press on the empty canvas at *from*, the pointer moved to *to*
 * in *moves* steps, released. *whileDragging* runs before the release.
 */
function shiftDrag(
  pane: HTMLElement,
  from: [number, number],
  to: [number, number],
  moves: number,
  whileDragging: () => void = () => undefined,
) {
  fireEvent.keyDown(document.body, { key: "Shift", code: "ShiftLeft", shiftKey: true });
  fireEvent.mouseDown(pane, { button: 0, buttons: 1, clientX: from[0], clientY: from[1], shiftKey: true });
  for (let step = 1; step <= moves; step += 1) {
    fireEvent.mouseMove(pane, {
      buttons: 1,
      clientX: from[0] + ((to[0] - from[0]) * step) / moves,
      clientY: from[1] + ((to[1] - from[1]) * step) / moves,
      shiftKey: true,
    });
  }
  whileDragging();
  fireEvent.mouseUp(pane, { button: 0, clientX: to[0], clientY: to[1], shiftKey: true });
  fireEvent.keyUp(document.body, { key: "Shift", code: "ShiftLeft" });
}

test("a Shift+drag over the empty canvas draws React Flow's selection box and does not render MainCanvas", () => {
  const { container, pane } = drawCanvas();
  const rendersAtRest = mockCanvasRenders;
  let boxDrawn = false;
  // Clear of both nodes: the box selects nothing.
  shiftDrag(pane, [600, 100], [700, 200], 5, () => {
    boxDrawn = container.querySelector(".react-flow__selection") !== null;
  });
  expect({
    rendered: rendersAtRest > 0,
    boxDrawn,
    rendersDuringTheDrag: mockCanvasRenders - rendersAtRest,
  }).toEqual({ rendered: true, boxDrawn: true, rendersDuringTheDrag: 0 });
});

test("a Shift+drag around a node selects that node and no other", () => {
  const { pane } = drawCanvas();
  // From below and right of "a" to above and left of it; "b" stays outside.
  shiftDrag(pane, [230, 190], [80, 80], 5);
  const selections = mockFlow.onNodesChange.mock.calls
    .flatMap(([changes]: [NodeChange[]]) => changes)
    .filter((change: NodeChange) => change.type === "select");
  expect(selections).toEqual([{ id: "a", type: "select", selected: true }]);
});
