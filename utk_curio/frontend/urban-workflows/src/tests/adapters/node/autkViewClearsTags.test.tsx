/**
 * An Autark node's selection tags are emptied each time it draws (#884). A run
 * draws its map or plot anew, and a pick or a brush made in it does not come
 * back, so a node reading one of its tags would otherwise read a pick the node
 * no longer shows. The node is the one the canvas registers for
 * `autk-grammar` (registry/builtinBehaviors), its draw stubbed here.
 */
// The built-in behaviors pull in vega and vega-lite, whose ESM Jest's default
// transform skips; this suite never compiles a chart.
jest.mock("vega", () => ({}), { virtual: true });
jest.mock("vega-lite", () => ({}), { virtual: true });

// The draw autkGrammarBehavior runs, settled when each test says.
let mockDraw: (spec: string) => Promise<void> = async () => {};
jest.mock("../../../adapters/node/autkGrammarBehavior", () => ({
  useAutkGrammarBehavior: () => ({ applyGrammar: (spec: string) => mockDraw(spec), outputIdOverride: "autk-map" }),
}));
const mockClear = jest.fn();
jest.mock("../../../providers/FlowProvider", () => ({
  useFlowContext: () => ({ clearSelectionTagsOf: mockClear }),
}));

import { act, renderHook } from "@testing-library/react";
import { getBehavior } from "../../../registry/behaviorRegistry";
import "../../../registry/builtinBehaviors";

const SPEC = JSON.stringify({ map: { layerRefs: [{ dataRef: "input_0", isPick: true }] } });

/** The Autark node *nodeId* as the canvas renders it. */
function autarkNode(nodeId = "map") {
  const useBehavior = getBehavior("autk-grammar")!;
  const data: any = { nodeId, interactionsCallback: jest.fn(), outputCallback: jest.fn() };
  const nodeState: any = { code: SPEC, setOutput: jest.fn() };
  return renderHook(() => useBehavior(data, nodeState));
}

beforeEach(() => {
  mockClear.mockClear();
  mockDraw = async () => {};
});

describe("an Autark node drawn again", () => {
  test("empties the selection tags on it", async () => {
    const node = autarkNode();

    await act(async () => {
      await node.result.current.applyGrammar!(SPEC);
    });

    expect(mockClear).toHaveBeenCalledTimes(1);
    expect(mockClear).toHaveBeenCalledWith("map");
    // Everything else the node is stays as autkGrammarBehavior makes it.
    expect(node.result.current.outputIdOverride).toBe("autk-map");
  });

  test("empties them once its draw has ended, not before", async () => {
    let end: () => void = () => {};
    mockDraw = () => new Promise<void>((resolve) => {
      end = resolve;
    });
    const node = autarkNode();

    let drawing: Promise<void> = Promise.resolve();
    act(() => {
      drawing = node.result.current.applyGrammar!(SPEC);
    });
    await act(async () => {});
    expect(mockClear).not.toHaveBeenCalled();

    await act(async () => {
      end();
      await drawing;
    });
    expect(mockClear).toHaveBeenCalledWith("map");
  });

  test("empties nothing when its draw ends after it left the page", async () => {
    // Drawn once on the page first: its tags are emptied.
    const first = autarkNode();
    await act(async () => {
      await first.result.current.applyGrammar!(SPEC);
    });
    expect(mockClear).toHaveBeenCalledTimes(1);

    let end: () => void = () => {};
    mockDraw = () => new Promise<void>((resolve) => {
      end = resolve;
    });
    const node = autarkNode();
    let drawing: Promise<void> = Promise.resolve();
    act(() => {
      drawing = node.result.current.applyGrammar!(SPEC);
    });
    node.unmount();
    await act(async () => {
      end();
      await drawing;
    });

    expect(mockClear).toHaveBeenCalledTimes(1);
  });
});
