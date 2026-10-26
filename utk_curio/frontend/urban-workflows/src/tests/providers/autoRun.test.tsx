/**
 * Auto-run (#845): with "Run stale nodes automatically" on, a widget value
 * change runs the nodes it touched and every node below them, once the
 * changes settle, through the run Run All starts. A change that
 * arrives while a run goes waits for it and then runs once.
 */
import { act, renderHook } from "@testing-library/react";
import { AUTO_RUN_SETTLE_MS, autoRunTargets, useAutoRun } from "../../providers/flow/useAutoRun";

const node = (id: string) => ({ id, position: { x: 0, y: 0 }, data: { nodeId: id } });
const NODES = ["w", "below", "further", "apart"].map(node);
const EDGES = [
  { id: "e1", source: "w", target: "below", sourceHandle: "out", targetHandle: "in_0" },
  { id: "e2", source: "below", target: "further", sourceHandle: "out", targetHandle: "in_0" },
  // A two-way interaction link is not a data edge: it orders no run.
  { id: "e3", source: "further", target: "apart", sourceHandle: "in/out", targetHandle: "in/out" },
];

describe("the nodes a change runs", () => {
  test("the node it touched and every node below it, in canvas order (#845)", () => {
    expect(autoRunTargets(["w"], NODES as any, EDGES as any)).toEqual(["w", "below", "further"]);
    expect(autoRunTargets(["below", "apart"], NODES as any, EDGES as any)).toEqual(["below", "further", "apart"]);
  });

  test("a node no longer on the canvas is left out (#845)", () => {
    expect(autoRunTargets(["gone", "below"], NODES as any, EDGES as any)).toEqual(["below", "further"]);
    expect(autoRunTargets(["gone"], NODES as any, EDGES as any)).toEqual([]);
  });
});

type Props = { enabled: boolean; runActive: boolean };

function harness(initial: Partial<Props> = {}) {
  let nodes: any[] = NODES;
  const reactFlow: any = { getNodes: () => nodes, getEdges: () => EDGES };
  const start = jest.fn();
  const hook = renderHook((props: Props) => useAutoRun({ ...props, reactFlow, start }), {
    initialProps: { enabled: true, runActive: false, ...initial },
  });
  const change = (ids: string[]) => act(() => hook.result.current.requestAutoRun(ids));
  const wait = (ms: number) => act(() => { jest.advanceTimersByTime(ms); });
  const deleteNode = (id: string) => { nodes = nodes.filter((n) => n.id !== id); };
  return { hook, start, change, wait, deleteNode };
}

beforeEach(() => jest.useFakeTimers());
afterEach(() => jest.useRealTimers());

describe("auto-run", () => {
  test("waits about half a second for the changes to settle (#845)", () => {
    expect(AUTO_RUN_SETTLE_MS).toBe(500);
  });

  test("twenty slider steps give one run, half a second after the last (#845)", () => {
    const { start, change, wait } = harness();
    for (let step = 0; step < 20; step++) {
      change(["w"]);
      wait(50);
    }
    wait(AUTO_RUN_SETTLE_MS - 51);
    expect(start).not.toHaveBeenCalled();
    wait(1);
    expect(start).toHaveBeenCalledTimes(1);
    expect(start).toHaveBeenCalledWith(["w", "below", "further"]);
    wait(5000);
    expect(start).toHaveBeenCalledTimes(1);
  });

  test("runs nothing while the toggle is off (#845)", () => {
    const { start, change, wait } = harness({ enabled: false });
    change(["w"]);
    wait(5000);
    expect(start).not.toHaveBeenCalled();
  });

  test("turning the toggle off drops a change that has not run yet (#845)", () => {
    const { hook, start, change, wait } = harness();
    change(["w"]);
    hook.rerender({ enabled: false, runActive: false });
    wait(5000);
    expect(start).not.toHaveBeenCalled();
  });

  test("a change during a run waits for it, then runs once with every change since (#845)", () => {
    const { hook, start, change, wait } = harness({ runActive: true });
    change(["w"]);
    wait(AUTO_RUN_SETTLE_MS + 100);
    change(["apart"]);
    wait(AUTO_RUN_SETTLE_MS + 100);
    expect(start).not.toHaveBeenCalled();

    hook.rerender({ enabled: true, runActive: false });
    expect(start).toHaveBeenCalledTimes(1);
    expect(start).toHaveBeenCalledWith(["w", "below", "further", "apart"]);

    // That run going and ending starts nothing more.
    hook.rerender({ enabled: true, runActive: true });
    hook.rerender({ enabled: true, runActive: false });
    wait(5000);
    expect(start).toHaveBeenCalledTimes(1);
  });

  test("a run that ends while a change still settles leaves it to its own timer (#845)", () => {
    const { hook, start, change, wait } = harness({ runActive: true });
    change(["w"]);
    wait(100);
    hook.rerender({ enabled: true, runActive: false });
    expect(start).not.toHaveBeenCalled();
    wait(AUTO_RUN_SETTLE_MS);
    expect(start).toHaveBeenCalledTimes(1);
  });

  test("Stop drops the run that waited (#845)", () => {
    const { hook, start, change, wait } = harness({ runActive: true });
    change(["w"]);
    wait(AUTO_RUN_SETTLE_MS + 100);
    act(() => hook.result.current.dropWaiting());
    hook.rerender({ enabled: true, runActive: false });
    wait(5000);
    expect(start).not.toHaveBeenCalled();
  });

  test("a node deleted before the run is left out (#845)", () => {
    const { start, change, wait, deleteNode } = harness();
    change(["w", "below"]);
    deleteNode("w");
    wait(AUTO_RUN_SETTLE_MS);
    expect(start).toHaveBeenCalledWith(["below", "further"]);
  });

  test("a change whose nodes were all deleted runs nothing (#845)", () => {
    const { start, change, wait, deleteNode } = harness();
    change(["apart"]);
    deleteNode("apart");
    wait(AUTO_RUN_SETTLE_MS);
    expect(start).not.toHaveBeenCalled();
  });
});
