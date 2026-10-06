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
jest.mock("../../components/editing/CodeEditor", () => ({ __esModule: true, default: () => <div data-testid="code-editor" /> }));

import NodeEditor from "../../components/editing/NodeEditor";
import { NotebookViewContext } from "../../providers/flow/notebookViewContext";

const OUTPUT_ID = "vega-n1";

function props(): Record<string, any> {
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

function mount(on: boolean, p: ReturnType<typeof props> = props()) {
  const utils = render(
    <NotebookViewContext.Provider value={{ on, laneX: new Map(), reveal: () => on }}>
      <NodeEditor {...(p as React.ComponentProps<typeof NodeEditor>)} />
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

  test("puts its tab pills above the input, as a notebook puts a cell's toolbar", () => {
    const { container } = mount(true);
    const nav = container.querySelector(".nav") as HTMLElement;
    expect(nav).not.toBeNull();
    expect(container.querySelector('[data-rr-ui-event-key="grammar"]')).not.toBeNull();
    expect(nav.compareDocumentPosition(panes(container)) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  test("lets the grammar and the output panes take their own height", () => {
    const { container } = mount(true);
    expect(grammarPane(container).style.height).not.toBe("100%");
    expect(outputPane().style.height).not.toBe("100%");
    expect(panes(container).style.height).not.toBe("100%");
  });

  test("draws its chart 320px tall, which Vega needs as a definite height, scrolling inside past it", () => {
    mount(true);
    const mountEl = document.getElementById(OUTPUT_ID)!;
    expect(mountEl.style.height).toBe("320px");
    expect(mountEl.style.overflow).toBe("auto");
  });
});

describe("other nodes shown as notebook cells", () => {
  const contentProps = (nodeType: string) => ({
    ...props(),
    nodeType,
    grammar: nodeType.includes("autk"),
    outputId: undefined,
    contentComponent: <div data-testid="content" />,
  });
  const contentMount = (container: HTMLElement) => container.querySelector(".curio-content-mount") as HTMLElement;

  test("an Autark map or plot is 400px tall, a definite height to draw in", () => {
    const { container } = mount(true, contentProps("curio.builtin/autk-grammar"));
    expect(contentMount(container).style.height).toBe("400px");
  });

  test("a summary takes its own height up to 360px and scrolls inside past it", () => {
    // Data Summary is the one such kind with an editor; the kinds with none
    // (Data Pool, Simple View...) are capped in UniversalNode, by the same rule.
    const { container } = mount(true, contentProps("curio.builtin/data-summary@1"));
    const el = contentMount(container);
    expect(el.style.maxHeight).toBe("360px");
    expect(el.style.overflow).toBe("auto");
    expect(el.style.height).not.toBe("100%");
  });

  test("a Compare Scenarios chart or map gets a definite 400px, as an Autark map does", () => {
    const { container } = mount(true, contentProps("curio.builtin/compare-scenarios"));
    expect(contentMount(container).style.height).toBe("400px");
  });

  test("a package's body, sized for a node, gets a definite height rather than collapsing", () => {
    const { container } = mount(true, contentProps("acme.tools/heatmap@1"));
    expect(contentMount(container).style.height).toBe("360px");
    expect(contentMount(container).style.overflow).toBe("auto");
  });

  test("a code node keeps its Code pill in the page, which the e2e helpers click", () => {
    const { container } = mount(true, {
      ...props(), nodeType: "curio.builtin/computation-analysis", code: true, grammar: false, outputId: undefined,
    });
    expect(container.querySelector('.nav-link[data-rr-ui-event-key="code"]')).not.toBeNull();
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

  test("keeps its pills below the panes, and every pane and mount filling the node", () => {
    const { container } = mount(false);
    const nav = container.querySelector(".nav") as HTMLElement;
    expect(nav.compareDocumentPosition(panes(container)) & Node.DOCUMENT_POSITION_PRECEDING).toBeTruthy();
    expect(panes(container).style.height).toBe("100%");
    expect(outputPane().style.height).toBe("100%");
    expect(document.getElementById(OUTPUT_ID)!.style.height).toBe("100%");
  });

  test("lets a content node fill the node, as before", () => {
    const { container } = mount(false, {
      ...props(), nodeType: "curio.builtin/data-pool", grammar: false, outputId: undefined,
      contentComponent: <div />,
    });
    const el = container.querySelector(".curio-content-mount") as HTMLElement;
    expect(el.style.height).toBe("100%");
    expect(el.style.maxHeight).toBe("");
  });
});
