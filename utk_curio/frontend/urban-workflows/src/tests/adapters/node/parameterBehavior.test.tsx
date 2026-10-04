/**
 * The Parameter node (#662): one widget, shared by every node whose code names
 * it as `[!! @name !!]`. Its body declares the widget, sets its value, lists
 * the nodes that use it, and on a rename rewrites their references.
 */
import React from "react";
import { act, fireEvent, render, screen } from "@testing-library/react";
import type { NodeBehaviorData, UseNodeStateReturn } from "../../../registry/types";
import type { WidgetDef } from "../../../utils/widgets/widgetModel";
import { noteCodeEdit } from "../../../utils/references/codeEdits";

let mockNodes: any[] = [];
const mockUpdateDataNode = jest.fn();
const mockMarkNodeStale = jest.fn();
const mockMarkDirty = jest.fn();
jest.mock("../../../providers/FlowProvider", () => ({
  useFlowContext: () => ({
    nodes: mockNodes,
    updateDataNode: mockUpdateDataNode,
    markNodeStale: mockMarkNodeStale,
    markDirty: mockMarkDirty,
    dashboardOn: false,
  }),
}));

jest.mock("../../../utils/palettePackageFactoryDraft", () => ({
  resolveNodeDisplayLabel: (data: any) => data.title ?? data.nodeId,
}));

import { useParameterBehavior } from "../../../adapters/node/parameterBehavior";

const PARAM = "curio.builtin/parameter@1";
const CODE = "curio.builtin/computation-analysis@1";

const node = (id: string, nodeType: string, data: Record<string, unknown> = {}) => ({
  id,
  type: "__curioUniversalNode",
  data: { nodeId: id, nodeType, ...data },
});

function Harness({ data }: { data: any }) {
  const behavior = useParameterBehavior(data as NodeBehaviorData, {} as UseNodeStateReturn);
  return <>{behavior.contentComponent}</>;
}

const factor: WidgetDef = { name: "factor", type: "number", label: "Factor", default: 2 };

beforeEach(() => {
  mockUpdateDataNode.mockReset();
  mockMarkNodeStale.mockReset();
  mockMarkDirty.mockReset();
});

describe("a new Parameter node", () => {
  test("asks for its widget, and saves it as the node's one widget", () => {
    const self = node("p1", PARAM);
    mockNodes = [self];
    render(<Harness data={self.data} />);
    fireEvent.change(screen.getByLabelText("Widget name"), { target: { value: "rate" } });
    fireEvent.click(screen.getByRole("button", { name: "Add parameter" }));
    expect(mockUpdateDataNode).toHaveBeenCalledWith(
      "p1",
      expect.objectContaining({ widgets: [{ name: "rate", type: "number", default: 0 }] }),
    );
  });

  test("cannot take the name of another Parameter node", () => {
    const self = node("p1", PARAM);
    mockNodes = [self, node("p2", PARAM, { widgets: [factor] })];
    render(<Harness data={self.data} />);
    fireEvent.change(screen.getByLabelText("Widget name"), { target: { value: "factor" } });
    expect(screen.getByText("Another Parameter node is named factor.")).toBeTruthy();
    expect((screen.getByRole("button", { name: "Add parameter" }) as HTMLButtonElement).disabled).toBe(true);
  });
});

describe("a Parameter node with its widget", () => {
  const users = () => [
    node("a", CODE, { title: "Shadows A", code: "h = [!! @factor !!] * height" }),
    node("b", CODE, { title: "Shadows B", code: "s = f'{[!! @factor !!]}'" }),
    node("c", CODE, { title: "Own widget", code: "h = [!! factor !!]", widgets: [factor] }),
  ];

  test("shows its tag, and lists the nodes whose code names it", () => {
    const self = node("p1", PARAM, { widgets: [factor] });
    mockNodes = [self, ...users()];
    const view = render(<Harness data={self.data} />);
    expect(view.container.querySelector('[data-shared-tag="factor"]')?.textContent).toBe("@factor");
    const listed = Array.from(view.container.querySelectorAll("[data-parameter-user]")).map((li) => li.textContent);
    expect(listed).toEqual(["Shadows A", "Shadows B"]);
  });

  test("lists a node as soon as its code names it", () => {
    const self = node("p1", PARAM, { widgets: [factor] });
    const later = node("d", CODE, { title: "Later", code: "x = 1" });
    mockNodes = [self, later];
    const view = render(<Harness data={self.data} />);
    expect(view.container.querySelectorAll("[data-parameter-user]")).toHaveLength(0);
    // A code edit reaches node data by direct mutation, as useNodeState writes it.
    (later.data as any).code = "x = [!! @factor !!]";
    act(() => noteCodeEdit());
    expect(Array.from(view.container.querySelectorAll("[data-parameter-user]")).map((li) => li.textContent)).toEqual([
      "Later",
    ]);
  });

  test("a new value reaches the node and marks the nodes that use it stale", () => {
    const self = node("p1", PARAM, { widgets: [factor] });
    mockNodes = [self, ...users()];
    render(<Harness data={self.data} />);
    const control = screen.getByLabelText("Factor", { selector: "input" });
    fireEvent.change(control, { target: { value: "5" } });
    fireEvent.blur(control);
    expect(mockUpdateDataNode).toHaveBeenCalledWith(
      "p1",
      expect.objectContaining({ widgets: [{ ...factor, value: 5 }] }),
    );
    expect(mockMarkNodeStale.mock.calls.map((c) => c[0]).sort()).toEqual(["a", "b"]);
  });

  test("a rename rewrites the references in every node that uses it, and nowhere else", () => {
    const self = node("p1", PARAM, { widgets: [{ ...factor, value: 3 }] });
    mockNodes = [self, ...users()];
    render(<Harness data={self.data} />);
    fireEvent.click(screen.getByRole("button", { name: "Edit parameter factor" }));
    fireEvent.change(screen.getByLabelText("Widget name"), { target: { value: "height_factor" } });
    fireEvent.click(screen.getByRole("button", { name: "Save parameter" }));

    const written = new Map(mockUpdateDataNode.mock.calls.map(([id, data]) => [id, data]));
    expect(written.get("a")).toEqual(
      expect.objectContaining({ code: "h = [!! @height_factor !!] * height", defaultCode: "h = [!! @height_factor !!] * height" }),
    );
    expect(written.get("b")).toEqual(
      expect.objectContaining({ code: "s = f'{[!! @height_factor !!]}'" }),
    );
    expect(written.has("c")).toBe(false);
    // The set value survives the rename.
    expect(written.get("p1")).toEqual(
      expect.objectContaining({ widgets: [{ ...factor, name: "height_factor", value: 3 }] }),
    );
    expect(mockMarkNodeStale.mock.calls.map((c) => c[0]).sort()).toEqual(["a", "b"]);
  });
});
