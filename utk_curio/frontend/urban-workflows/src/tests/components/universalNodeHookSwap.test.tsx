/**
 * A node's body starts again when the hook its descriptor holds changes, and
 * only then.
 *
 * A package that ships its own behavior (the Column Filter of
 * `curio.example-ui@1`) registers its hook from a bundle the registry loads for
 * the open dataflow's packages. Opening such a dataflow by its link, as a reload
 * does, builds the descriptors before that bundle has run: the node mounts with
 * the generic package hook (`usePackageNodeBehavior`), then the bundle registers
 * its hook and the registry is built again with it. The node's type is the
 * same, so its body was kept and called the new hook where the old one's hooks
 * were. React threw ("Should have a queue", its error 311) and the route's error
 * boundary replaced the whole canvas.
 *
 * A rebuild that keeps the hook keeps the body and what it holds. Every
 * registry refresh builds every descriptor again, and a template that ships a
 * starter has its hook wrapped (`withPackageStarter`) on each build.
 *
 * Drives the real registry: descriptors built by `registerPackageTemplates`
 * and replaced the way `loadInstalledPackages` replaces them. The browser
 * case is `test_package_node_reopens_e2e.py`.
 */
import React from "react";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";

// vega ships ESM Jest's default transform skips; nothing here draws a chart.
jest.mock("vega", () => ({}), { virtual: true });
jest.mock("vega-lite", () => ({}), { virtual: true });

// The parts of React Flow that need its store; the rest stays real.
jest.mock("reactflow", () => ({
  ...jest.requireActual("reactflow"),
  Handle: () => null,
  useEdges: () => [],
  useUpdateNodeInternals: () => () => undefined,
}));
jest.mock("../../components/styles", () => ({
  NodeContainer: ({ children }: any) => <div>{children}</div>,
}));
// The editor shows what the behavior draws, as its output tab does.
jest.mock("../../components/editing/NodeEditor", () => ({
  __esModule: true,
  default: ({ contentComponent }: any) => <div>{contentComponent}</div>,
}));
jest.mock("../../components/DescriptionModal", () => ({ __esModule: true, default: () => null }));
jest.mock("../../components/edges/OutputIcon", () => ({ OutputIcon: () => null }));
jest.mock("../../components/edges/InputIcon", () => ({ InputIcon: () => null }));
jest.mock("../../components/UnresolvedNode", () => ({ UnresolvedNode: () => null }));
jest.mock("../../components/agents/attach/NodeAgentBadges", () => ({ NodeAgentBadges: () => null }));
jest.mock("../../components/nodes/NodeOutcomeStrip", () => ({ NodeOutcomeStrip: () => null }));

// How many times the node's body mounted. `useNodeState` is the first hook the
// body calls, and the same one whichever behavior the body runs.
const mockBody = { mounts: 0 };
jest.mock("../../hook/useNodeState", () => {
  const React = require("react");
  return {
    useNodeState: (data: any) => {
      React.useEffect(() => {
        mockBody.mounts += 1;
      }, []);
      return {
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
      };
    },
  };
});
jest.mock("../../providers/FlowProvider", () => ({
  useFlowContext: () => ({
    signalNodeExecDone: () => {},
    dashboardOn: false,
    edges: [],
    nodes: [],
    isRunActive: false,
  }),
}));
jest.mock("../../providers/CollaborationProvider", () => ({
  useCollab: () => ({ enabled: false, lockedNodes: {}, currentUserId: null }),
}));

// The behavior and icon registries are filled before packagesClient pulls in
// the adapters, in the order packagesClient.test.ts uses.
import "../../registry/builtinBehaviors";
import "../../registry/iconRegistry";
import { registerPackageTemplates } from "../../registry/packagesClient";
import {
  clearPackageNodes,
  getNodeDescriptor,
  withSuspendedRegistryNotifications,
} from "../../registry/nodeRegistry";
import { registerBehavior } from "../../registry/behaviorRegistry";
import { usePackageNodeBehavior, withPackageStarter } from "../../adapters/node/packageNodeBehavior";
import UniversalNode from "../../components/UniversalNode";
import type { NodeBehaviorHook } from "../../registry/types";

