/**
 * A collapsed scenario's box (#662): one box tinted in its color, with its
 * name and a card per node it holds, with the node's kind and latest output, a
 * port on each card for the stand-in edges, and a double-click that expands
 * it. An expanded scenario has a frame whose header collapses it. A set's
 * shared context and shared outcomes are framed in gray under a pill that
 * collapses them, and collapsed into a box of cards with the set's circles.
 */
import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { ReactFlowProvider, useStoreApi } from "reactflow";

jest.mock("../../providers/FlowProvider", () => ({ useFlowContext: () => ({}) }));
jest.mock("../../components/scenarios/useScenarioActions", () => ({ useScenarioActions: () => ({}) }));

import { ScenarioLayers, boxLayout, groupBoxLayout } from "../../components/scenarios/ScenarioLayers";
import type { ScenarioBox, ScenarioCanvasView, SharedGroup } from "../../utils/scenarios/scenarioCanvasView";

const scenario = { id: "tall", name: "Twice as tall", color: "#e86a3c", nodes: ["a", "map"], collapsed: true };
const box: ScenarioBox = {
  scenario,
  x: 10,
  y: 20,
  parts: { levers: ["a", "map"], context: ["pool", "season"], outcomes: ["map"] },
  rows: ["a", "map"],
};

const view = (over: Partial<ScenarioCanvasView<any, any>> = {}): ScenarioCanvasView<any, any> => ({
  nodes: [],
  edges: [],
  boxes: [box],
  frames: [],
  standIns: [],
  dots: [],
  ...over,
});

const labels: Record<string, string> = { pool: "Data Pool", season: "Season", map: "Shadow map", a: "Scale heights" };
const kinds: Record<string, string> = { a: "Python", map: "Autark", chart: "Vega-Lite" };

function renderLayers(v = view()) {
  const handlers = {
    onExpand: jest.fn(),
    onCollapse: jest.fn(),
    onMoveBox: jest.fn(),
    onSharedCollapse: jest.fn(),
    onSharedMove: jest.fn(),
  };
  render(
    <ReactFlowProvider>
      <ScenarioLayers
        view={v}
        editable
        labelOf={(id) => labels[id] ?? id}
        typeOf={(id) => kinds[id] ?? ""}
        statusOf={(id) => (id === "map" ? { text: "Done", tone: "done" } : { text: "Not run", tone: "none" })}
        {...handlers}
      />
    </ReactFlowProvider>,
  );
  return handlers;
}

describe("a collapsed scenario's box", () => {
  test("shows its name and a card per node, with its kind and latest output", () => {
    renderLayers();
    const el = screen.getByTestId("scenario-box-tall");
    expect(el.textContent).toContain("Twice as tall");
    expect(el.textContent).toContain("Double-click to expand");
    expect(el.textContent).not.toContain("Data Pool");
    expect(el.querySelector('[data-scenario-row="a"]')!.textContent).toBe("PythonNot runScale heights");
    expect(el.querySelector('[data-scenario-row="map"]')!.textContent).toBe("AutarkDoneShadow map");
  });

  test("a double-click expands it", () => {
    const { onExpand } = renderLayers();
    fireEvent.doubleClick(screen.getByTestId("scenario-box-tall"));
    expect(onExpand).toHaveBeenCalledWith("tall");
  });

  test("sits where the view puts it, as tall as its cards", () => {
    renderLayers();
    const el = screen.getByTestId("scenario-box-tall");
    const layout = boxLayout(box);
    expect([el.style.left, el.style.top, el.style.height]).toEqual(["10px", "20px", `${layout.height}px`]);
    // Under its header, a card per node, each a card and a gap apart.
    expect([...layout.rows]).toEqual([
      ["a", 58],
      ["map", 124],
    ]);
    expect(layout.height).toBe(192);
  });
});

const outcomes: SharedGroup = {
  key: "group:park:outcomes",
  set: "park",
  kind: "outcomes",
  nodes: ["map", "chart"],
  collapsed: true,
  x: 400,
  y: 30,
};
const circles = (node: string) => ({
  node,
  dots: [
    { scenario: "e", name: "Existing", color: "#2a9d8f", member: true },
    { scenario: "tall", name: "Twice as tall", color: "#e86a3c", member: node === "map" },
  ],
});

