/**
 * A template that declares `opensOnControls` (Data Loading, Data Export) shows
 * only its controls on its Widgets tab, the rows a dashboard tile shows: a
 * label and a control for each widget, then the node's own (Data Export's
 * Download), with no tag, Edit, Delete, Add widget or selections. Any other
 * node keeps the whole Widgets tab. The node opens there while its code reads
 * one of its widgets, and its code stays on the Code tab; a fresh node, which
 * takes its starter and widgets after it mounts, turns there when they arrive.
 * A value set there is the node's, and a run writes it into the code. A
 * dataset widget's control is where a file or a Data Catalog dataset is
 * dropped, and its Choose file hands the files it picks to the node
 * (DatasetWidgetContext), which takes them as a drop.
 */
import React from "react";
import { act, fireEvent, render, within } from "@testing-library/react";
import type { WidgetDef } from "../../utils/widgets/widgetModel";
import {
  DatasetWidgetContext,
  type DatasetWidgetNode,
} from "../../components/editing/widgets/datasetWidgetContext";
import { WidgetControl } from "../../components/editing/widgets/WidgetControl";

const LOADER = "curio.builtin/data-loading";
const EXPORT = "curio.builtin/data-export";
const PYTHON = "curio.builtin/computation-analysis";
let mockDashboardOn = false;
const mockRequestAutoRun = jest.fn();
const mockViews = [{ id: "chart", label: "Chart" }];

jest.mock("../../providers/FlowProvider", () => ({
  useFlowContext: () => ({
    dashboardOn: mockDashboardOn,
    markDirty: jest.fn(),
    markNodeStale: jest.fn(),
    requestAutoRun: mockRequestAutoRun,
    // What a run on the node reads (CodeEditor).
    workflowNameRef: { current: "Export" },
    isDashboardSource: () => false,
    markNodeExecuted: jest.fn(),
    markNodeErrored: jest.fn(),
    signalNodeExecDone: jest.fn(),
  }),
}));
// Data Loading and Data Export declare the flag in the shipped manifest
// (dataLoadingTemplate.test.ts, test_data_loading_widget.py).
jest.mock("../../registry/nodeRegistry", () => ({
  ...jest.requireActual("../../registry/nodeRegistry"),
  tryGetNodeDescriptor: (nodeType: string) =>
    nodeType === "curio.builtin/data-loading" || nodeType === "curio.builtin/data-export"
      ? { id: nodeType, opensOnControls: true }
      : undefined,
}));
// A chart in the dataflow, so the whole Widgets tab offers Add selection.
jest.mock("../../hook/useSelectionViews", () => ({
  ...jest.requireActual("../../hook/useSelectionViews"),
  useSelectionViews: () => mockViews,
}));
jest.mock("@monaco-editor/react", () => ({
  __esModule: true,
  default: ({ value }: any) => <textarea data-testid="monaco" value={value ?? ""} readOnly />,
}));
jest.mock("../../providers/CollaborationProvider", () => ({
  useCollab: () => ({
    enabled: false,
    connected: false,
    users: [],
    proposals: [],
    currentUserId: null,
    requestCodeChange: jest.fn(),
    approveCodeChange: jest.fn(),
    rejectCodeChange: jest.fn(),
    onRemote: jest.fn(() => jest.fn()),
  }),
}));

import NodeEditor from "../../components/editing/NodeEditor";

const DATA: WidgetDef = { name: "data", type: "dataset", label: "Data", default: "" };
const FILE_NAME: WidgetDef = { name: "file_name", type: "text", label: "File name", default: "" };
const ROWS: WidgetDef = {
  name: "rows", type: "choice", label: "Rows", default: "three",
  options: { choices: ["three", "five"], display: "radio" },
};
const STARTER = "data = curio_load_data([!! data !!])\nreturn data";
const EXPORT_STARTER = "return curio_export(input_0, [!! file_name !!])";

const baseProps = {
  setSendCodeCallback: jest.fn(),
  setOutputCallback: jest.fn(),
  output: { code: "", content: "" },
  nodeType: LOADER,
  readOnly: false,
  applyGrammar: jest.fn(),
  code: true,
  grammar: false,
  widgets: true,
  defaultValue: STARTER,
};

function nodeData(widgets: WidgetDef[], extra: Record<string, unknown> = {}) {
  return { nodeId: "n1", outputCallback: jest.fn(), widgets, ...extra };
}