type Pack = Parameters<typeof registerPackageTemplates>[0][number];

/**
 * A package with one node, as `GET /api/packages` lists it. Without a `source`
 * it has no editor and draws its own interface, as the Column Filter does; with
 * one it opens a code editor with that starter.
 */
function pack(packageId: string, behavior: string, source: string | null = null): Pack {
  return {
    packageId,
    major: 1,
    version: "1.0.0",
    name: packageId,
    publisher: "Test",
    description: "",
    license: null,
    permissions: [],
    lineage: null,
    templates: [{
      id: `${packageId}/filter@1`,
      templateId: "filter",
      label: "Filter",
      category: "computation",
      engine: "python",
      description: "",
      icon: null,
      iconRef: null,
      behavior,
      paletteOrder: null,
      editor: source ? "code" : "none",
      hasCode: source !== null,
      hasWidgets: false,
      hasGrammar: false,
      grammarId: null,
      badge: null,
      inputPorts: [{ types: ["DATAFRAME"], cardinality: "1" }],
      outputPorts: [{ types: ["DATAFRAME"], cardinality: "1" }],
      source,
      bidirectional: false,
      containerStyle: null,
      hasProvenance: null,
    }],
  };
}

/**
 * What `loadInstalledPackages` does with the installed packages, once a
 * package's bundle has registered its hooks: every package descriptor built
 * again, and the registry's listeners told once.
 */
function rebuildRegistry(...packs: Pack[]): void {
  withSuspendedRegistryNotifications(() => {
    clearPackageNodes();
    registerPackageTemplates(packs);
  });
}

/**
 * A package's own interface, with state first and hooks of other kinds and in
 * another number than the generic package hook's, as the Column Filter's
 * behavior has.
 */
const useOwnInterface: NodeBehaviorHook = () => {
  const [column] = React.useState("population");
  const [threshold] = React.useState(0);
  const rule = React.useMemo(() => `${column} > ${threshold}`, [column, threshold]);
  React.useEffect(() => undefined, [rule]);
  return { contentComponent: <span data-testid="own-interface">{rule}</span> };
};

/** A count the node's body keeps for as long as it stays mounted. */
const useCounter: NodeBehaviorHook = () => {
  const [count, setCount] = React.useState(0);
  return {
    contentComponent: (
      <button type="button" data-testid="count" onClick={() => setCount((n: number) => n + 1)}>
        {String(count)}
      </button>
    ),
  };
};

async function mount(data: Record<string, unknown>) {
  let utils!: ReturnType<typeof render>;
  await act(async () => {
    utils = render(<UniversalNode data={data} isConnectable />);
  });
  return utils;
}

/** Everything React said through `console.error` while *run* ran. */
function errorsWhile(run: () => void): string {
  const errors = jest.spyOn(console, "error");
  try {
    run();
    return errors.mock.calls.map((call) => call.map(String).join(" ")).join("\n");
  } finally {
    errors.mockRestore();
  }
}

/** What React says when one component's hooks change between renders. */
const HOOKS_CHANGED = /order of Hooks|Rendered (more|fewer) hooks|Should have a queue/;

beforeEach(() => {
  mockBody.mounts = 0;
});

afterEach(() => {
  // Unmounted first, so clearing the registry re-renders nothing.
  cleanup();
  clearPackageNodes();
});

