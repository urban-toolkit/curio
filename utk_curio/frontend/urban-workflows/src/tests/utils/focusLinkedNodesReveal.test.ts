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

const isLinked = (n: { data: any }) => n.data.linked === true;

beforeEach(() => fit.mockClear());

test("on the canvas the linked nodes are framed", () => {
  const reveal = jest.fn(() => false);
  expect(focusLinkedNodes(flow(), isLinked, reveal)).toBe(1);
  expect(reveal).toHaveBeenCalledWith(["a"]);
  expect(fit).toHaveBeenCalledTimes(1);
});

test("in the notebook view the first linked cell is scrolled to, and nothing is framed", () => {
  const reveal = jest.fn(() => true);
  expect(focusLinkedNodes(flow(), isLinked, reveal)).toBe(1);
  expect(reveal).toHaveBeenCalledWith(["a"]);
  expect(fit).not.toHaveBeenCalled();
});

test("without a reveal it frames, as before", () => {
  expect(focusLinkedNodes(flow(), isLinked)).toBe(1);
  expect(fit).toHaveBeenCalledTimes(1);
});
