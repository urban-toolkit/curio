/**
 * A template that declares `widgetsWithCode` (Data Loading) shows its widgets'
 * controls above its code on the canvas, so what the code reads and the code
 * are seen together. A dataset widget's control is where a file or a Data
 * Catalog dataset is dropped, and its Choose file hands the files it picks to
 * the node (DatasetWidgetContext), which takes them as a drop.
 */
import React from "react";
import { fireEvent, render, within } from "@testing-library/react";
import type { WidgetDef } from "../../utils/widgets/widgetModel";
import {
  DatasetWidgetContext,
  type DatasetWidgetNode,
} from "../../components/editing/widgets/datasetWidgetContext";

const mockMarkDirty = jest.fn();
const mockMarkNodeStale = jest.fn();
const mockRequestAutoRun = jest.fn();
const LOADER = "acme.tools/loader";

jest.mock("../../providers/FlowProvider", () => ({
  useFlowContext: () => ({
    dashboardOn: false,
    markDirty: mockMarkDirty,
    markNodeStale: mockMarkNodeStale,
    requestAutoRun: mockRequestAutoRun,
  }),
}));
jest.mock("../../registry/nodeRegistry", () => ({
  ...jest.requireActual("../../registry/nodeRegistry"),
  tryGetNodeDescriptor: (nodeType: string) =>
    nodeType === "acme.tools/loader" ? { id: nodeType, widgetsWithCode: true } : undefined,
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
jest.mock("../../components/editing/WidgetsEditor", () => ({ __esModule: true, default: () => null }));

import NodeEditor from "../../components/editing/NodeEditor";

const DATA: WidgetDef = { name: "data", type: "dataset", label: "Data", default: "" };
const ROWS: WidgetDef = {
  name: "rows", type: "choice", label: "Rows", default: "three",
  options: { choices: ["three", "five"], display: "radio" },
};

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
  defaultValue: "data = curio_load_data([!! data !!])\nreturn data",
};

function nodeData(widgets: WidgetDef[]) {
  return { nodeId: "n1", outputCallback: jest.fn(), widgets };
}

/** The one pane Bootstrap marks active. */
function activePane(container: HTMLElement): HTMLElement {
  const pane = container.querySelector<HTMLElement>(".tab-pane.active");
  if (!pane) throw new Error("no active pane rendered");
  return pane;
}

beforeEach(() => {
  mockMarkDirty.mockReset();
  mockMarkNodeStale.mockReset();
  mockRequestAutoRun.mockReset();
});

test("the controls sit above the code, in the code's own pane", () => {
  const { container } = render(<NodeEditor {...baseProps} data={nodeData([DATA])} />);

  const column = activePane(container).querySelector<HTMLElement>("[data-controls-with-code]");
  if (!column) throw new Error("the code pane has no column of controls and code");
  const [controls, code] = Array.from(column.children) as HTMLElement[];
  expect(controls.hasAttribute("data-widget-controls")).toBe(true);
  expect(within(controls).getByText("Data")).toBeTruthy();
  expect(code.querySelector("[data-testid='monaco']")).not.toBeNull();
  // The code takes what the controls leave.
  expect(code.style.flexGrow).toBe("1");
});

test("a template that does not declare it keeps its controls in the Widgets tab", () => {
  const { container } = render(
    <NodeEditor {...baseProps} nodeType="curio.builtin/computation-analysis" data={nodeData([ROWS])} />,
  );

  expect(container.querySelector("[data-widget-controls]")).toBeNull();
  expect(container.querySelector("[data-controls-with-code]")).toBeNull();
  expect(activePane(container).querySelector("[data-testid='monaco']")).not.toBeNull();
});

test("with no widgets, the code fills the pane", () => {
  const { container } = render(<NodeEditor {...baseProps} data={nodeData([])} />);

  expect(container.querySelector("[data-widget-controls]")).toBeNull();
  expect(activePane(container).querySelector("[data-testid='monaco']")).not.toBeNull();
});

test("a value set there is set as the Widgets tab sets it: out of date, saved, and run when automatic", () => {
  const data = nodeData([ROWS]);
  const { container } = render(<NodeEditor {...baseProps} data={data} />);
  const five = within(activePane(container)).getByRole("radio", { name: "five" });

  fireEvent.click(five);
  fireEvent.blur(five);

  expect(data.widgets).toEqual([{ ...ROWS, value: "five" }]);
  expect(mockMarkNodeStale).toHaveBeenCalledWith("n1");
  expect(mockMarkDirty).toHaveBeenCalled();
  expect(mockRequestAutoRun).toHaveBeenCalledWith(["n1"]);
});

describe("a dataset widget's control", () => {
  function renderWith(node: Partial<DatasetWidgetNode>, widgets: WidgetDef[]) {
    const value: DatasetWidgetNode = { describe: () => undefined, dropping: false, ...node };
    return render(
      <DatasetWidgetContext.Provider value={value}>
        <NodeEditor {...baseProps} data={nodeData(widgets)} />
      </DatasetWidgetContext.Provider>,
    );
  }

  test("empty, it says what to drop and offers Choose file", () => {
    const { container } = renderWith({ takeFiles: jest.fn() }, [DATA]);

    const zone = container.querySelector<HTMLElement>("[data-dataset-drop]");
    expect(zone?.getAttribute("data-dataset-drop")).toBe("empty");
    expect(within(zone!).getByText("Drop a file or a Data Catalog dataset here")).toBeTruthy();
    expect(within(zone!).getByText("Choose file")).toBeTruthy();
  });

  test("Choose file hands the picked file to the node, which takes it as a drop", () => {
    const takeFiles = jest.fn();
    const { container } = renderWith({ takeFiles }, [DATA]);
    const input = container.querySelector<HTMLInputElement>("[data-dataset-drop] input[type='file']");
    const file = new File(["id,height\n1,10\n"], "trees.csv", { type: "text/csv" });

    fireEvent.change(input!, { target: { files: [file] } });

    expect(takeFiles).toHaveBeenCalledWith([file]);
  });

  test("set, it names the dataset and its format", () => {
    const { container } = renderWith(
      { takeFiles: jest.fn(), describe: (id) => (id === "imported.xtrees" ? { title: "trees.csv", format: "csv" } : undefined) },
      [{ ...DATA, value: "imported.xtrees" }],
    );

    const zone = container.querySelector<HTMLElement>("[data-dataset-drop]");
    expect(zone?.getAttribute("data-dataset-drop")).toBe("set");
    expect(within(zone!).getByText("trees.csv")).toBeTruthy();
    expect(within(zone!).getByText("CSV")).toBeTruthy();
  });

  test("where no file can be added, it offers no Choose file", () => {
    const { container } = renderWith({}, [DATA]);

    expect(container.querySelector("[data-dataset-drop] input[type='file']")).toBeNull();
  });

  test("it lights up while a drop is over its node", () => {
    const { container } = renderWith({ takeFiles: jest.fn(), dropping: true }, [DATA]);

    expect(container.querySelector("[data-dataset-drop]")?.className).toMatch(/datasetDropActive/);
  });
});
