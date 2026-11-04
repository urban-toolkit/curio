/**
 * The canvas of another account's dataflow, opened from its link, draws the
 * nodes of the packages that dataflow uses which this account does not hold.
 *
 * alice's dataflow uses her package `ai.test.flood-tools@1`, which bob, an
 * editor she invited, and erin, who watches, do not hold. Their canvases drew
 * its node as "No installed package provides ...": the registry was built
 * from their own stores alone. A canvas opened from the dataflow's link now
 * also lists the packages the dataflow uses from her store, read-only
 * (`GET /api/packages/dataflows/<id>`), and draws their nodes. bob's runs use
 * her copy, so his node has its Play; erin's runs read none of her packages,
 * so hers has none. A package the account holds stays its own copy, and
 * alice's canvas of her own dataflow asks for nothing more.
 *
 * Drives the real registry through `refreshPackageRegistry`, as ProjectLoader
 * calls it once a dataflow opened from its link has loaded
 * (`projectLoaderTrustedDeps.test.tsx`), and the node as the canvas renders
 * it. The node's header draws Play with `NodeRunControls`, as NodeContainer
 * does; the backend is a fake behind `apiFetch`.
 */
import React from "react";
import { act, cleanup, render } from "@testing-library/react";

// vega ships ESM Jest's default transform skips; nothing here draws a chart.
jest.mock("vega", () => ({}), { virtual: true });
jest.mock("vega-lite", () => ({}), { virtual: true });

// The backend: what each package listing answers (`backendHolds`).
const mockApiFetch = jest.fn();
jest.mock("../../utils/authApi", () => ({
  ...jest.requireActual("../../utils/authApi"),
  getToken: () => "a-session-token",
  apiFetch: (...args: unknown[]) => mockApiFetch(...args),
}));