describe("a node whose package's hook is registered after the node mounted", () => {
  test("starts its body again with that hook, rather than breaking the rules of hooks", async () => {
    const PACKAGE = "zz.test.late-hook";
    const BEHAVIOR = "zz-test-late-hook";
    const nodeType = `${PACKAGE}/filter@1`;
    // Built before the package's bundle has run, as on a reload or a link:
    // the node gets the generic package hook.
    rebuildRegistry(pack(PACKAGE, BEHAVIOR));
    expect(getNodeDescriptor(nodeType).adapter.useNodeBehavior).toBe(usePackageNodeBehavior);

    const data = { nodeId: "n1", nodeType, input: "" };
    const utils = await mount(data);
    expect(mockBody.mounts).toBe(1);
    expect(screen.queryByTestId("own-interface")).toBeNull();

    const said = errorsWhile(() => {
      // The bundle runs: its hook is registered, and the registry is built
      // again with it.
      act(() => {
        registerBehavior(BEHAVIOR, useOwnInterface);
        rebuildRegistry(pack(PACKAGE, BEHAVIOR));
      });
      // New data renders the body again, as the canvas hands a node whenever
      // anything in its data changes. On the same body this called the new
      // hook where the generic one's hooks were.
      act(() => {
        utils.rerender(<UniversalNode data={{ ...data }} isConnectable />);
      });
    });

    expect(getNodeDescriptor(nodeType).adapter.useNodeBehavior).toBe(useOwnInterface);
    expect(said).not.toMatch(HOOKS_CHANGED);
    expect(screen.getByTestId("own-interface")).toHaveTextContent("population > 0");
    expect(mockBody.mounts).toBe(2);
  });
});

describe("a registry rebuild that keeps a node's hook", () => {
  test.each([
    ["a template whose own behavior is registered", "zz.test.kept-own", null],
    ["a template that ships a starter, its behavior wrapped to inject it", "zz.test.kept-starter", "sources/filter.py"],
  ])("keeps the node's body and what the body holds: %s", async (_label, PACKAGE, source) => {
    const BEHAVIOR = `${PACKAGE}-counter`;
    const nodeType = `${PACKAGE}/filter@1`;
    registerBehavior(BEHAVIOR, useCounter);
    rebuildRegistry(pack(PACKAGE, BEHAVIOR, source));
    const before = getNodeDescriptor(nodeType);

    // Saved with code, so the starter injection leaves the node alone.
    const data = { nodeId: "n1", nodeType, input: "", code: "" };
    const utils = await mount(data);
    fireEvent.click(screen.getByTestId("count"));
    expect(screen.getByTestId("count")).toHaveTextContent("1");

    // Every refresh builds every descriptor again: an install, a dataflow's
    // second load, another package's bundle registering its hooks.
    act(() => rebuildRegistry(pack(PACKAGE, BEHAVIOR, source)));
    expect(getNodeDescriptor(nodeType)).not.toBe(before);
    act(() => {
      utils.rerender(<UniversalNode data={{ ...data }} isConnectable />);
    });

    expect(screen.getByTestId("count")).toHaveTextContent("1");
    expect(mockBody.mounts).toBe(1);
  });
});

describe("a template's hook across registry builds", () => {
  test("withPackageStarter wraps one hook into one function", () => {
    const inner: NodeBehaviorHook = () => ({});
    const other: NodeBehaviorHook = () => ({});
    expect(withPackageStarter(inner)).toBe(withPackageStarter(inner));
    expect(withPackageStarter(other)).not.toBe(withPackageStarter(inner));
  });

  test("two builds of a template that ships a starter hand out the same hook", () => {
    const PACKAGE = "zz.test.starter-builds";
    const BEHAVIOR = `${PACKAGE}-counter`;
    const nodeType = `${PACKAGE}/filter@1`;
    registerBehavior(BEHAVIOR, useCounter);
    rebuildRegistry(pack(PACKAGE, BEHAVIOR, "sources/filter.py"));
    const first = getNodeDescriptor(nodeType);
    rebuildRegistry(pack(PACKAGE, BEHAVIOR, "sources/filter.py"));
    const second = getNodeDescriptor(nodeType);

    expect(second).not.toBe(first);
    expect(second.adapter.useNodeBehavior).toBe(first.adapter.useNodeBehavior);
    // Still the wrapper that injects the starter, not the bare hook.
    expect(second.adapter.useNodeBehavior).not.toBe(useCounter);
  });
});
