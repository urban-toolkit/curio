/**
 * Which pane a dashboard tile shows.
 *
 * On the dashboard a tile shows its output, not its editor, so the output pane
 * is forced. But only a node that HAS one: a code node's result is the text box
 * under its editor, in the code pane. Forcing a pane that does not exist left a
 * pinned code node as an empty tile with nothing reachable on it, which was
 * already true of the old canvas mode and became visible once the dashboard was
 * a page of its own.
 *
 * A node with widgets shows them as the tile's controls (#1117): in place of a
 * code node's code, whose pane stays mounted and hidden, and above a chart or
 * a map, which fills the rest of the tile. A viewer's change asks for a run
 * and never marks the dataflow to save, and a tile's code is read-only.
 */
import React from "react";
import { fireEvent, render, within } from "@testing-library/react";
import type { WidgetDef } from "../../utils/widgets/widgetModel";

let mockDashboardOn = false;
const mockMarkDirty = jest.fn();
const mockMarkNodeStale = jest.fn();
const mockRequestAutoRun = jest.fn();

jest.mock("../../providers/FlowProvider", () => ({
  useFlowContext: () => ({
    dashboardOn: mockDashboardOn,
    markDirty: mockMarkDirty,
    markNodeStale: mockMarkNodeStale,
    requestAutoRun: mockRequestAutoRun,
  }),
}));
// The editor says whether it takes edits.
jest.mock("@monaco-editor/react", () => ({
  __esModule: true,
  default: ({ value, options }: any) => (
    <textarea data-testid="monaco" data-read-only={options?.readOnly ? "true" : "false"} value={value ?? ""} readOnly />
  ),
}));
jest.mock("../../providers/CollaborationProvider", () => ({
  useCollab: () => ({
    connected: false,
    users: [],
    onRemote: jest.fn(() => jest.fn()),
  }),
}));
jest.mock("../../components/editing/WidgetsEditor", () => ({ __esModule: true, default: () => null }));

import NodeEditor from "../../components/editing/NodeEditor";

const baseProps = {
  setSendCodeCallback: jest.fn(),
  setOutputCallback: jest.fn(),
  data: { nodeId: "n1", outputCallback: jest.fn() },
  output: { code: "", content: "" },
  nodeType: "curio.builtin/computation-analysis",
  readOnly: false,
  applyGrammar: jest.fn(),
  code: true,
  grammar: false,
  widgets: false,
  defaultValue: "return 1",
};

/** The one pane Bootstrap marks active. */
function activePane(container: HTMLElement): HTMLElement {
  const pane = container.querySelector<HTMLElement>(".tab-pane.active");
  if (!pane) throw new Error("no active pane rendered");
  return pane;
}

beforeEach(() => {
  mockDashboardOn = false;
  mockMarkDirty.mockReset();
  mockMarkNodeStale.mockReset();
  mockRequestAutoRun.mockReset();
});

const rows: WidgetDef = {
  name: "rows", type: "choice", label: "Rows", default: "three",
  options: { choices: ["three", "five"], display: "radio" },
};
const opacity: WidgetDef = {
  name: "opacity", type: "slider", label: "Opacity", default: 1, options: { min: 0.1, max: 1, step: 0.1 },
};
const note: WidgetDef = { name: "note", type: "text", label: "Note", default: "" };

/** A pinned node's data, holding *widgets*. */
function nodeData(widgets: WidgetDef[]) {
  return { nodeId: "n1", outputCallback: jest.fn(), dashboardPinned: true, widgets };
}

/** The Bootstrap pane the code editor sits in. */
function codePane(container: HTMLElement): HTMLElement {
  const pane = container.querySelector("[data-testid='monaco']")?.closest<HTMLElement>(".tab-pane");
  if (!pane) throw new Error("no code pane rendered");
  return pane;
}

test("a pinned code node shows its code pane, where its output is", () => {
  mockDashboardOn = true;

  const { container } = render(<NodeEditor {...baseProps} />);

  expect(activePane(container).querySelector("[data-testid='monaco']")).not.toBeNull();
});

test("a pinned chart shows its output pane", () => {
  mockDashboardOn = true;

  const { container } = render(
    <NodeEditor {...baseProps} nodeType="curio.builtin/vis-vega" outputId="vega-n1" />,
  );

  expect(activePane(container).querySelector("#vega-n1")).not.toBeNull();
});

test("a node with custom content shows that content", () => {
  mockDashboardOn = true;

  const { container } = render(
    <NodeEditor {...baseProps} contentComponent={<div data-testid="table" />} />,
  );

  expect(activePane(container).querySelector("[data-testid='table']")).not.toBeNull();
});

test("the tab bar is not drawn on a tile", () => {
  mockDashboardOn = true;

  const { container } = render(<NodeEditor {...baseProps} outputId="vega-n1" />);

  expect(container.querySelector(".nav-pills")).toBeNull();
});

test("on the canvas nothing changes: the editor opens on its first tab", () => {
  const { container } = render(<NodeEditor {...baseProps} outputId="vega-n1" />);

  expect(activePane(container).querySelector("[data-testid='monaco']")).not.toBeNull();
  expect(container.querySelector(".nav-pills")).not.toBeNull();
});

