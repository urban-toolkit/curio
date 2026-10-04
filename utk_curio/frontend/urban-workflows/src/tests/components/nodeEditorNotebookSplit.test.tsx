/**
 * A Vega-Lite or Autark node shown as a notebook cell shows its grammar and its
 * output at once, the way a notebook cell shows its code above its output.
 *
 * NodeEditor keeps every tab pane where it is (moving the output pane would
 * remount the chart's or the map's mount). Under the notebook view the panes'
 * container is a split (`curio-notebook-split`) and the output pane is marked
 * to stay visible (`curio-notebook-output`, Node.css) while the grammar tab is
 * the active one. jsdom has no stylesheet, so the contract is the classes, as
 * nodeEditorOutputScroll.test.tsx checks `nowheel`. Same harness.
 */
import React from "react";
import { act, render } from "@testing-library/react";

jest.mock("../../providers/FlowProvider", () => ({
  useFlowContext: () => ({ dashboardOn: false }),
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
jest.mock("../../components/editing/NodeProvenance", () => ({ __esModule: true, default: () => null }));

import NodeEditor from "../../components/editing/NodeEditor";
import { NotebookViewContext } from "../../providers/flow/notebookViewContext";

const OUTPUT_ID = "vega-n1";

function props() {
  return {
    setSendCodeCallback: jest.fn(),
    setOutputCallback: jest.fn(),
    data: { nodeId: "n1", outputCallback: jest.fn() },
    output: { code: "", content: "" },
    nodeType: "curio.builtin/vis-vega",
    readOnly: false,
    applyGrammar: jest.fn(),
    code: false,
    grammar: true,
    widgets: false,
    provenance: false,
    defaultValue: "{}",
    outputId: OUTPUT_ID,
  };
}

function mount(on: boolean, p = props()) {
  const utils = render(
    <NotebookViewContext.Provider value={{ on, laneX: new Map(), heights: new Map(), reveal: () => on }}>
      <NodeEditor {...p} />
    </NotebookViewContext.Provider>,
  );
  return { ...utils, p };
}

const outputPane = () => document.getElementById(OUTPUT_ID)!.parentElement as HTMLElement;
const panes = (container: HTMLElement) => container.querySelector(".tab-content") as HTMLElement;
const grammarPane = (container: HTMLElement) =>
  Array.from(panes(container).children).find((el) => el !== outputPane()) as HTMLElement;
const outputPill = (container: HTMLElement) => container.querySelector('[data-rr-ui-event-key="output"]');

/** What a run does to the tabs: it hands the code on, and the editor shows the output. */
async function run(p: ReturnType<typeof props>) {
  const sendCode = p.setSendCodeCallback.mock.calls[0][0];
  await act(async () => {
    sendCode("{}");
  });
}

describe("a grammar node shown as a notebook cell", () => {
  test("shows the grammar and the output pane together", () => {
    const { container } = mount(true);
    expect(panes(container)).toHaveClass("curio-notebook-split");
    expect(outputPane()).toHaveClass("curio-notebook-output");
    expect(grammarPane(container)).toHaveClass("active");
  });

  test("has no Output tab to switch to", () => {
    const { container } = mount(true);
    expect(outputPill(container)).toBeNull();
  });

  test("keeps the grammar showing after a run", async () => {
    const { container, p } = mount(true);
    await run(p);
    expect(grammarPane(container)).toHaveClass("active");
    expect(outputPane()).toHaveClass("curio-notebook-output");
  });
});

describe("the same node on the canvas", () => {
  test("keeps its tabs: one pane at a time, and an Output tab", () => {
    const { container } = mount(false);
    expect(panes(container)).not.toHaveClass("curio-notebook-split");
    expect(outputPane()).not.toHaveClass("curio-notebook-output");
    expect(outputPill(container)).not.toBeNull();
  });

  test("switches to the output after a run", async () => {
    const { p } = mount(false);
    await run(p);
    expect(outputPane()).toHaveClass("active");
  });
});
