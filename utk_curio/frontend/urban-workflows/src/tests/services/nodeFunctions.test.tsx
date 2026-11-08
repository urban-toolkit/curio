/**
 * What a node's code can call, as the header above its code reads it
 * (`services/packages/nodeFunctions`): one read per dataflow and node type,
 * however many headers show it; a read that fails lists nothing and is not
 * asked again; and the lists are read again only when the installed packages
 * change, which each refresh of the package registry says.
 */
const mockNodeFunctions = jest.fn();
jest.mock("../../services/packages/packagesApi", () => ({
  packagesApi: { nodeFunctions: (...args: unknown[]) => mockNodeFunctions(...args) },
}));

import React from "react";
import { act, cleanup, render } from "@testing-library/react";
import { forgetNodeFunctions, useNodeFunctions } from "../../services/packages/nodeFunctions";
import type { NodeFunctionsPayload } from "../../services/packages/types";

const LIST: NodeFunctionsPayload = {
  engine: "python",
  curio: [{ name: "curio_load_model", call: "curio_load_model(model_id)", doc: "Loads a model.", insert: "curio_load_model(model_id)" }],
  modules: [],
};

/** A header's read: its state, and how many of Curio's functions it lists. */
function Header({ nodeType, dataflowId }: { nodeType: string | null; dataflowId?: string }) {
  const state = useNodeFunctions(nodeType, dataflowId);
  return <div data-header={nodeType ?? "none"} data-state={state.state} data-curio={state.state === "ready" ? state.functions.curio.length : -1} />;
}

const stateOf = (container: HTMLElement, index = 0) =>
  container.querySelectorAll("[data-header]")[index].getAttribute("data-state");

/** The reads asked for so far, by node type and dataflow. */
const asked = () => mockNodeFunctions.mock.calls.map(([nodeType, dataflowId]) => [nodeType, dataflowId ?? null]);

/** Lets the reads that answered settle. */
async function settle() {
  await act(async () => {
    for (let i = 0; i < 10; i += 1) await Promise.resolve();
  });
}

beforeEach(() => {
  mockNodeFunctions.mockReset();
});

afterEach(cleanup);

test("a node type's list is read once per dataflow, however many headers show it", async () => {
  mockNodeFunctions.mockResolvedValue(LIST);
  const view = render(
    <>
      <Header nodeType="ai.test/once" dataflowId="flow-1" />
      <Header nodeType="ai.test/once" dataflowId="flow-1" />
      <Header nodeType="ai.test/once" dataflowId="flow-2" />
    </>,
  );
  expect(stateOf(view.container)).toBe("loading");
  await settle();
  expect(asked()).toEqual([
    ["ai.test/once", "flow-1"],
    ["ai.test/once", "flow-2"],
  ]);
  for (const index of [0, 1, 2]) expect(stateOf(view.container, index)).toBe("ready");
  expect(view.container.querySelector("[data-header]")!.getAttribute("data-curio")).toBe("1");
});

test("a read that fails lists nothing, and is not asked again", async () => {
  mockNodeFunctions.mockRejectedValue(new Error("HTTP 500"));
  const view = render(<Header nodeType="ai.test/fails" />);
  await settle();
  expect(stateOf(view.container)).toBe("failed");
  view.rerender(<Header nodeType="ai.test/fails" />);
  await settle();
  expect(asked()).toEqual([["ai.test/fails", null]]);
  // A call that throws at once fails the same way.
  mockNodeFunctions.mockImplementation(() => {
    throw new TypeError("packagesApi.nodeFunctions is not a function");
  });
  const thrown = render(<Header nodeType="ai.test/throws" />);
  await settle();
  expect(stateOf(thrown.container)).toBe("failed");
});

test("a node of no type reads nothing and lists nothing", async () => {
  const view = render(<Header nodeType={null} />);
  await settle();
  expect(stateOf(view.container)).toBe("ready");
  expect(view.container.querySelector("[data-header]")!.getAttribute("data-curio")).toBe("0");
  expect(mockNodeFunctions).not.toHaveBeenCalled();
});

test("the lists are read again only when the installed packages change", async () => {
  mockNodeFunctions.mockResolvedValue(LIST);
  // What the packages are now: a refresh that names them.
  forgetNodeFunctions("ai.test/changes 1.0.0 1");
  const view = render(<Header nodeType="ai.test/changes" />);
  await settle();
  expect(asked()).toHaveLength(1);

  // A refresh with the same packages, as the canvas makes several at load.
  forgetNodeFunctions("ai.test/changes 1.0.0 1");
  await settle();
  expect(asked()).toHaveLength(1);
  expect(stateOf(view.container)).toBe("ready");

  // A package changed: the header reads its list again.
  act(() => forgetNodeFunctions("ai.test/changes 1.0.1 2"));
  await settle();
  expect(asked()).toHaveLength(2);
  expect(stateOf(view.container)).toBe("ready");
});

test("a read on its way when the packages change is not kept", async () => {
  let answer: (list: NodeFunctionsPayload) => void = () => undefined;
  mockNodeFunctions.mockImplementationOnce(() => new Promise<NodeFunctionsPayload>((resolve) => (answer = resolve)));
  mockNodeFunctions.mockImplementationOnce(() => new Promise<NodeFunctionsPayload>(() => undefined));
  forgetNodeFunctions("ai.test/late 1");
  const view = render(<Header nodeType="ai.test/late" />);
  await settle();
  act(() => forgetNodeFunctions("ai.test/late 2"));
  await settle();
  // The old answer comes back after the change: the new read is still on its way.
  await act(async () => answer(LIST));
  await settle();
  expect(asked()).toHaveLength(2);
  expect(stateOf(view.container)).toBe("loading");
});
