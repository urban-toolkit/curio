/**
 * A loader on the canvas opens on its preview, in a smaller box, folds to its
 * typed chip, and its view is saved and shared
 * (plans/data-loading-expressive-preview-memo.md, sections 3.4 to 3.6).
 */
import React from "react";
import { act, render } from "@testing-library/react";

const mockContainer = jest.fn();
const mockEditor = jest.fn();
const mockUpdateDataNode = jest.fn();
const mockMarkDirty = jest.fn();
let mockDescriptorId = "curio.builtin/data-loading";
let mockViewerMode: string | undefined;

jest.mock("reactflow", () => ({
  Handle: () => null,
  useEdges: () => [],
  useUpdateNodeInternals: () => () => undefined,
}));
jest.mock("../../components/styles", () => ({
  NodeContainer: (props: any) => {
    mockContainer(props);
    return <div>{props.children}</div>;
  },
}));
jest.mock("../../components/editing/NodeEditor", () => ({
  __esModule: true,
  default: (props: any) => {
    mockEditor(props);
    return null;
  },
}));
jest.mock("../../components/DescriptionModal", () => ({ __esModule: true, default: () => null }));
jest.mock("../../components/edges/OutputIcon", () => ({ OutputIcon: () => null }));
jest.mock("../../components/edges/InputIcon", () => ({ InputIcon: () => null }));
jest.mock("../../components/UnresolvedNode", () => ({ UnresolvedNode: () => null }));
jest.mock("../../components/agents/attach/NodeAgentBadges", () => ({ NodeAgentBadges: () => null }));
jest.mock("../../components/nodes/NodeOutcomeStrip", () => ({ NodeOutcomeStrip: () => null }));
jest.mock("../../registry/nodeRegistry", () => {
  // One object per id, as the registry keeps them: a new one per read makes
  // useSyncExternalStore re-render forever.
  const made = new Map<string, any>();
  const descriptor = () => {
    if (!made.has(mockDescriptorId)) made.set(mockDescriptorId, build());
    return made.get(mockDescriptorId);
  };
  const build = () => ({
    id: mockDescriptorId,
    category: mockDescriptorId.includes("computation") ? "computation" : "data",
    hasCode: true,
    hasGrammar: false,
    hasWidgets: true,
    inputPorts: [],
    outputPorts: [{ types: ["DATAFRAME", "GEODATAFRAME", "RASTER"] }],
    adapter: {
      handles: [],
      editor: {},
      container: { nodeWidth: 320, nodeHeight: 380 },
      useNodeBehavior: () => ({}),
    },
  });
  return {
    getNodeDescriptor: () => descriptor(),
    tryGetNodeDescriptor: () => descriptor(),
    subscribeToRegistry: () => () => {},
  };
});
jest.mock("../../registry/registryReadiness", () => ({
  isRegistryReady: () => true,
  subscribeToRegistryReady: () => () => {},
}));
jest.mock("../../hook/useNodeState", () => ({
  useNodeState: (data: any) => ({
    output: data.output ?? { code: "", content: "" },
    setOutput: () => {},
    code: data.code ?? "",
    setCode: () => {},
    sendCode: undefined,
    setSendCodeCallback: () => {},
    templateData: {},
    user: null,
    promptDescription: () => {},
    closeDescription: () => {},
    showDescriptionModal: false,
  }),
}));
// Stable, as the real context's are: a new array per render re-runs every
// effect keyed on them.
const mockEmpty: any[] = [];
jest.mock("../../providers/FlowProvider", () => ({
  useFlowContext: () => ({
    signalNodeExecDone: () => {},
    dashboardOn: false,
    edges: mockEmpty,
    nodes: mockEmpty,
    outputs: mockEmpty,
    projectId: null,
    viewerMode: mockViewerMode,
    updateDataNode: mockUpdateDataNode,
    markDirty: mockMarkDirty,
  }),
}));
jest.mock("../../providers/CollaborationProvider", () => ({
  useCollab: () => ({ enabled: false, lockedNodes: {}, currentUserId: null, proposals: [] }),
}));

import UniversalNode from "../../components/UniversalNode";
import { LOADER_CHIP_HEIGHT, LOADER_CHIP_WIDTH, LOADER_PREVIEW_HEIGHT } from "../../utils/loaderView";

