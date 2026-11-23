/**
 * Selecting the nodes linked to a dataset or a model (utils/focusDatasetNodes)
 * frames them on the canvas, and in the notebook view scrolls to their cell
 * instead: there the canvas fit has nothing to move.
 */
jest.mock("../../utils/fitViewWithMenuOffset", () => ({ fitViewWithMenuOffset: jest.fn(() => true) }));

import { focusLinkedNodes } from "../../utils/focusDatasetNodes";
import { fitViewWithMenuOffset } from "../../utils/fitViewWithMenuOffset";

const fit = fitViewWithMenuOffset as jest.Mock;

function flow() {
  const nodes = [
    { id: "a", data: { linked: true } },
    { id: "b", data: { linked: false } },
  ];
  return {
    getNodes: () => nodes,
    setNodes: jest.fn(),
  } as any;
}

/** React Flow's store, whose own selection takes the linked nodes by id. */
function store() {
  const addSelectedNodes = jest.fn();
  return { addSelectedNodes, getState: () => ({ getNodes: () => [], addSelectedNodes }) };
}

const isLinked = (n: { data: any }) => n.data.linked === true;

beforeEach(() => fit.mockClear());

test("on the canvas the linked nodes are framed", () => {
  const reveal = jest.fn(() => false);
  const selection = store();
  const canvas = flow();
  expect(focusLinkedNodes(canvas, selection, isLinked, reveal)).toBe(1);
  expect(reveal).toHaveBeenCalledWith(["a"]);
  expect(fit).toHaveBeenCalledTimes(1);
  // Selected by id, through React Flow's own selection: the node list itself
  // is never handed back.
  expect(selection.addSelectedNodes).toHaveBeenCalledWith(["a"]);
  expect(canvas.setNodes).not.toHaveBeenCalled();
});

test("in the notebook view the first linked cell is scrolled to, and nothing is framed", () => {
  const reveal = jest.fn(() => true);
  const selection = store();
  expect(focusLinkedNodes(flow(), selection, isLinked, reveal)).toBe(1);
  expect(reveal).toHaveBeenCalledWith(["a"]);
  expect(fit).not.toHaveBeenCalled();
  expect(selection.addSelectedNodes).toHaveBeenCalledWith(["a"]);
});

test("without a reveal it frames, as before", () => {
  expect(focusLinkedNodes(flow(), store(), isLinked)).toBe(1);
  expect(fit).toHaveBeenCalledTimes(1);
});

test("with no linked node nothing is selected and nothing is framed", () => {
  const selection = store();
  expect(focusLinkedNodes(flow(), selection, () => false)).toBe(0);
  expect(selection.addSelectedNodes).not.toHaveBeenCalled();
  expect(fit).not.toHaveBeenCalled();
});
