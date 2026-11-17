/**
 * A Spatial Join runs in the browser once each of its two ports holds its
 * input: a hosted guest's run, a watcher's, or one on a canvas nobody signed
 * in to. An account's runs go to the server, which never meets this check.
 *
 * Dev 0.17.332, a hosted guest's Run All of example 32: both nodes feeding the
 * join answered with their outputs, and the join held them by port
 * (`data.portInputs`, `in` and `in_1`) and as the one value its code reads
 * (`data.input`, both in port order). Its editor still refused the run before
 * it reached the sandbox:
 *
 *   input_0 (from On the ground) has no value yet. Run the node that feeds it.
 *   input_1 (from Zones on the ground) has no value yet. Run the node that feeds it.
 *
 * A guest of example 25 saw its nine joins refused the same way. The check of
 * the inputs a run waits for (hook/useInputScope) read a circle's value from
 * `data.inputSlots`, which only a growing node holds, or from `data.input` on
 * circle 0, and a node with several ports holds neither by circle.
 *
 * The join here is example 32's "Objects in each zone" as the guest's canvas
 * held it: "On the ground" on `in`, "Zones on the ground" on `in_1`, and the
 * artifacts each handed it, put on the node by the canvas's own writers
 * (`withPortValues`, `nodeInputFromPorts`, as providers/flow/useGraphEdits
 * calls them). As its template says, the join opens on its controls, so a run
 * resolves its chips in NodeEditor itself. The real CodeEditor sends the run;
 * Monaco is stubbed.
 */
import React from "react";
import { act, render } from "@testing-library/react";
import type { WidgetDef } from "../../utils/widgets/widgetModel";
import { nodeInputFromPorts, withPortValues } from "../../utils/inputSlots";

const JOIN = "curio.builtin/spatial-join";
const JOIN_ID = "idot-objects-in-zones";
const ON_THE_GROUND_ID = "idot-on-the-ground";
const ZONES_ID = "idot-zones-on-the-ground";

const mockFlow = {
  nodes: [
    { id: ON_THE_GROUND_ID, data: { nodeType: "curio.builtin/python-computation", title: "On the ground" } },
    { id: ZONES_ID, data: { nodeType: "curio.builtin/python-computation", title: "Zones on the ground" } },
  ],
  // Example 32's two edges into the join, as it ships.
  edges: [
    {
      id: "reactflow__edge-idot-on-the-groundout-idot-objects-in-zonesin",
      source: ON_THE_GROUND_ID, sourceHandle: "out", target: JOIN_ID, targetHandle: "in",
    },
    {
      id: "reactflow__edge-idot-zones-on-the-groundout-idot-objects-in-zonesin_1",
      source: ZONES_ID, sourceHandle: "out", target: JOIN_ID, targetHandle: "in_1",
    },
  ],
  // Both answered 200 with their outputs.
  nodeExecStatus: { [ON_THE_GROUND_ID]: "executed", [ZONES_ID]: "executed" },
};

jest.mock("../../providers/FlowProvider", () => ({
  useFlowContext: () => ({
    dashboardOn: false,
    markDirty: jest.fn(),
    markNodeStale: jest.fn(),
    requestAutoRun: jest.fn(),
    // What a run on the node reads (CodeEditor).
    workflowNameRef: { current: "SAGE-IDOT rail crossings" },
    isDashboardSource: () => false,
    markNodeExecuted: jest.fn(),
    markNodeErrored: jest.fn(),
    signalNodeExecDone: jest.fn(),
    ...mockFlow,
  }),
}));
// The join's template, as the shipped manifest declares it: two input ports of
// one edge each, and it opens on its controls.
jest.mock("../../registry/nodeRegistry", () => ({
  ...jest.requireActual("../../registry/nodeRegistry"),
  tryGetNodeDescriptor: (nodeType: string) =>
    nodeType === "curio.builtin/spatial-join"
      ? {
          id: nodeType,
          label: "Spatial Join",
          hasCode: true,
          hasWidgets: true,
          hasGrammar: false,
          inputPorts: [
            { types: ["GEODATAFRAME"], cardinality: "1" },
            { types: ["GEODATAFRAME"], cardinality: "1" },
          ],
          outputPorts: [{ types: ["GEODATAFRAME"], cardinality: "1" }],
          opensOnControls: true,
        }
      : undefined,
}));
jest.mock("@monaco-editor/react", () => ({
  __esModule: true,
  default: ({ value }: any) => <textarea data-testid="monaco" value={value ?? ""} readOnly />,
}));
jest.mock("../../providers/CollaborationProvider", () => ({
  useCollab: () => ({
    connected: false,
    users: [],
    onRemote: jest.fn(() => jest.fn()),
  }),
}));