// The parts of React Flow that need its store; the rest stays real.
jest.mock("reactflow", () => ({
  ...jest.requireActual("reactflow"),
  Handle: () => null,
  useEdges: () => [],
  useUpdateNodeInternals: () => () => undefined,
}));
// The node's header: Play, drawn by NodeRunControls as NodeContainer draws it.
jest.mock("../../components/styles", () => {
  const { NodeRunControls } = jest.requireActual("../../components/nodes/NodeRunControls");
  return {
    NodeContainer: ({ children, disablePlay }: any) => (
      <div>
        <NodeRunControls
          nodeId="n1"
          part="play"
          disablePlay={!!disablePlay}
          isLoading={false}
          showSaveToggle={false}
          saveOutput={false}
          onSaveOutputChange={() => undefined}
          onPlay={() => undefined}
        />
        {children}
      </div>
    ),
  };
});
jest.mock("../../components/editing/NodeEditor", () => ({ __esModule: true, default: () => null }));
jest.mock("../../components/DescriptionModal", () => ({ __esModule: true, default: () => null }));
jest.mock("../../components/edges/OutputIcon", () => ({ OutputIcon: () => null }));
jest.mock("../../components/edges/InputIcon", () => ({ InputIcon: () => null }));
jest.mock("../../components/UnresolvedNode", () => ({
  UnresolvedNode: ({ nodeType }: any) => <div data-testid="unresolved-node">{nodeType}</div>,
  unresolvedNodeMessage: (nodeType: string) => `No installed package provides ${nodeType}`,
}));
jest.mock("../../components/agents/attach/NodeAgentBadges", () => ({ NodeAgentBadges: () => null }));
jest.mock("../../components/nodes/NodeOutcomeStrip", () => ({ NodeOutcomeStrip: () => null }));
jest.mock("../../hook/useNodeState", () => ({
  useNodeState: (data: any) => ({
    output: { code: "", content: "" },
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

// Whose canvas it is. alice's opens her own dataflow; bob's and erin's open it
// from its link (`viewerMode` "shared"), with their role in its room.
const mockCanvas: { viewerMode: "owner" | "shared"; role: string } = { viewerMode: "owner", role: "owner" };
jest.mock("../../providers/FlowProvider", () => ({
  useFlowContext: () => ({
    signalNodeExecDone: () => {},
    dashboardOn: false,
    edges: [],
    nodes: [],
    isRunActive: false,
    projectId: "flood-check",
    viewerMode: mockCanvas.viewerMode,
  }),
}));
jest.mock("../../providers/CollaborationProvider", () => ({
  useCollab: () => ({ lockedNodes: {}, role: mockCanvas.role }),
}));

// The behavior and icon registries are filled before packagesClient pulls in
// the adapters, in the order packagesClient.test.ts uses.
import "../../registry/builtinBehaviors";
import "../../registry/iconRegistry";
import { refreshPackageRegistry } from "../../registry/packageRegistryBootstrap";
import { clearCurrentProject, setCurrentProject } from "../../registry/projectPackagesStore";
import { clearPackageNodes, tryGetNodeDescriptor } from "../../registry/nodeRegistry";
import UniversalNode from "../../components/UniversalNode";

/** alice's dataflow. */
const PID = "flood-check";
const TOOLS = "ai.test.flood-tools";
const TOOLS_DIR = `${TOOLS}@1`;
/** The type of its node of her package. */
const DEPTH = `${TOOLS}/depth@1`;

/**
 * alice's package as the package listings give it: one node, which draws its
 * own interface with a behavior that has not loaded, so the generic package
 * hook draws it.
 */
const FLOOD_TOOLS = {
  packageId: TOOLS,
  major: 1,
  version: "1.0.0",
  name: "Flood tools",
  publisher: "Test",
  description: "",
  license: "MIT",
  permissions: [],
  lineage: null,
  dirName: TOOLS_DIR,
  templates: [{
    id: DEPTH,
    templateId: "depth",
    label: "Depth",
    category: "computation",
    engine: "python",
    description: "",
    icon: null,
    iconRef: null,
    behavior: "ai-test-flood-depth",
    paletteOrder: null,
    editor: "none",
    hasCode: false,
    hasWidgets: false,
    hasGrammar: false,
    grammarId: null,
    badge: null,
    inputPorts: [{ types: ["DATAFRAME"], cardinality: "1" }],
    outputPorts: [{ types: ["DATAFRAME"], cardinality: "1" }],
    source: null,
    bidirectional: false,
    containerStyle: null,
    hasProvenance: null,
  }],
};

/** The backend: *own* are the packages of the signed-in account's store, and
 *  her dataflow uses her package, which its listing gives read-only. */
function backendHolds(own: unknown[]): void {
  mockApiFetch.mockImplementation(async (path: string) => {
    if (path === "/api/packages") return { packages: own };
    if (path === `/api/packages/dataflows/${PID}`) return { packages: [{ ...FLOOD_TOOLS, readOnly: true }] };
    throw Object.assign(new Error(`not found: ${path}`), { status: 404 });
  });
}

/** The canvas opens alice's dataflow: pinned, loaded, then the registry is
 *  refreshed, with the dataflow's id when it was opened from its link. */
async function open(own: unknown[], { fromItsLink }: { fromItsLink: boolean }): Promise<void> {
  backendHolds(own);
  setCurrentProject(PID, [TOOLS_DIR]);
  await act(async () => {
    await (fromItsLink ? refreshPackageRegistry({ openedFromLink: PID }) : refreshPackageRegistry());
  });
}

/** Her node, on the canvas of *viewerMode* with *role* in the room. */
async function draw(viewerMode: "owner" | "shared", role: string) {
  mockCanvas.viewerMode = viewerMode;
  mockCanvas.role = role;
  let utils!: ReturnType<typeof render>;
  await act(async () => {
    utils = render(<UniversalNode data={{ nodeId: "n1", nodeType: DEPTH, input: "" }} isConnectable />);
  });
  return utils;
}

const play = (container: HTMLElement) => container.querySelector("svg.fa-circle-play");

afterEach(() => {
  // Unmounted first, so clearing the registry re-renders nothing.
  cleanup();
  clearPackageNodes();
  clearCurrentProject();
  mockApiFetch.mockReset();
});

describe("alice's dataflow, opened from its link by an account that does not hold her package", () => {
  test("lists the packages her dataflow uses from her store, and registers her copy's nodes", async () => {
    await open([], { fromItsLink: true });

    expect(mockApiFetch).toHaveBeenCalledWith(`/api/packages/dataflows/${PID}`);
    expect(tryGetNodeDescriptor(DEPTH)?.package).toMatchObject({ packageId: TOOLS, ownersCopy: true });
  });

  test("an editor's canvas draws her package's node, with its Play", async () => {
    await open([], { fromItsLink: true });
    const { container, queryByTestId } = await draw("shared", "editor");

    expect(queryByTestId("unresolved-node")).toBeNull();
    expect(play(container)).not.toBeNull();
  });

  test("a watcher's canvas draws it too, with no Play", async () => {
    await open([], { fromItsLink: true });
    const { container, queryByTestId } = await draw("shared", "watcher");

    expect(queryByTestId("unresolved-node")).toBeNull();
    expect(play(container)).toBeNull();
  });
});

describe("what stays as it was", () => {
  test("a package the account holds is drawn from its own copy, with its Play on a watcher's canvas too", async () => {
    await open([FLOOD_TOOLS], { fromItsLink: true });
    expect(tryGetNodeDescriptor(DEPTH)?.package?.ownersCopy).toBeUndefined();

    const { container } = await draw("shared", "watcher");
    expect(play(container)).not.toBeNull();
  });

  test("alice's canvas of her own dataflow asks for nothing more", async () => {
    await open([FLOOD_TOOLS], { fromItsLink: false });
    expect(mockApiFetch).not.toHaveBeenCalledWith(`/api/packages/dataflows/${PID}`);
    expect(tryGetNodeDescriptor(DEPTH)?.package?.ownersCopy).toBeUndefined();

    const { container } = await draw("owner", "owner");
    expect(play(container)).not.toBeNull();
  });
});
