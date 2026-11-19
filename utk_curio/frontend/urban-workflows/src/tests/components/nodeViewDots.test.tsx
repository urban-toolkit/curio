/**
 * A view's dot on an Autark node (components/nodes/NodeHandles): its hover text
 * names the view, through Curio's one tooltip (`data-tooltip`), and the same
 * words name it for a screen reader; hovering it rings the view's pane, which
 * holds the view's id (`data-view-id`, adapters/node/autkViews `layOutPanes`),
 * and leaving it takes the ring off. The node's own dot is as before. In a
 * notebook cell a view's dot sits under the node's own interaction dot.
 */
import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";

jest.mock("reactflow", () => ({
  Handle: ({ id, position, style, children, className, onMouseEnter, onMouseLeave, ...rest }: any) => (
    <div
      data-testid={`handle-${id}`}
      data-position={position}
      data-left={style?.left === undefined ? "" : String(style.left)}
      data-top={style?.top === undefined ? "" : String(style.top)}
      data-tooltip={rest["data-tooltip"]}
      aria-label={rest["aria-label"]}
      className={className}
      onMouseEnter={onMouseEnter}
      onMouseLeave={onMouseLeave}
    >
      {children}
    </div>
  ),
  Position: { Left: "left", Right: "right", Top: "top", Bottom: "bottom" },
}));

import { NodeHandles } from "../../components/nodes/NodeHandles";
import type { HandleDef } from "../../registry/types";

const HANDLES = [
  { id: "in", type: "target", position: "left" },
  { id: "out", type: "source", position: "right" },
  { id: "in/out", type: "source", position: "top" },
  { id: "in/out@north", type: "source", position: "top", style: { left: "calc(50% + 28px)" }, tooltip: "interaction · north", view: "north" },
  { id: "in/out@heights", type: "source", position: "top", style: { left: "calc(50% + 56px)" }, tooltip: "interaction · heights", view: "heights" },
] as unknown as HandleDef[];

/** The node *nodeId* with its dots and the panes of its views, as React Flow and a run lay them out. */
function renderNode(notebookOn = false) {
  render(
    <div className="react-flow__node" data-id="views">
      <NodeHandles nodeId="views" data={{}} handles={HANDLES} isConnectable notebookOn={notebookOn} edges={[]} nodes={[]} />
      <div data-curio-autk-views="2">
        <div data-curio-autk-pane="map-0" data-view-id="north" data-testid="pane-north" />
        <div data-curio-autk-pane="plot-0" data-view-id="heights" data-testid="pane-heights" />
      </div>
    </div>,
  );
}

const ringed = () => ["north", "heights"].filter((view) => screen.getByTestId(`pane-${view}`).getAttribute("data-curio-ringed") === "true");

test("a view's dot says which view it is, in Curio's tooltip and to a screen reader; the node's own dot is as before", () => {
  renderNode();

  expect(screen.getByTestId("handle-in/out@north")).toHaveAttribute("data-tooltip", "interaction · north");
  expect(screen.getByTestId("handle-in/out@north")).toHaveAttribute("aria-label", "interaction · north");
  expect(screen.getByTestId("handle-in/out@north")).toHaveAttribute("data-left", "calc(50% + 28px)");
  expect(screen.getByTestId("handle-in/out")).not.toHaveAttribute("data-tooltip");
  expect(screen.getByTestId("handle-in/out")).not.toHaveAttribute("aria-label");
  expect(screen.getByTestId("handle-in")).not.toHaveAttribute("data-tooltip");
});

test("hovering a view's dot rings that view's pane alone, and leaving it takes the ring off", () => {
  renderNode();
  expect(ringed()).toEqual([]);

  fireEvent.mouseEnter(screen.getByTestId("handle-in/out@heights"));
  expect(ringed()).toEqual(["heights"]);

  fireEvent.mouseLeave(screen.getByTestId("handle-in/out@heights"));
  expect(ringed()).toEqual([]);

  // The node's own dot rings nothing.
  fireEvent.mouseEnter(screen.getByTestId("handle-in/out"));
  expect(ringed()).toEqual([]);
});

test("in a notebook cell, a view's dot sits under the node's own interaction dot and says which view it is", () => {
  renderNode(true);

  expect(screen.getByTestId("handle-in/out")).toHaveAttribute("data-top", "50%");
  expect(screen.getByTestId("handle-in/out")).toHaveAttribute("data-tooltip", "interaction");
  expect(screen.getByTestId("handle-in/out@north")).toHaveAttribute("data-top", "calc(50% + 22px)");
  expect(screen.getByTestId("handle-in/out@heights")).toHaveAttribute("data-top", "calc(50% + 44px)");
  // On the cell's right edge: none keeps its place along the canvas's top edge.
  expect(screen.getByTestId("handle-in/out@north")).toHaveAttribute("data-left", "");
  expect(screen.getByTestId("handle-in/out@north")).toHaveAttribute("data-tooltip", "interaction · north");
  fireEvent.mouseEnter(screen.getByTestId("handle-in/out@north"));
  expect(ringed()).toEqual(["north"]);
});