describe("a pinned node's widgets are its tile's controls (#1117)", () => {
  test("a code node shows them in place of its code, whose pane stays mounted and hidden", () => {
    mockDashboardOn = true;

    const { container } = render(<NodeEditor {...baseProps} widgets data={nodeData([rows])} />);

    const pane = activePane(container);
    expect(pane.querySelector("[data-widget-controls]")).not.toBeNull();
    expect(within(pane).getByRole("radio", { name: "five" })).toBeTruthy();
    expect(pane.querySelector("[data-testid='monaco']")).toBeNull();
    // Its editor holds the node's run: mounted, in a pane that is not shown.
    expect(codePane(container).classList.contains("active")).toBe(false);
  });

  test("a chart shows them above its output, which fills the rest of the tile", () => {
    mockDashboardOn = true;

    const { container } = render(
      <NodeEditor
        {...baseProps}
        nodeType="curio.builtin/vis-vega"
        outputId="vega-n1"
        code={false}
        grammar
        widgets
        defaultValue="{}"
        data={nodeData([opacity])}
      />,
    );

    const column = activePane(container).querySelector<HTMLElement>("[data-tile-column]");
    if (!column) throw new Error("the tile has no column of controls and output");
    expect(column.style.display).toBe("flex");
    expect(column.style.flexDirection).toBe("column");
    const [controls, chart] = Array.from(column.children) as HTMLElement[];
    expect(controls.hasAttribute("data-widget-controls")).toBe(true);
    expect(within(controls).getByRole("slider", { name: "Opacity" })).toBeTruthy();
    expect(chart.id).toBe("vega-n1");
    // The chart takes what the controls leave, not the whole tile.
    expect(chart.style.height).toBe("");
    expect(chart.style.flexGrow).toBe("1");
    expect(parseFloat(chart.style.minHeight)).toBe(0);
  });

  test("a map's content sits below them the same way", () => {
    mockDashboardOn = true;

    const { container } = render(
      <NodeEditor
        {...baseProps}
        nodeType="curio.builtin/autk-grammar"
        code={false}
        grammar
        widgets
        defaultValue="{}"
        data={nodeData([opacity])}
        contentComponent={<div data-testid="map" />}
      />,
    );

    const column = activePane(container).querySelector<HTMLElement>("[data-tile-column]");
    if (!column) throw new Error("the tile has no column of controls and output");
    const [controls, mount] = Array.from(column.children) as HTMLElement[];
    expect(controls.hasAttribute("data-widget-controls")).toBe(true);
    expect(within(mount).getByTestId("map")).toBeTruthy();
    expect(mount.style.height).toBe("");
    expect(mount.style.flexGrow).toBe("1");
  });

  test("a text widget stays read-only, as the dashboard's contract says; a choice does not", () => {
    mockDashboardOn = true;

    const { container } = render(<NodeEditor {...baseProps} widgets data={nodeData([note, rows])} />);

    const pane = activePane(container);
    expect((within(pane).getByLabelText("Note", { selector: "input" }) as HTMLInputElement).disabled).toBe(true);
    expect((within(pane).getByRole("radio", { name: "five" }) as HTMLInputElement).disabled).toBe(false);
  });

  test("a change asks for a run of the node and never marks the dataflow to save", () => {
    mockDashboardOn = true;
    const data = nodeData([rows]);
    const { container } = render(<NodeEditor {...baseProps} widgets data={data} />);
    const five = within(activePane(container)).getByRole("radio", { name: "five" });

    fireEvent.click(five);
    fireEvent.blur(five);

    expect(data.widgets).toEqual([{ ...rows, value: "five" }]);
    expect(mockMarkNodeStale).toHaveBeenCalledWith("n1");
    expect(mockRequestAutoRun).toHaveBeenCalledWith(["n1"]);
    expect(mockMarkDirty).not.toHaveBeenCalled();
  });

  test("a node that could hold widgets but holds none shows its code, as before", () => {
    mockDashboardOn = true;

    const { container } = render(<NodeEditor {...baseProps} widgets data={nodeData([])} />);

    expect(activePane(container).querySelector("[data-testid='monaco']")).not.toBeNull();
    expect(container.querySelector("[data-widget-controls]")).toBeNull();
  });

  test("on the canvas a node with widgets shows no controls", () => {
    const { container } = render(<NodeEditor {...baseProps} widgets data={nodeData([rows])} />);

    expect(container.querySelector("[data-widget-controls]")).toBeNull();
    expect(activePane(container).querySelector("[data-testid='monaco']")).not.toBeNull();
  });
});

describe("a tile's code is read-only: Save layout would save a stray edit", () => {
  test("on a tile", () => {
    mockDashboardOn = true;

    const { container } = render(<NodeEditor {...baseProps} />);

    expect(activePane(container).querySelector("[data-testid='monaco']")?.getAttribute("data-read-only")).toBe("true");
  });

  test("but not on the canvas", () => {
    const { container } = render(<NodeEditor {...baseProps} />);

    expect(activePane(container).querySelector("[data-testid='monaco']")?.getAttribute("data-read-only")).toBe("false");
  });
});
