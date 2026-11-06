/**
 * A node's `data.code` is the code its editor holds: useNodeState writes it
 * there once the editor's code changes. A run on the server starts from it
 * (useServerRun's `startRun`): each node's code then is the code its history
 * entry names, and its run key the key its result is stamped with.
 *
 * The canvas hands React Flow its nodes as props, and React Flow takes them
 * into its store in an effect, so a node draws the data it had for a moment
 * after the canvas replaced it. A run's result that lands in the same render
 * as a keystroke (`useStepOutcomes`' `showOnNode` spreads the node's data)
 * copies the data as it was before the keystroke's write, while the write
 * lands on the data the node still draws. The copy then reached the node
 * without it, and the next run named the code from before the keystroke:
 * `test_node_provenance_drawer_e2e.py`'s typing test listed the third run,
 * filed under the second run's code, before the typing that came ahead of it
 * (main's run 42141023968).
 */
import React from "react";
import { act, render, renderHook } from "@testing-library/react";
import {
  ReactFlow,
  ReactFlowProvider,
  useNodesState,
  useReactFlow,
  type Node,
  type NodeProps,
} from "reactflow";

// jsdom polyfills React Flow needs (as agentProvenanceEntries.integration).
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
(global as any).ResizeObserver = ResizeObserverStub;
if (!(global as any).DOMMatrixReadOnly) {
  (global as any).DOMMatrixReadOnly = class { m22 = 1; constructor() {} };
}

jest.mock("../../providers/StarterProvider", () => ({
  useStarterContext: () => ({ editUserStarter: jest.fn() }),
}));
jest.mock("../../providers/UserProvider", () => ({
  useUserContext: () => ({ user: null }),
}));
jest.mock("../../providers/FlowProvider", () => ({
  useFlowContext: () => ({ projectId: "p1", nodes: [] }),
}));
jest.mock("../../services/nodeRuntimeReport", () => ({
  reportFromNodeOutput: () => null,
  reportNodeRuntime: jest.fn(),
}));

import { useNodeState } from "../../hook/useNodeState";

const NODE = "runs-node";
const NODE_TYPE = "curio.builtin/computation-analysis" as any;
const SECOND = "return 2\n";
const THIRD = "return 3\n";
const RESULT = { code: "success", content: "Saved to file: art" };

/** What a run's result does to its node's data (`showOnNode`). */
const withResult = (data: any) => ({ ...data, output: RESULT });

/** The node's code as its editor's change hands it on (`floatCode`). */
let typeInNode: (code: string) => void = () => undefined;
let canvas: { setNodes: React.Dispatch<React.SetStateAction<Node<any>[]>>; getNodes: () => Node<any>[] };

const CodeNode = ({ data }: NodeProps) => {
  const state = useNodeState(data, NODE_TYPE);
  typeInNode = state.setCode;
  return null;
};
const nodeTypes = { code: CodeNode };

const Canvas = () => {
  const [nodes, setNodes, onNodesChange] = useNodesState<any>([
    { id: NODE, type: "code", position: { x: 0, y: 0 }, data: { nodeId: NODE, code: SECOND, defaultCode: SECOND } },
  ]);
  const flow = useReactFlow();
  canvas = { setNodes, getNodes: flow.getNodes };
  return (
    <div style={{ width: 800, height: 600 }}>
      <ReactFlow nodes={nodes} onNodesChange={onNodesChange} nodeTypes={nodeTypes} />
    </div>
  );
};

/** The node's data as React Flow holds it, which a run's start reads. */
const held = () => {
  const node = canvas.getNodes().find((n) => n.id === NODE);
  if (!node) throw new Error("React Flow holds no node");
  return node.data;
};

const nodeOn = (data: any) =>
  renderHook(({ data: current }: { data: any }) => useNodeState(current, NODE_TYPE), { initialProps: { data } });

test("a keystroke in the render a run's result lands in stays the node's code on React Flow", () => {
  render(
    <ReactFlowProvider>
      <Canvas />
    </ReactFlowProvider>,
  );
  expect(held().code).toBe(SECOND);

  act(() => {
    typeInNode(THIRD);
    canvas.setNodes((nds) => nds.map((node) => (node.id === NODE ? { ...node, data: withResult(node.data) } : node)));
  });

  // The result's copy is the node's data now.
  expect(held().output).toEqual(RESULT);
  expect(held().code).toBe(THIRD);
});

test("a copy of a node's data made before a keystroke's write and handed to it after takes the keystroke's code", () => {
  const before: any = { nodeId: NODE, code: SECOND, defaultCode: SECOND };
  const node = nodeOn(before);
  const copy = withResult(before);

  act(() => node.result.current.setCode(THIRD));
  expect(before.code).toBe(THIRD);
  node.rerender({ data: copy });

  expect(copy.code).toBe(THIRD);
});

test("new data that brings the editor other code keeps it until the editor takes it", () => {
  const before: any = { nodeId: NODE, code: SECOND, defaultCode: SECOND };
  const node = nodeOn(before);
  act(() => node.result.current.setCode(THIRD));

  // A writer that sets a node's code (a rewrite, an agent's apply) sets the
  // code its editor takes as well.
  const rewritten = { ...before, code: "return 4\n", defaultCode: "return 4\n" };
  node.rerender({ data: rewritten });

  expect(rewritten.code).toBe("return 4\n");
});