/** The one pane Bootstrap marks active. */
function activePane(container: HTMLElement): HTMLElement {
  const pane = container.querySelector<HTMLElement>(".tab-pane.active");
  if (!pane) throw new Error("no active pane rendered");
  return pane;
}

/** A tab of the node, by its event key, as the e2e helpers find it. */
function tabOf(container: HTMLElement, key: string): HTMLElement {
  const tab = container.querySelector<HTMLElement>(`.nav-link[data-rr-ui-event-key="${key}"]`);
  if (!tab) throw new Error(`no ${key} tab rendered`);
  return tab;
}

/** The node's Widgets tab, opened. */
function widgetsPane(container: HTMLElement): HTMLElement {
  fireEvent.click(tabOf(container, "widgets"));
  return activePane(container);
}

const showsControls = (container: HTMLElement) =>
  activePane(container).querySelector("[data-widget-controls]") !== null;
const showsCode = (container: HTMLElement) =>
  within(activePane(container)).queryByTestId("monaco") !== null;

beforeEach(() => mockRequestAutoRun.mockClear());

describe("where a node opens", () => {
  test("on its Widgets tab, when its template says so and its code reads one of its widgets", () => {
    const { container } = render(<NodeEditor {...baseProps} data={nodeData([DATA])} />);

    expect(showsControls(container)).toBe(true);
    // The code is there, on its own tab.
    expect(container.querySelector("[data-testid='monaco']")).not.toBeNull();
  });

  test("its code is one click away, on the Code tab", () => {
    const { container } = render(<NodeEditor {...baseProps} data={nodeData([DATA])} />);

    fireEvent.click(tabOf(container, "code"));

    expect(showsCode(container)).toBe(true);
  });

  test("on its code when its code reads none of its widgets, as an example's literal loader", () => {
    const { container } = render(
      <NodeEditor {...baseProps} defaultValue={'df = curio_load_data("data.utk.trees")\nreturn df'} data={nodeData([DATA])} />,
    );

    expect(showsCode(container)).toBe(true);
  });

  test("on its code when it has no widgets", () => {
    const { container } = render(<NodeEditor {...baseProps} data={nodeData([])} />);

    expect(showsCode(container)).toBe(true);
  });

  test("on its code when its template does not say so, whatever its code reads", () => {
    const { container } = render(
      <NodeEditor {...baseProps} nodeType={PYTHON} defaultValue="n = [!! rows !!]" data={nodeData([ROWS])} />,
    );

    expect(showsCode(container)).toBe(true);
  });

  test("a fresh node turns to its Widgets tab when its starter and widgets arrive, once", () => {
    const { container, rerender } = render(
      <NodeEditor {...baseProps} defaultValue={undefined} data={nodeData([])} />,
    );
    expect(showsCode(container)).toBe(true);

    rerender(<NodeEditor {...baseProps} data={nodeData([DATA])} />);
    expect(showsControls(container)).toBe(true);

    // Once the user has picked a tab, new widgets leave it there.
    fireEvent.click(tabOf(container, "code"));
    rerender(<NodeEditor {...baseProps} data={nodeData([DATA, ROWS])} />);
    expect(showsCode(container)).toBe(true);
  });
});