const CATALOG_LOADER = 'gdf = curio_load_data("data.utk.chicago-community-areas")\nreturn gdf';

function nodeData(extra: Record<string, unknown> = {}) {
  return {
    nodeId: "n1",
    nodeType: mockDescriptorId,
    input: "",
    code: CATALOG_LOADER,
    nodeHeight: 380,
    datasetSource: {
      datasetId: "data.utk.chicago-community-areas",
      title: "Chicago community areas",
      format: "geojson",
      origin: "imported",
    },
    ...extra,
  };
}

const lastContainer = () => mockContainer.mock.calls[mockContainer.mock.calls.length - 1][0];
const lastEditor = () => mockEditor.mock.calls[mockEditor.mock.calls.length - 1][0];

async function mount(data: any) {
  let utils: ReturnType<typeof render>;
  await act(async () => {
    utils = render(<UniversalNode data={data} isConnectable />);
  });
  return utils!;
}

beforeEach(() => {
  jest.clearAllMocks();
  mockDescriptorId = "curio.builtin/data-loading";
  mockViewerMode = undefined;
});

describe("a loader with code (an example, an older dataflow, a palette drop)", () => {
  test("opens on its preview, in the preview's smaller box, without the dataset pill", async () => {
    await mount(nodeData());
    expect(lastEditor().loaderPreview.view).toBe("preview");
    expect(lastContainer()).toMatchObject({
      nodeHeight: LOADER_PREVIEW_HEIGHT,
      heightKey: "loaderPreviewHeight",
      hideDatasetPill: true,
      minimizedBox: { width: LOADER_CHIP_WIDTH, height: LOADER_CHIP_HEIGHT },
    });
  });

  test("folds to a chip that names its type and source", async () => {
    await mount(nodeData());
    expect(lastContainer().minimizedLabel).toBe(
      "Data Loading · Loads GeoJSON from the Data Catalog: Chicago community areas",
    );
    expect(lastContainer().minimizedContent.props).toMatchObject({ dataType: "geojson" });
  });

  test("its toggle saves the other view on the node and marks the dataflow changed", async () => {
    await mount(nodeData());
    act(() => lastEditor().loaderPreview.onToggle());
    expect(mockUpdateDataNode).toHaveBeenCalledWith("n1", expect.objectContaining({ loaderView: "code" }));
    expect(mockMarkDirty).toHaveBeenCalled();
  });

  test("in code mode, uses the node's own height and shows its dataset pill", async () => {
    await mount(nodeData({ loaderView: "code" }));
    expect(lastEditor().loaderPreview.view).toBe("code");
    expect(lastContainer()).toMatchObject({ nodeHeight: 380, heightKey: "nodeHeight", hideDatasetPill: false });
  });

  test("a resized preview keeps its own height", async () => {
    await mount(nodeData({ loaderPreviewHeight: 230 }));
    expect(lastContainer().nodeHeight).toBe(230);
  });

  test("a viewer who cannot save toggles on their screen only", async () => {
    mockViewerMode = "shared";
    await mount(nodeData());
    act(() => lastEditor().loaderPreview.onToggle());
    expect(mockUpdateDataNode).not.toHaveBeenCalled();
    expect(lastEditor().loaderPreview.view).toBe("code");
  });
});

describe("an empty loader (the bare Data Loading tool)", () => {
  test("opens on its editor and cannot preview", async () => {
    const data: any = nodeData({ code: "" });
    await mount(data);
    expect(lastEditor().loaderPreview).toMatchObject({ view: "code", canPreview: false });
    expect(lastContainer().nodeHeight).toBe(380);
  });

  test("keeps its editor while it is being written", async () => {
    const data: any = nodeData({ code: "" });
    await mount(data);
    expect(data.loaderView).toBe("code");
  });
});

describe("a node that is not a loader", () => {
  test("has no preview and folds to its kind's icon", async () => {
    mockDescriptorId = "curio.builtin/computation-analysis";
    await mount(nodeData({ inputPorts: [] }));
    expect(lastEditor().loaderPreview).toBeUndefined();
    expect(lastContainer()).toMatchObject({ minimizedContent: undefined, heightKey: "nodeHeight", hideDatasetPill: false });
  });
});
