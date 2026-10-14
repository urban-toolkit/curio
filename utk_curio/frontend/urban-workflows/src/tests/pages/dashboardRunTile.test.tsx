/**
 * The dashboard's Run button: Run All with the values the tiles show, and Stop
 * while a run goes, as the canvas rail's button does.
 */
import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";

let mockFlow: any = {};
jest.mock("../../providers/FlowProvider", () => ({
  useFlowContext: () => mockFlow,
}));
jest.mock("reactflow", () => ({ useViewport: () => ({ x: 0, y: 0, zoom: 1 }) }));

import DashboardRunTile from "../../pages/dashboard/DashboardRunTile";

const props = (movable: boolean) => ({
  place: { x: 20, y: 30, width: 56, height: 44 },
  movable,
  onPreview: jest.fn(),
  onCommit: jest.fn(),
});

function renderTile(movable = false) {
  return render(<DashboardRunTile {...props(movable)} />);
}

beforeEach(() => {
  mockFlow = {
    playAllNodes: jest.fn(),
    cancelRun: jest.fn(),
    isRunActive: false,
    serverRunActive: false,
  };
});

test("Run runs the dataflow", () => {
  renderTile();
  const button = screen.getByTestId("dashboard-run-btn");
  expect(button.getAttribute("aria-label")).toBe("Run");
  fireEvent.click(button);
  expect(mockFlow.playAllNodes).toHaveBeenCalledTimes(1);
  expect(mockFlow.cancelRun).not.toHaveBeenCalled();
});

test.each([
  ["in the browser", { isRunActive: true }],
  ["on the server", { serverRunActive: true }],
])("while a run goes %s it is Stop, which cancels it", (_where, state) => {
  Object.assign(mockFlow, state);
  renderTile();
  const button = screen.getByTestId("dashboard-run-btn");
  expect(button.getAttribute("aria-label")).toBe("Cancel run");
  expect(button.getAttribute("data-run-active")).toBe("true");
  fireEvent.click(button);
  expect(mockFlow.cancelRun).toHaveBeenCalledTimes(1);
  expect(mockFlow.playAllNodes).not.toHaveBeenCalled();
});

test("has a resize corner only while the layout is edited, and no grip", () => {
  const { rerender } = renderTile(false);
  expect(screen.getByTestId("dashboard-run-tile").getAttribute("data-editing")).toBeNull();
  expect(screen.queryByTestId("dashboard-run-resize")).toBeNull();

  rerender(<DashboardRunTile {...props(true)} />);
  expect(screen.getByTestId("dashboard-run-tile").getAttribute("data-editing")).toBe("true");
  expect(screen.queryByTestId("dashboard-run-resize")).not.toBeNull();
  expect(screen.queryByTestId("dashboard-run-grip")).toBeNull();
});

test("is sized as its place says, at the zoom", () => {
  renderTile();
  const tile = screen.getByTestId("dashboard-run-tile");
  expect(tile.style.width).toBe("56px");
  expect(tile.style.height).toBe("44px");
});

test("while editing, a click that does not move it still runs", () => {
  const p = props(true);
  render(<DashboardRunTile {...p} />);
  const button = screen.getByTestId("dashboard-run-btn");
  fireEvent.pointerDown(button, { button: 0, clientX: 5, clientY: 5, pointerId: 1 });
  fireEvent.pointerUp(button, { button: 0, clientX: 6, clientY: 5, pointerId: 1 });
  fireEvent.click(button);
  expect(p.onCommit).not.toHaveBeenCalled();
  expect(mockFlow.playAllNodes).toHaveBeenCalledTimes(1);
});

test("while editing, dragging the card moves it, and the drag does not run", () => {
  const p = props(true);
  render(<DashboardRunTile {...p} />);
  const button = screen.getByTestId("dashboard-run-btn");
  fireEvent.pointerDown(button, { button: 0, clientX: 5, clientY: 5, pointerId: 1 });
  fireEvent.pointerMove(button, { button: 0, clientX: 45, clientY: 25, pointerId: 1 });
  fireEvent.pointerUp(button, { button: 0, clientX: 45, clientY: 25, pointerId: 1 });
  fireEvent.click(button);
  expect(p.onCommit).toHaveBeenCalledWith({ x: 60, y: 50, width: 56, height: 44 });
  expect(mockFlow.playAllNodes).not.toHaveBeenCalled();
});

test("its corner resizes it, never below the smallest size", () => {
  const p = props(true);
  render(<DashboardRunTile {...p} />);
  const corner = screen.getByTestId("dashboard-run-resize");
  fireEvent.pointerDown(corner, { button: 0, clientX: 0, clientY: 0, pointerId: 1 });
  fireEvent.pointerMove(corner, { button: 0, clientX: 44, clientY: 16, pointerId: 1 });
  expect(p.onPreview).toHaveBeenLastCalledWith({ x: 20, y: 30, width: 100, height: 60 });
  fireEvent.pointerMove(corner, { button: 0, clientX: -200, clientY: -200, pointerId: 1 });
  fireEvent.pointerUp(corner, { button: 0, clientX: -200, clientY: -200, pointerId: 1 });
  expect(p.onCommit).toHaveBeenCalledWith({ x: 20, y: 30, width: 36, height: 32 });
});

test("when the layout is locked, a press never moves it", () => {
  const p = props(false);
  render(<DashboardRunTile {...p} />);
  const button = screen.getByTestId("dashboard-run-btn");
  fireEvent.pointerDown(button, { button: 0, clientX: 5, clientY: 5, pointerId: 1 });
  fireEvent.pointerMove(button, { button: 0, clientX: 80, clientY: 80, pointerId: 1 });
  fireEvent.pointerUp(button, { button: 0, clientX: 80, clientY: 80, pointerId: 1 });
  expect(p.onPreview).not.toHaveBeenCalled();
  expect(p.onCommit).not.toHaveBeenCalled();
});
