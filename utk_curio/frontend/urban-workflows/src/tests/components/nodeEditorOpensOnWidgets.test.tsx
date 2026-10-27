/**
 * A template that declares `opensOnWidgets` (Data Loading) opens on its Widgets
 * tab, where the user sets what its code reads, while its code reads one of its
 * widgets; its code stays on the Code tab. A fresh node, which takes its
 * starter and widgets after it mounts, turns there when they arrive. A dataset
 * widget's control is where a file or a Data Catalog dataset is dropped, and
 * its Choose file hands the files it picks to the node (DatasetWidgetContext),
 * which takes them as a drop.
 */
import React from "react";
import { fireEvent, render, within } from "@testing-library/react";
import type { WidgetDef } from "../../utils/widgets/widgetModel";
import {
  DatasetWidgetContext,
  type DatasetWidgetNode,
} from "../../components/editing/widgets/datasetWidgetContext";
import { WidgetControl } from "../../components/editing/widgets/WidgetControl";

const LOADER = "acme.tools/loader";

jest.mock("../../providers/FlowProvider", () => ({
  useFlowContext: () => ({
    dashboardOn: false,
    markDirty: jest.fn(),
    markNodeStale: jest.fn(),
    requestAutoRun: jest.fn(),
  }),
}));
jest.mock("../../registry/nodeRegistry", () => ({
  ...jest.requireActual("../../registry/nodeRegistry"),
  tryGetNodeDescriptor: (nodeType: string) =>
    nodeType === "acme.tools/loader" ? { id: nodeType, opensOnWidgets: true } : undefined,
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
jest.mock("../../components/editing/WidgetsEditor", () => ({
  __esModule: true,
  default: () => <div data-testid="widgets-editor" />,
}));

import NodeEditor from "../../components/editing/NodeEditor";

const DATA: WidgetDef = { name: "data", type: "dataset", label: "Data", default: "" };
const ROWS: WidgetDef = {
  name: "rows", type: "choice", label: "Rows", default: "three",
  options: { choices: ["three", "five"], display: "radio" },
};
const STARTER = "data = curio_load_data([!! data !!])\nreturn data";

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

function nodeData(widgets: WidgetDef[]) {
  return { nodeId: "n1", outputCallback: jest.fn(), widgets };
}

/** The one pane Bootstrap marks active. */
function activePane(container: HTMLElement): HTMLElement {
  const pane = container.querySelector<HTMLElement>(".tab-pane.active");
  if (!pane) throw new Error("no active pane rendered");
  return pane;
}

/** The node's Code tab, by its event key, as the e2e helpers find it. */
function codeTab(container: HTMLElement): HTMLElement {
  const tab = container.querySelector<HTMLElement>('.nav-link[data-rr-ui-event-key="code"]');
  if (!tab) throw new Error("no Code tab rendered");
  return tab;
}

const showsWidgets = (container: HTMLElement) =>
  within(activePane(container)).queryByTestId("widgets-editor") !== null;
const showsCode = (container: HTMLElement) =>
  within(activePane(container)).queryByTestId("monaco") !== null;

describe("where a node opens", () => {
  test("on its Widgets tab, when its template says so and its code reads one of its widgets", () => {
    const { container } = render(<NodeEditor {...baseProps} data={nodeData([DATA])} />);

    expect(showsWidgets(container)).toBe(true);
    // The code is there, on its own tab.
    expect(container.querySelector("[data-testid='monaco']")).not.toBeNull();
  });

  test("its code is one click away, on the Code tab", () => {
    const { container } = render(<NodeEditor {...baseProps} data={nodeData([DATA])} />);

    fireEvent.click(codeTab(container));

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
      <NodeEditor
        {...baseProps}
        nodeType="curio.builtin/computation-analysis"
        defaultValue="n = [!! rows !!]"
        data={nodeData([ROWS])}
      />,
    );

    expect(showsCode(container)).toBe(true);
  });

  test("a fresh node turns to its Widgets tab when its starter and widgets arrive, once", () => {
    const { container, rerender } = render(
      <NodeEditor {...baseProps} defaultValue={undefined} data={nodeData([])} />,
    );
    expect(showsCode(container)).toBe(true);

    rerender(<NodeEditor {...baseProps} data={nodeData([DATA])} />);
    expect(showsWidgets(container)).toBe(true);

    // Once the user has picked a tab, new widgets leave it there.
    fireEvent.click(codeTab(container));
    rerender(<NodeEditor {...baseProps} data={nodeData([DATA, ROWS])} />);
    expect(showsCode(container)).toBe(true);
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