import NodeEditor from "../../components/editing/NodeEditor";

/** What each node feeding the join handed it, from dev's evidence. */
const ON_THE_GROUND = { path: "1794945771869_ab89a326", dataType: "geodataframe" };
const ZONES = { path: "1794945771387_fd09adaa", dataType: "geodataframe" };

/** The join's two widgets, as its template declares them, with example 32's values. */
const OPERATION: WidgetDef = {
  name: "operation", type: "choice", label: "Operation", default: "intersects", value: "within",
  options: {
    choices: ["intersects", "within", "contains", "touches", "overlaps", "crosses", "nearest"],
    display: "dropdown",
  },
};
const OUTPUT: WidgetDef = {
  name: "output", type: "choice", label: "Output", default: "pairs", value: "pairs",
  options: { choices: ["pairs", "counts"], display: "dropdown" },
};

/** The join's code, its template's source. */
const CODE =
  "from spatial_join import spatial_join\n\n"
  + "return spatial_join(input_0, input_1, operation=[!! operation !!], output=[!! output !!])\n";
/** The same, as a run sends it to the sandbox. */
const RESOLVED =
  "from spatial_join import spatial_join\n\n"
  + 'return spatial_join(input_0, input_1, operation="within", output="pairs")\n';

/** The join's data once the inputs in *arrivals* reached it, in that order, as
 *  the canvas's writers leave it: each port's input by handle, and the one
 *  value its code reads, both inputs in port order once both arrived. A node
 *  with several ports holds no `inputSlots`. */
function joinData(arrivals: Array<[string, unknown]>, extra: Record<string, unknown> = {}) {
  let portInputs: Record<string, unknown> = {};
  for (const [handle, value] of arrivals) portInputs = withPortValues(portInputs, [handle], value);
  return {
    nodeId: JOIN_ID,
    nodeType: JOIN,
    title: "Objects in each zone",
    widgets: [OPERATION, OUTPUT],
    portInputs,
    input: nodeInputFromPorts(portInputs, [0, 1]),
    inputTypes: [],
    outputCallback: jest.fn(),
    ...extra,
  };
}

const baseProps = {
  output: { code: "", content: "" },
  nodeType: JOIN,
  readOnly: false,
  code: true,
  grammar: false,
  widgets: true,
  defaultValue: CODE,
};

/** The join played as UniversalNode plays it: shown running, then its code sent. */
function play(data: Record<string, unknown>) {
  const setSendCodeCallback = jest.fn();
  const setOutputCallback = jest.fn();
  const props = { ...baseProps, setSendCodeCallback, setOutputCallback };
  const { rerender } = render(<NodeEditor {...(props as any)} data={data} />);
  rerender(<NodeEditor {...(props as any)} data={data} output={{ code: "exec", content: "" }} />);
  const send = setSendCodeCallback.mock.calls[0][0];
  act(() => send(CODE));
  return { setOutputCallback };
}

const refusals = (setOutputCallback: jest.Mock) =>
  setOutputCallback.mock.calls.map(([outcome]) => outcome).filter((outcome) => outcome?.code === "error");

test("example 32's join, both ports holding their inputs, sends its run to the sandbox with both, each on its circle", () => {
  const interpretCode = jest.fn();
  // Zones on the ground answered first, as on dev.
  const data = joinData([["in_1", ZONES], ["in", ON_THE_GROUND]], { pythonInterpreter: { interpretCode } });
  expect(data).not.toHaveProperty("inputSlots");
  expect(data.input).toEqual({ dataType: "outputs", data: [ON_THE_GROUND, ZONES] });

  const { setOutputCallback } = play(data);

  expect(refusals(setOutputCallback)).toEqual([]);
  expect(interpretCode).toHaveBeenCalledTimes(1);
  const sent = interpretCode.mock.calls[0];
  expect(sent[1]).toBe(RESOLVED);
  // The one value its code reads: On the ground as input_0, the zones as input_1.
  expect(sent[2]).toEqual({ dataType: "outputs", data: [ON_THE_GROUND, ZONES] });
  expect(sent[6]).toBe(JOIN_ID);
  // The circles the run names, which the sandbox reads that value on.
  expect(sent[12]).toEqual([0, 1]);
});

test("example 32's join with only its zones arrived waits for input_0 and names it alone", () => {
  const interpretCode = jest.fn();
  const data = joinData([["in_1", ZONES]], { pythonInterpreter: { interpretCode } });

  const { setOutputCallback } = play(data);

  expect(refusals(setOutputCallback)).toEqual([
    { code: "error", content: "input_0 (from On the ground) has no value yet. Run the node that feeds it." },
  ]);
  expect(interpretCode).not.toHaveBeenCalled();
});
