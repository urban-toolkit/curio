/**
 * A collapsed scenario's box (#662): one box in its color, with its name, its
 * fixed context and its outcomes with their latest outputs, a port on each row
 * for the stand-in edges, and a double-click that expands it. An expanded
 * scenario has a frame whose header collapses it.
 */
import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { ReactFlowProvider, useStoreApi } from "reactflow";

jest.mock("../../providers/FlowProvider", () => ({ useFlowContext: () => ({}) }));
jest.mock("../../components/scenarios/useScenarioActions", () => ({ useScenarioActions: () => ({}) }));

import { ScenarioLayers, boxLayout } from "../../components/scenarios/ScenarioLayers";
import type { ScenarioBox, ScenarioCanvasView } from "../../utils/scenarios/scenarioCanvasView";

const scenario = { id: "tall", name: "Twice as tall", color: "#e86a3c", nodes: ["a", "map"], collapsed: true };
const box: ScenarioBox = {
  scenario,
  x: 10,
  y: 20,
  parts: { levers: ["a", "map"], context: ["pool", "season"], outcomes: ["map"] },
};

const view = (over: Partial<ScenarioCanvasView<any, any>> = {}): ScenarioCanvasView<any, any> => ({
  nodes: [],
  edges: [],
  boxes: [box],
  frames: [],
  standIns: [],
  ...over,
});

const labels: Record<string, string> = { pool: "Data Pool", season: "Season", map: "Shadow map" };

function renderLayers(v = view()) {
  const handlers = { onExpand: jest.fn(), onCollapse: jest.fn(), onMoveBox: jest.fn() };
  render(
    <ReactFlowProvider>
      <ScenarioLayers
        view={v}
        editable
        labelOf={(id) => labels[id] ?? id}
        statusOf={(id) => (id === "map" ? { text: "Done", tone: "done" } : { text: "Not run", tone: "none" })}
        {...handlers}
      />
    </ReactFlowProvider>,
  );
  return handlers;
}

describe("a collapsed scenario's box", () => {
  test("shows its name, its fixed context and its outcomes with their latest outputs", () => {
    renderLayers();
    const el = screen.getByTestId("scenario-box-tall");
    expect(el.textContent).toContain("Twice as tall");
    expect(el.textContent).toContain("2 nodes");
    expect(el.textContent).toContain("Fixed context");
    expect(el.textContent).toContain("Data Pool");
    expect(el.textContent).toContain("Season");
    const outcome = el.querySelector('[data-scenario-outcome="map"]')!;
    expect(outcome.textContent).toBe("Shadow mapDone");
  });

  test("a double-click expands it", () => {
    const { onExpand } = renderLayers();
    fireEvent.doubleClick(screen.getByTestId("scenario-box-tall"));
    expect(onExpand).toHaveBeenCalledWith("tall");
  });

  test("sits where the view puts it, as tall as its rows", () => {
    renderLayers();
    const el = screen.getByTestId("scenario-box-tall");
    const layout = boxLayout(box);
    expect([el.style.left, el.style.top, el.style.height]).toEqual(["10px", "20px", `${layout.height}px`]);
    // One row per context input, then one per outcome, each a port's height apart.
    expect([...layout.context.values()]).toEqual([62, 86]);
    expect([...layout.outcomes.values()]).toEqual([132]);
  });
});

/** Puts measured nodes in React Flow's store, as a rendered canvas would. */
function Measured({ nodes }: { nodes: any[] }) {
  const store = useStoreApi();
  React.useLayoutEffect(() => {
    store.getState().setNodes(nodes);
  }, [store, nodes]);
  return null;
}

const measured = [
  { id: "pool", position: { x: -300, y: 0 }, width: 100, height: 50, data: {} },
  { id: "a", position: { x: 0, y: 0 }, width: 100, height: 50, data: {} },
  { id: "map", position: { x: 200, y: 100 }, width: 100, height: 50, data: {} },
];

function renderMeasured(v: ScenarioCanvasView<any, any>) {
  const onCollapse = jest.fn();
  render(
    <ReactFlowProvider>
      <Measured nodes={measured} />
      <ScenarioLayers
        view={v}
        editable
        labelOf={(id) => id}
        statusOf={() => ({ text: "Done", tone: "done" })}
        onExpand={jest.fn()}
        onCollapse={onCollapse}
        onMoveBox={jest.fn()}
      />
    </ReactFlowProvider>,
  );
  return onCollapse;
}

describe("an expanded scenario", () => {
  test("is framed around its measured nodes, and the frame's header collapses it", () => {
    const onCollapse = renderMeasured(
      view({ boxes: [], frames: [{ scenario: { ...scenario, collapsed: false }, members: ["a", "map"] }] }),
    );
    const frame = document.querySelector('[data-scenario-frame="tall"]') as HTMLElement;
    expect([frame.style.left, frame.style.top, frame.style.width, frame.style.height]).toEqual([
      "-18px",
      "-18px",
      "336px",
      "186px",
    ]);
    fireEvent.click(screen.getByTestId("scenario-collapse-tall"));
    expect(onCollapse).toHaveBeenCalledWith("tall");
  });

  test("on the dashboard, its frame's header names it, with nothing to collapse", () => {
    render(
      <ReactFlowProvider>
        <Measured nodes={measured} />
        <ScenarioLayers
          view={view({ boxes: [], frames: [{ scenario: { ...scenario, collapsed: false }, members: ["a", "map"] }] })}
          editable={false}
          labelOf={(id) => id}
          statusOf={() => ({ text: "", tone: "none" })}
          onExpand={jest.fn()}
          onMoveBox={jest.fn()}
        />
      </ReactFlowProvider>,
    );
    const header = document.querySelector('[data-scenario-header="tall"]') as HTMLElement;
    expect(header).not.toBeNull();
    expect(header.textContent).toBe("Twice as tall");
    // Above the frame, which is 18 above the top node: 46 in all.
    expect([header.style.left, header.style.top]).toEqual(["-18px", "-46px"]);
    expect(screen.queryByTestId("scenario-collapse-tall")).toBeNull();
  });
});

describe("a stand-in edge", () => {
  test("runs from the context node to its row's port on the box", () => {
    renderMeasured(
      view({
        standIns: [
          { id: "s", source: { node: "pool", handle: "out" }, target: { box: "tall", port: "context", of: "pool" } },
        ],
      }),
    );
    const path = document.querySelector("[data-scenario-stand-in]")!;
    const d = path.getAttribute("d")!;
    // From the middle of pool's right side (no handle measured) to the port
    // on the box's left edge, at the middle of pool's row.
    expect(d.startsWith("M -200 25 ")).toBe(true);
    expect(d.endsWith(" 10 94")).toBe(true);
  });
});
