/**
 * A node's Delete node tool, among its header's tools and on an icon-only
 * node's chip, follows the rule the canvas's Delete key follows
 * (`graphEditGates`): nodes are deleted on the canvas, by whoever edits it. A
 * notebook cell has none, since the notebook view changes no graph, and nor does
 * a node on a read-only canvas, where the Delete key does nothing either.
 */
import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";

const mockFlow: { viewerMode: "owner" | "shared" } = { viewerMode: "owner" };
const mockCollab = { enabled: false };

jest.mock("../../providers/FlowProvider", () => ({
  useFlowContext: () => mockFlow,
}));
jest.mock("../../providers/CollaborationProvider", () => ({
  useCollab: () => mockCollab,
}));

import { NodeDeleteTool } from "../../components/nodes/NodeDeleteTool";
import { NotebookViewContext } from "../../providers/flow/notebookViewContext";

/** The tool as a node draws it, in the notebook view or on the canvas. */
function draw(notebookOn: boolean) {
  const onDelete = jest.fn();
  render(
    <NotebookViewContext.Provider value={{ on: notebookOn, laneX: new Map(), cellWidth: 1065, reveal: () => false }}>
      <NodeDeleteTool onDelete={onDelete} />
    </NotebookViewContext.Provider>,
  );
  return onDelete;
}

const tool = () => screen.queryByRole("button", { name: "Delete node" });

afterEach(() => {
  mockFlow.viewerMode = "owner";
  mockCollab.enabled = false;
});

describe("a node's Delete node tool", () => {
  test("on the owner's canvas, it is there and a press deletes the node", () => {
    const onDelete = draw(false);
    const button = tool();
    expect(button).not.toBeNull();
    // HeaderIconButton acts on the pointer pair, so a press without a drag.
    fireEvent.pointerDown(button as HTMLElement, { clientX: 0, clientY: 0 });
    fireEvent.pointerUp(button as HTMLElement, { clientX: 0, clientY: 0 });
    expect(onDelete).toHaveBeenCalledTimes(1);
  });

  test("in the notebook view, a cell has none: cells are deleted on the canvas", () => {
    draw(true);
    expect(tool()).toBeNull();
  });

  test("on a read-only canvas, a node has none", () => {
    mockFlow.viewerMode = "shared";
    draw(false);
    expect(tool()).toBeNull();
  });

  test("with collaboration on, another user's dataflow is edited on the canvas, so the tool is there", () => {
    mockFlow.viewerMode = "shared";
    mockCollab.enabled = true;
    draw(false);
    expect(tool()).not.toBeNull();
  });
});
