/**
 * A view drawn again without the selection its tags hold empties them (#884):
 * `clearViewTags`, which the flow hands its views as `clearSelectionTagsOf`.
 * Every tag on the view is emptied, in every node that holds one, and those
 * nodes go stale, as after a selection cleared in the view. A selection read
 * before the redraw is not written over the emptied tags, and a tag added
 * afterwards starts from no selection.
 */
import React from "react";
import { act, render } from "@testing-library/react";
import { useSelectionTags } from "../../providers/flow/useSelectionTags";
import { VisInteractionType } from "../../constants";
import { objectRows } from "../../utils/selectionMatch";
import { provideViewRows, resetViewSelections, selectionStateOf } from "../../utils/references/viewSelections";
import type { SelectionTag } from "../../utils/references/selectionTags";

const ROWS = [
  { osm_id: 101, height: 10 },
  { osm_id: 102, height: 30 },
  { osm_id: 103, height: 50 },
];
const VIEW_ROWS = { rows: objectRows(ROWS), columns: ["osm_id", "height"] };

const brush = (low: number, high: number) => ({
  brush: { type: VisInteractionType.INTERVAL, data: { height: [low, high] }, priority: 1 },
});

type Api = { clearViewTags?: (viewId: string) => void } | undefined;
let api: Api;

function Harness(props: Parameters<typeof useSelectionTags>[0]) {
  api = useSelectionTags(props) as Api;
  return null;
}

function setup(nodes: any[]) {
  const store = { nodes };
  const setNodes = jest.fn((update: any) => {
    store.nodes = typeof update === "function" ? update(store.nodes) : update;
  });
  const stale = jest.fn();
  const dirty = jest.fn();
  const props = {
    reactFlow: { getNodes: () => store.nodes } as any,
    setNodes: setNodes as any,
    markNodeStaleRef: { current: stale },
    markDirtyRef: { current: dirty },
  };
  const tagsOf = (id: string): SelectionTag[] => store.nodes.find((n: any) => n.id === id).data.selections;
  return { props, setNodes, stale, dirty, tagsOf };
}

const node = (id: string, selections?: SelectionTag[]) => ({ id, data: { nodeId: id, ...(selections ? { selections } : {}) } });
const onChart = (extra: Partial<SelectionTag>): SelectionTag => ({ name: "picked", node: "chart", column: "osm_id", ...extra });

beforeEach(() => {
  api = undefined;
  provideViewRows("chart", () => VIEW_ROWS);
});
afterEach(() => resetViewSelections());

describe("a view drawn again without its tags' selection", () => {
  test("empties every tag on it, in every node, and marks those nodes stale", async () => {
    const { props, stale, dirty, tagsOf } = setup([
      node("chart"),
      node("counter", [onChart({ ids: [101] })]),
      node("other", [
        onChart({ name: "tall", column: "height", ids: [10] }),
        { name: "elsewhere", node: "map", column: "osm_id", ids: [5] },
      ]),
      node("reader"),
    ]);
    render(<Harness {...props} interactions={[]} />);

    act(() => api!.clearViewTags!("chart"));

    expect(tagsOf("counter")).toEqual([onChart({ ids: [] })]);
    expect(tagsOf("other")).toEqual([
      onChart({ name: "tall", column: "height", ids: [] }),
      { name: "elsewhere", node: "map", column: "osm_id", ids: [5] },
    ]);
    expect(stale.mock.calls.map(([id]) => id).sort()).toEqual(["counter", "other"]);
    expect(dirty).toHaveBeenCalledTimes(1);
  });

  test("empties a tag that held a count in place of ids", async () => {
    const { props, stale, tagsOf } = setup([node("chart"), node("counter", [onChart({ count: 20000 })])]);
    render(<Harness {...props} interactions={[]} />);

    act(() => api!.clearViewTags!("chart"));

    expect(tagsOf("counter")).toEqual([onChart({ ids: [] })]);
    expect(stale).toHaveBeenCalledWith("counter");
  });

  test("changes nothing when its tags hold nothing", async () => {
    const { props, setNodes, stale, dirty } = setup([node("chart"), node("counter", [onChart({ ids: [] })])]);
    render(<Harness {...props} interactions={[]} />);

    act(() => api!.clearViewTags!("chart"));

    expect(setNodes).not.toHaveBeenCalled();
    expect(stale).not.toHaveBeenCalled();
    expect(dirty).not.toHaveBeenCalled();
  });

  test("keeps them empty when a selection read before lands after", async () => {
    // The view's rows answer only when told, so the brush is still being read
    // when the view is drawn again.
    let answer: () => void = () => {};
    provideViewRows("chart", () => new Promise((resolve) => {
      answer = () => resolve(VIEW_ROWS);
    }));
    const { props, tagsOf } = setup([node("chart"), node("counter", [onChart({ ids: [101] })])]);
    const view = render(<Harness {...props} interactions={[]} />);
    await act(async () => {
      view.rerender(<Harness {...props} interactions={[{ nodeId: "chart", details: brush(20, 60), priority: 1 }]} />);
    });

    act(() => api!.clearViewTags!("chart"));
    await act(async () => {
      answer();
    });
    await act(async () => {});

    expect(tagsOf("counter")).toEqual([onChart({ ids: [] })]);
  });

  test("leaves no selection for a tag added afterwards to start from", async () => {
    const { props, tagsOf } = setup([node("chart"), node("counter", [onChart({ ids: [101] })])]);
    const view = render(<Harness {...props} interactions={[]} />);
    await act(async () => {
      view.rerender(<Harness {...props} interactions={[{ nodeId: "chart", details: brush(20, 60), priority: 1 }]} />);
    });
    await act(async () => {});
    expect(tagsOf("counter")).toEqual([onChart({ ids: [102, 103] })]);
    expect(await selectionStateOf("chart", "height")).toEqual({ ids: [30, 50] });

    act(() => api!.clearViewTags!("chart"));

    expect(await selectionStateOf("chart", "height")).toEqual({ ids: [] });
  });
});
