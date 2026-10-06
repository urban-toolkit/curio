/**
 * A cell added from the notebook view's (+) reads the output of the cell above
 * it (utils/notebookAddCell): the new node's first input takes that cell's
 * output, when both ends exist and their kinds connect; otherwise it is added
 * with no connection.
 */
import { addedCellConnection, type CellEnd } from "../../utils/notebookAddCell";

const loader: CellEnd = {
  id: "load",
  nodeType: "curio.builtin/data-loading",
  handles: [{ id: "out", type: "source" }],
};
const transform: CellEnd = {
  id: "new",
  nodeType: "curio.builtin/data-transformation",
  handles: [{ id: "in", type: "target" }, { id: "out", type: "source" }],
};
const always = () => true;

describe("the connection of a cell added below another", () => {
  test("takes the cell above's output into the new node's first input", () => {
    expect(addedCellConnection(loader, transform, always)).toEqual({
      source: "load", sourceHandle: "out", target: "new", targetHandle: "in",
    });
  });

  test("asks whether the two kinds connect, output kind first", () => {
    const seen: string[][] = [];
    addedCellConnection(loader, transform, (out, inn) => {
      seen.push([out, inn]);
      return true;
    });
    expect(seen).toEqual([["curio.builtin/data-loading", "curio.builtin/data-transformation"]]);
  });

  test("is none when the kinds do not connect", () => {
    expect(addedCellConnection(loader, transform, () => false)).toBeNull();
  });

  test("is none when the cell above has no output or the new node no input", () => {
    const exporter: CellEnd = { id: "exp", nodeType: "curio.builtin/data-export", handles: [{ id: "in", type: "target" }] };
    const source: CellEnd = { id: "src", nodeType: "curio.builtin/data-loading", handles: [{ id: "out", type: "source" }] };
    expect(addedCellConnection(exporter, transform, always)).toBeNull();
    expect(addedCellConnection(loader, source, always)).toBeNull();
  });

  test("never uses an interaction dot", () => {
    const chart: CellEnd = {
      id: "chart",
      nodeType: "curio.builtin/vis-vega",
      handles: [{ id: "in/out", type: "source" }, { id: "in/out", type: "target" }],
    };
    expect(addedCellConnection(chart, chart, always)).toBeNull();
  });
});
