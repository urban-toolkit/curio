/**
 * An agent's applied change to a node's settings (`node.settings.write`)
 * reaches the node the way a pick in the node does: each setting goes to the
 * setter the node registered for it while it is on the canvas
 * (`utils/nodeSettingsWriters`). A setting no setter takes goes into the
 * node's data through `updateDataNode`, as a load of the node's metadata puts
 * it there, and a widget's new value still leaves what reads it out of date
 * and asks for an automatic run.
 */
import {
  nodeSettingWriter,
  registerNodeSettingWriter,
  writeNodeSettings,
} from "../../utils/nodeSettingsWriters";

const COMBINE = {
  name: "combine", type: "choice", label: "Combine", default: "mean",
  options: { choices: ["mean", "sum", "max"] },
};
const THRESHOLD = { name: "threshold", type: "slider", default: 2, options: { min: 0, max: 10 } };
const SEASON = { name: "season", type: "choice", default: "summer", options: { choices: ["summer", "winter"] } };

const node = (id: string, nodeType: string, data: Record<string, unknown> = {}) => ({
  id,
  type: "__curioUniversalNode",
  data: { nodeId: id, nodeType, ...data },
});

function canvas(nodes: ReturnType<typeof node>[]) {
  return {
    nodes: () => nodes,
    updateDataNode: jest.fn(),
    markNodeStale: jest.fn(),
    markDirty: jest.fn(),
    requestAutoRun: jest.fn(),
  };
}

const offs: Array<() => void> = [];
afterEach(() => {
  while (offs.length) offs.pop()!();
});

test("each setting goes to the setter its node registered for it, and nothing into the node's data", () => {
  const pool = jest.fn();
  const values = jest.fn();
  offs.push(registerNodeSettingWriter("n1", "dataPool", pool), registerNodeSettingWriter("n1", "widgets", values));
  const flow = canvas([node("n1", "curio.builtin/data-pool@1")]);

  writeNodeSettings(flow, "n1", { dataPool: { betweenCharts: "MERGE_AND" }, widgets: { combine: "max" } });

  expect(pool).toHaveBeenCalledWith({ betweenCharts: "MERGE_AND" });
  expect(values).toHaveBeenCalledWith({ combine: "max" });
  expect(flow.updateDataNode).not.toHaveBeenCalled();
  // The setter does what a pick in the node does; the bridge adds nothing.
  expect(flow.markNodeStale).not.toHaveBeenCalled();
  expect(flow.requestAutoRun).not.toHaveBeenCalled();
});

test("a setting no setter takes goes into the node's data through updateDataNode, as a load of its metadata puts it there", () => {
  const flow = canvas([node("n1", "curio.builtin/spatial-join@1", {
    dataPool: { insideChart: "MERGE_OR" },
    simpleVis: { imageColumn: "image_url" },
    spatialJoin: { output: "counts" },
    widgets: [COMBINE],
  })]);

  writeNodeSettings(flow, "n1", {
    dataPool: { betweenCharts: "MERGE_AND" },
    simpleVis: {},
    spatialJoin: { predicate: "within" },
  });

  expect(flow.updateDataNode).toHaveBeenCalledTimes(1);
  const [nodeId, data] = flow.updateDataNode.mock.calls[0];
  expect(nodeId).toBe("n1");
  // Each key the change gives, beside the ones it leaves as they were.
  expect(data.dataPool).toEqual({ insideChart: "MERGE_OR", betweenCharts: "MERGE_AND" });
  expect(data.spatialJoin).toEqual({ output: "counts", predicate: "within" });
  // No column is every image column.
  expect(data.simpleVis?.imageColumn).toBeUndefined();
  // What the change does not name stays as it is.
  expect(data.widgets).toEqual([COMBINE]);
  expect(data.nodeType).toBe("curio.builtin/spatial-join@1");
  expect(flow.markNodeStale).not.toHaveBeenCalled();
});

test("a widget's new value on a node with no setter leaves it out of date, the dataflow Unsaved, and asks for an automatic run", () => {
  const flow = canvas([node("chart", "curio.builtin/computation-analysis@1", { widgets: [COMBINE, THRESHOLD] })]);

  writeNodeSettings(flow, "chart", { widgets: { combine: "max" } });

  const [, data] = flow.updateDataNode.mock.calls[0];
  const byName = Object.fromEntries(data.widgets.map((w: any) => [w.name, w]));
  expect(byName.combine.value).toBe("max");
  expect(byName.threshold.value).toBeUndefined();
  expect(flow.markNodeStale).toHaveBeenCalledWith("chart");
  expect(flow.markDirty).toHaveBeenCalled();
  expect(flow.requestAutoRun).toHaveBeenCalledWith(["chart"]);
});

test("a Parameter's new value with no setter leaves the nodes that use it out of date, and runs them", () => {
  const flow = canvas([
    node("p1", "curio.builtin/parameter@1", { widgets: [SEASON] }),
    node("a", "curio.builtin/computation-analysis@1", { code: "s = [!! @season !!]" }),
    node("b", "curio.builtin/computation-analysis@1", { code: "print(1)" }),
  ]);

  writeNodeSettings(flow, "p1", { widgets: { season: "winter" } });

  const [, data] = flow.updateDataNode.mock.calls[0];
  expect(data.widgets[0].value).toBe("winter");
  expect(flow.markNodeStale.mock.calls.map((call) => call[0])).toEqual(["a"]);
  expect(flow.requestAutoRun).toHaveBeenCalledWith(["a"]);
});

test("a setter is taken off by what its registration returned, and a newer one for the node stays", () => {
  const first = jest.fn();
  const second = jest.fn();
  const offFirst = registerNodeSettingWriter("n1", "simpleVis", first);
  const offSecond = registerNodeSettingWriter("n1", "simpleVis", second);
  offFirst();
  expect(nodeSettingWriter("n1", "simpleVis")).toBe(second);
  offSecond();
  expect(nodeSettingWriter("n1", "simpleVis")).toBeUndefined();
});

test("a node that is not on the canvas takes nothing", () => {
  const flow = canvas([]);
  writeNodeSettings(flow, "gone", { dataPool: { betweenCharts: "MERGE_AND" } });
  expect(flow.updateDataNode).not.toHaveBeenCalled();
});