describe("a collapsed shared group", () => {
  test("is a box of cards with the set's circles, under its pill, and a double-click opens it", () => {
    const { onSharedCollapse } = renderLayers(
      view({ boxes: [], groups: [outcomes], dots: [circles("map"), circles("chart")] }),
    );
    const el = screen.getByTestId("shared-box-park-outcomes");
    expect([el.style.left, el.style.top, el.style.height]).toEqual([
      "400px",
      "30px",
      `${groupBoxLayout(outcomes).height}px`,
    ]);
    const chart = el.querySelector('[data-shared-row="chart"]')!;
    // Its latest output, as the scenario box shows it, then its circles.
    expect(chart.textContent).toBe("Vega-LiteNot runchart");
    expect(el.querySelector('[data-shared-row="map"] [data-tone="done"]')!.textContent).toBe("Done");
    const dots = [...chart.querySelectorAll("[data-scenario]")].map((d) => d.getAttribute("data-member"));
    expect(dots).toEqual(["true", "false"]);
    const header = document.querySelector('[data-shared-header="group:park:outcomes"]') as HTMLElement;
    expect(header.textContent).toBe("Shared outcomes");
    expect([header.style.left, header.style.top]).toEqual(["400px", "2px"]);
    expect(el.textContent).toContain("Double-click to expand");
    fireEvent.doubleClick(el);
    expect(onSharedCollapse).toHaveBeenCalledWith("park", "outcomes", false);
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

describe("an expanded shared group", () => {
  test("is framed in gray around its nodes, under a pill whose Collapse collapses it", () => {
    const onSharedCollapse = jest.fn();
    render(
      <ReactFlowProvider>
        <Measured nodes={measured} />
        <ScenarioLayers
          view={view({ boxes: [], groups: [{ ...outcomes, nodes: ["pool"], kind: "context", collapsed: false }] })}
          editable
          labelOf={(id) => id}
          statusOf={() => ({ text: "", tone: "none" })}
          onExpand={jest.fn()}
          onMoveBox={jest.fn()}
          onSharedCollapse={onSharedCollapse}
        />
      </ReactFlowProvider>,
    );
    const frame = document.querySelector('[data-shared-group="group:park:outcomes"]') as HTMLElement;
    expect([frame.style.left, frame.style.top, frame.style.width, frame.style.height]).toEqual([
      "-318px",
      "-18px",
      "136px",
      "86px",
    ]);
    const header = document.querySelector('[data-shared-header="group:park:outcomes"]') as HTMLElement;
    expect(header.textContent).toBe("Shared contextCollapse");
    expect([header.style.left, header.style.top]).toEqual(["-318px", "-46px"]);
    fireEvent.click(screen.getByTestId("shared-collapse-park-context"));
    expect(onSharedCollapse).toHaveBeenCalledWith("park", "context", true);
  });
});

describe("a stand-in edge", () => {
  test("runs from a node to the port of the card it enters", () => {
    renderMeasured(
      view({
        standIns: [{ id: "s", source: { node: "pool", handle: "out" }, target: { box: "tall", port: "in", of: "a" } }],
      }),
    );
    const path = document.querySelector("[data-scenario-stand-in]")!;
    const d = path.getAttribute("d")!;
    // From the middle of pool's right side (no handle measured) to the port
    // on the box's left edge, at the middle of a's card.
    expect(d.startsWith("M -200 25 ")).toBe(true);
    expect(d.endsWith(" 10 107")).toBe(true);
  });

  test("leaves a collapsed group's box from the card of the node it leaves", () => {
    renderMeasured(
      view({
        boxes: [],
        groups: [outcomes],
        standIns: [{ id: "s", source: { box: outcomes.key, port: "out", of: "chart" }, target: { node: "a" } }],
      }),
    );
    const d = document.querySelector("[data-scenario-stand-in]")!.getAttribute("d")!;
    // The box's right edge, at the middle of chart's card: 30 + 34 + 66 + 29.
    expect(d.startsWith("M 660 159 ")).toBe(true);
  });
});
