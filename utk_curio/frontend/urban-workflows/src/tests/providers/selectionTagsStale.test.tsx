/**
 * A new selection in a view reaches the selection tags that read it (#662):
 * their ids are rewritten, the nodes holding them go stale, and a run below
 * them runs them again, though their code did not change. A chart declaring its
 * selects as it compiles, as it does after a reload, changes nothing.
 */
import React from "react";
import { act, render, waitFor } from "@testing-library/react";
import { useSelectionTags } from "../../providers/flow/useSelectionTags";
import { nodesToRunUpTo } from "../../providers/flow/runLevels";
import { VisInteractionType } from "../../constants";
import { objectRows } from "../../utils/selectionMatch";
import { runKeyWithShared } from "../../utils/references/sharedParameters";
import { provideViewRows, resetViewSelections } from "../../utils/references/viewSelections";
import type { SelectionTag } from "../../utils/references/selectionTags";

const ROWS = [
  { osm_id: 101, height: 10 },
  { osm_id: 102, height: 30 },
  { osm_id: 103, height: 50 },
  { osm_id: 104, height: 20 },
];
const CODE = "return arg[arg.osm_id.isin([!! selection picked !!])]";
const TAG: SelectionTag = { name: "picked", node: "chart", column: "osm_id", ids: [101] };

const brush = (low: number, high: number) => ({
  brush: { type: VisInteractionType.INTERVAL, data: { height: [low, high] }, priority: 1 },
});

function Harness(props: Parameters<typeof useSelectionTags>[0]) {
  useSelectionTags(props);
  return null;
}

function setup() {
  let nodes: any[] = [
    { id: "chart", type: "curio.builtin/vis-vega", data: { nodeId: "chart" } },
    {
      id: "counter",
      data: {
        nodeId: "counter",
        code: CODE,
        selections: [TAG],
        output: { code: "success" },
        executedCode: runKeyWithShared(CODE, undefined, [], [TAG]),
      },
    },
    { id: "reader", data: { nodeId: "reader", code: "return arg", output: { code: "success" }, executedCode: "return arg" } },
  ];
  const edges: any[] = [{ id: "e1", source: "counter", target: "reader", sourceHandle: "out", targetHandle: "in" }];
  const reactFlow: any = { getNodes: () => nodes };
  const setNodes = jest.fn((update: any) => {
    nodes = typeof update === "function" ? update(nodes) : update;
  });
  const stale = jest.fn();
  const dirty = jest.fn();
  const refs = {
    reactFlow,
    setNodes: setNodes as any,
    markNodeStaleRef: { current: stale },
    markDirtyRef: { current: dirty },
  };
  const counter = () => nodes.find((n) => n.id === "counter");
  const runsBelow = () => nodesToRunUpTo("reader", nodes, edges, new Map()).willRun;
  return { refs, setNodes, stale, dirty, counter, runsBelow };
}

beforeEach(() => {
  provideViewRows("chart", () => ({ rows: objectRows(ROWS), columns: ["osm_id", "height"] }));
});
afterEach(() => resetViewSelections());

describe("a view's new selection", () => {
  test("rewrites the ids of the tags on it and marks their nodes stale", async () => {
    const { refs, stale, dirty, counter, runsBelow } = setup();
    // Before: the counter's output is current, so a run below reuses it.
    expect([...runsBelow()]).toEqual(["reader"]);

    const view = render(<Harness {...refs} interactions={[]} />);
    await act(async () => {
      view.rerender(<Harness {...refs} interactions={[{ nodeId: "chart", details: brush(15, 60), priority: 1 }]} />);
    });
    await waitFor(() => expect(counter().data.selections[0].ids).toEqual([102, 103, 104]));
    expect(stale).toHaveBeenCalledWith("counter");
    expect(dirty).toHaveBeenCalled();
    // After: its code is the same, but its run key is not, so it runs again.
    expect([...runsBelow()].sort()).toEqual(["counter", "reader"]);
  });

  test("a chart declaring its selects, as after a reload, keeps the saved ids", async () => {
    const { refs, setNodes, stale, counter } = setup();
    const view = render(<Harness {...refs} interactions={[]} />);
    const declared = { brush: { type: VisInteractionType.UNDETERMINED, data: [], source: "chart" } };
    await act(async () => {
      view.rerender(<Harness {...refs} interactions={[{ nodeId: "chart", details: declared, priority: 1 }]} />);
    });
    await act(async () => {});
    expect(setNodes).not.toHaveBeenCalled();
    expect(stale).not.toHaveBeenCalled();
    expect(counter().data.selections).toEqual([TAG]);
  });

  test("a chart's empty selects at its first draw, at priority 1, keep the saved ids", async () => {
    // A Vega chart's signal listeners hear its first pulse, and report each
    // select empty, as the newest.
    const { refs, setNodes, counter } = setup();
    const view = render(<Harness {...refs} interactions={[]} />);
    const firstDraw = { brush: { type: VisInteractionType.UNDETERMINED, data: [], priority: 1 } };
    await act(async () => {
      view.rerender(<Harness {...refs} interactions={[{ nodeId: "chart", details: firstDraw, priority: 1 }]} />);
    });
    await act(async () => {});
    expect(setNodes).not.toHaveBeenCalled();
    expect(counter().data.selections).toEqual([TAG]);
  });

  test("clearing a brush the chart held empties the ids", async () => {
    const { refs, counter } = setup();
    const view = render(<Harness {...refs} interactions={[]} />);
    await act(async () => {
      view.rerender(<Harness {...refs} interactions={[{ nodeId: "chart", details: brush(15, 60), priority: 1 }]} />);
    });
    await waitFor(() => expect(counter().data.selections[0].ids).toEqual([102, 103, 104]));
    const cleared = { brush: { type: VisInteractionType.INTERVAL, data: {}, priority: 1 } };
    await act(async () => {
      view.rerender(<Harness {...refs} interactions={[{ nodeId: "chart", details: cleared, priority: 1 }]} />);
    });
    await waitFor(() => expect(counter().data.selections[0].ids).toEqual([]));
  });

  test("of a brush's many moves, the last one's ids are kept", async () => {
    const { refs, counter } = setup();
    const view = render(<Harness {...refs} interactions={[]} />);
    await act(async () => {
      view.rerender(<Harness {...refs} interactions={[{ nodeId: "chart", details: brush(0, 100), priority: 1 }]} />);
      view.rerender(<Harness {...refs} interactions={[{ nodeId: "chart", details: brush(45, 55), priority: 1 }]} />);
    });
    await waitFor(() => expect(counter().data.selections[0].ids).toEqual([103]));
    await act(async () => {});
    expect(counter().data.selections[0].ids).toEqual([103]);
  });

  test("a selection in another view leaves the tags alone", async () => {
    const { refs, setNodes } = setup();
    provideViewRows("other", () => ({ rows: objectRows(ROWS), columns: ["osm_id", "height"] }));
    const view = render(<Harness {...refs} interactions={[]} />);
    await act(async () => {
      view.rerender(<Harness {...refs} interactions={[{ nodeId: "other", details: brush(0, 100), priority: 1 }]} />);
    });
    await act(async () => {});
    expect(setNodes).not.toHaveBeenCalled();
  });
});