describe("the Widgets tab", () => {
  const SHOWING_ONLY_CONTROLS = [
    { name: "Data Loading", nodeType: LOADER, widget: DATA, starter: STARTER },
    { name: "Data Export", nodeType: EXPORT, widget: FILE_NAME, starter: EXPORT_STARTER },
  ];

  test.each(SHOWING_ONLY_CONTROLS)(
    "$name shows only its controls, and any other node its tags, Edit, Delete, Add widget and selections",
    ({ nodeType, widget, starter }) => {
      const { container, unmount } = render(
        <NodeEditor {...baseProps} nodeType={nodeType} defaultValue={starter} data={nodeData([widget])} />,
      );
      const pane = widgetsPane(container);
      const controls = pane.querySelector<HTMLElement>("[data-widget-controls]");
      expect(controls).not.toBeNull();
      expect(within(controls!).getByText(widget.label!)).toBeTruthy();
      expect(pane.querySelector("[data-widget-tag]")).toBeNull();
      expect(within(pane).queryByRole("button", { name: `Edit widget ${widget.name}` })).toBeNull();
      expect(within(pane).queryByRole("button", { name: `Delete widget ${widget.name}` })).toBeNull();
      expect(within(pane).queryByRole("button", { name: "Add widget" })).toBeNull();
      expect(pane.querySelector("[data-selections-panel]")).toBeNull();
      expect(within(pane).queryByRole("button", { name: "Add selection" })).toBeNull();
      unmount();

      // A Python node in the same dataflow keeps every part of the tab.
      const python = render(
        <NodeEditor {...baseProps} nodeType={PYTHON} defaultValue="n = [!! rows !!]" data={nodeData([ROWS])} />,
      );
      const full = widgetsPane(python.container);
      expect(full.querySelector("[data-widget-controls]")).toBeNull();
      expect(full.querySelector('[data-widget-tag="rows"]')).not.toBeNull();
      expect(within(full).getByRole("button", { name: "Edit widget rows" })).toBeTruthy();
      expect(within(full).getByRole("button", { name: "Delete widget rows" })).toBeTruthy();
      expect(within(full).getByRole("button", { name: "Add widget" })).toBeTruthy();
      expect(full.querySelector("[data-selections-panel]")).not.toBeNull();
      expect(within(full).getByRole("button", { name: "Add selection" })).toBeTruthy();
    },
  );

  test("a node that shows only its controls, with none, says so and offers no Add widget", () => {
    const { container } = render(<NodeEditor {...baseProps} data={nodeData([])} />);

    const pane = widgetsPane(container);

    expect(within(pane).getByText("This node has no widgets.")).toBeTruthy();
    expect(within(pane).queryByRole("button", { name: "Add widget" })).toBeNull();
  });

  test("a value set on its controls is the node's, and a run writes it into the code", () => {
    const interpretCode = jest.fn();
    const setSendCodeCallback = jest.fn();
    const data = nodeData([FILE_NAME], { pythonInterpreter: { interpretCode } });
    const props = { ...baseProps, nodeType: EXPORT, defaultValue: EXPORT_STARTER, setSendCodeCallback };
    const { container, rerender } = render(<NodeEditor {...props} data={data} />);

    const controls = activePane(container).querySelector<HTMLElement>("[data-widget-controls]");
    expect(controls).not.toBeNull();
    const field = within(controls!).getByLabelText("File name", { selector: "input" });
    fireEvent.change(field, { target: { value: "trees" } });
    fireEvent.blur(field);

    // The node holds it, and is out of date: an automatic run takes it.
    expect(data.widgets).toEqual([{ ...FILE_NAME, value: "trees" }]);
    expect(mockRequestAutoRun).toHaveBeenCalledWith(["n1"]);

    // Played, the node runs its code with the value written in.
    rerender(<NodeEditor {...props} data={data} output={{ code: "exec", content: "" }} />);
    const play = setSendCodeCallback.mock.calls[0][0];
    act(() => play(EXPORT_STARTER));

    expect(interpretCode).toHaveBeenCalledTimes(1);
    expect(interpretCode.mock.calls[0][1]).toBe('return curio_export(input_0, "trees")');
  });

  test("a run of an empty Data ends with what to drop, though its tab lists no problem", () => {
    const setOutputCallback = jest.fn();
    const setSendCodeCallback = jest.fn();
    const { container } = render(
      <NodeEditor {...baseProps} setOutputCallback={setOutputCallback} setSendCodeCallback={setSendCodeCallback} data={nodeData([DATA])} />,
    );
    expect(showsControls(container)).toBe(true);
    expect(within(activePane(container)).queryByLabelText("References that do not resolve")).toBeNull();

    const play = setSendCodeCallback.mock.calls[0][0];
    act(() => play(STARTER));

    expect(setOutputCallback).toHaveBeenCalledWith({
      code: "error",
      content: expect.stringContaining("[!! data !!]: drop a file or a Data Catalog dataset on Data first."),
    });
  });
});

