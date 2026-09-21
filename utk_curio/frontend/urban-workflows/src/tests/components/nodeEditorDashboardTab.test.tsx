/**
 * Which pane a dashboard tile shows.
 *
 * On the dashboard a tile shows its output, not its editor, so the output pane
 * is forced. But only a node that HAS one: a code node's result is the text box
 * under its editor, in the code pane. Forcing a pane that does not exist left a
 * pinned code node as an empty tile with nothing reachable on it, which was
 * already true of the old canvas mode and became visible once the dashboard was
 * a page of its own.
 */
import React from "react";
import { render } from "@testing-library/react";

let mockDashboardOn = false;

jest.mock("../../providers/FlowProvider", () => ({
  useFlowContext: () => ({ dashboardOn: mockDashboardOn }),
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
});

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