describe("controls of the node's own (Data Export's Download)", () => {
  const download = <button type="button" data-download-button="true">Download trees.csv</button>;
  const props = { ...baseProps, nodeType: EXPORT, defaultValue: EXPORT_STARTER, controlsComponent: download };

  afterEach(() => { mockDashboardOn = false; });

  test("sit on the Widgets tab the node opens on, under File name's control, and nowhere on its code", () => {
    const { container } = render(<NodeEditor {...props} data={nodeData([FILE_NAME])} />);

    const controls = activePane(container).querySelector<HTMLElement>("[data-widget-controls]");
    expect(controls).not.toBeNull();
    const own = controls!.querySelector<HTMLElement>("[data-node-controls]");
    expect(own && within(own).getByRole("button", { name: "Download trees.csv" })).toBeTruthy();
    // Right under File name's row, and once in the node.
    expect(own!.previousElementSibling?.getAttribute("data-widget-row")).toBe("file_name");
    expect(container.querySelectorAll("[data-download-button]")).toHaveLength(1);

    fireEvent.click(tabOf(container, "code"));
    expect(showsCode(container)).toBe(true);
    expect(within(activePane(container)).queryByRole("button", { name: "Download trees.csv" })).toBeNull();
  });

  test("stay on the Widgets tab when the node holds no widgets", () => {
    const { container } = render(<NodeEditor {...props} data={nodeData([])} />);

    const controls = widgetsPane(container).querySelector<HTMLElement>("[data-widget-controls]");
    expect(controls && within(controls).getByRole("button", { name: "Download trees.csv" })).toBeTruthy();
    expect(within(controls!).queryByText("This node has no widgets.")).toBeNull();
  });

  test("on a dashboard tile, sit under the controls of its widgets, once", () => {
    mockDashboardOn = true;
    const { container } = render(<NodeEditor {...props} data={nodeData([FILE_NAME])} />);

    const pane = activePane(container);
    expect(within(pane).getByText("File name")).toBeTruthy();
    const own = pane.querySelector<HTMLElement>("[data-node-controls]");
    expect(own && within(own).getByRole("button", { name: "Download trees.csv" })).toBeTruthy();
    // After the File name control, and in no other pane.
    expect(pane.querySelector("[data-widget-controls]")!.compareDocumentPosition(own!)
      & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(container.querySelectorAll("[data-download-button]")).toHaveLength(1);
    // The tile shows its controls, not its code.
    expect(pane.querySelector("[data-testid='monaco']")).toBeNull();
  });
});

describe("a dataset widget's control", () => {
  function renderWith(node: Partial<DatasetWidgetNode>, value: string) {
    const held: DatasetWidgetNode = { describe: () => undefined, dropping: false, ...node };
    return render(
      <DatasetWidgetContext.Provider value={held}>
        <WidgetControl widget={DATA} value={value} onChange={jest.fn()} />
      </DatasetWidgetContext.Provider>,
    );
  }

  test("empty, it says what to drop and offers Choose file", () => {
    const { container } = renderWith({ takeFiles: jest.fn() }, "");

    const zone = container.querySelector<HTMLElement>("[data-dataset-drop]");
    expect(zone?.getAttribute("data-dataset-drop")).toBe("empty");
    expect(within(zone!).getByText("Drop a file or a Data Catalog dataset here")).toBeTruthy();
    expect(within(zone!).getByText("Choose file")).toBeTruthy();
  });

  test("Choose file hands the picked file to the node, which takes it as a drop", () => {
    const takeFiles = jest.fn();
    const { container } = renderWith({ takeFiles }, "");
    const input = container.querySelector<HTMLInputElement>("[data-dataset-drop] input[type='file']");
    const file = new File(["id,height\n1,10\n"], "trees.csv", { type: "text/csv" });

    fireEvent.change(input!, { target: { files: [file] } });

    expect(takeFiles).toHaveBeenCalledWith([file]);
  });

  test("set, it names the dataset and its format", () => {
    const { container } = renderWith(
      { takeFiles: jest.fn(), describe: (id) => (id === "imported.xtrees" ? { title: "trees.csv", format: "csv" } : undefined) },
      "imported.xtrees",
    );

    const zone = container.querySelector<HTMLElement>("[data-dataset-drop]");
    expect(zone?.getAttribute("data-dataset-drop")).toBe("set");
    expect(within(zone!).getByText("trees.csv")).toBeTruthy();
    expect(within(zone!).getByText("CSV")).toBeTruthy();
  });

  test("where no file can be added, it offers no Choose file", () => {
    const { container } = renderWith({}, "");

    expect(container.querySelector("[data-dataset-drop] input[type='file']")).toBeNull();
  });

  test("it lights up while a drop is over its node", () => {
    const { container } = renderWith({ takeFiles: jest.fn(), dropping: true }, "");

    expect(container.querySelector("[data-dataset-drop]")?.className).toMatch(/datasetDropActive/);
  });
});
