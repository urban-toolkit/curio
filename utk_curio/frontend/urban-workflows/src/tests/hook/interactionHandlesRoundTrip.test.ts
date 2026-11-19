/**
 * A saved interaction edge keeps the handles it names, a view's among them
 * (`in/out@<id>`), from the dataflow to the canvas and back.
 *
 * The canvas makes each edge of a load and of the dataflow's doc through
 * `canvasEdgeFromTrill` (hook/codeNodes.ts): an interaction edge keeps the
 * interaction handles it was saved with, and one saved with none, or with
 * another kind of handle, gets a node's own (`in/out`) at that end.
 * `TrillGenerator` writes the canvas's edges back as the dataflow saves them,
 * and the doc mapping (providers/collab/docMapping.ts) holds each edge whole,
 * so a handle that names a view comes back as it went.
 */
import * as Y from "yjs";
import { canvasEdgeFromTrill } from "../../hook/codeNodes";
import { TrillGenerator } from "../../TrillGenerator";
import { dataflowToDoc, docToDataflow } from "../../providers/collab/docMapping";

/** Interaction edges as a dataflow saves them. */
const SAVED = [
  { id: "view-to-chart", source: "map", target: "chart", type: "Interaction", sourceHandle: "in/out@heights", targetHandle: "in/out" },
  { id: "view-to-view", source: "map", target: "plot", type: "Interaction", sourceHandle: "in/out@heights", targetHandle: "in/out@buildings" },
  { id: "node-to-node", source: "map", target: "pool", type: "Interaction", sourceHandle: "in/out", targetHandle: "in/out" },
  { id: "no-handles", source: "chart", target: "pool", type: "Interaction" },
  { id: "data-handles", source: "plot", target: "pool", type: "Interaction", sourceHandle: "out", targetHandle: "in" },
];

/** What each loaded or saved edge says: its id, its two handles, and its type. */
const handles = (edges: any[]) => edges.map((edge) => [edge.id, edge.sourceHandle, edge.targetHandle, edge.type]);

beforeEach(() => TrillGenerator.reset());

test("the canvas keeps the interaction handles a saved edge names, and a node's own where it names none", () => {
  expect(handles(SAVED.map((edge) => canvasEdgeFromTrill(edge)))).toEqual([
    ["view-to-chart", "in/out@heights", "in/out", "BIDIRECTIONAL_EDGE"],
    ["view-to-view", "in/out@heights", "in/out@buildings", "BIDIRECTIONAL_EDGE"],
    ["node-to-node", "in/out", "in/out", "BIDIRECTIONAL_EDGE"],
    ["no-handles", "in/out", "in/out", "BIDIRECTIONAL_EDGE"],
    ["data-handles", "in/out", "in/out", "BIDIRECTIONAL_EDGE"],
  ]);
});

test("saved again, and held in the dataflow's doc, each edge keeps its handles and its type", () => {
  const loaded = SAVED.map((edge) => canvasEdgeFromTrill(edge));
  const dataflow = TrillGenerator.generateTrill([], loaded, "Linked views").dataflow;
  const kept = [
    ["view-to-chart", "in/out@heights", "in/out", "Interaction"],
    ["view-to-view", "in/out@heights", "in/out@buildings", "Interaction"],
    ["node-to-node", "in/out", "in/out", "Interaction"],
    ["no-handles", "in/out", "in/out", "Interaction"],
    ["data-handles", "in/out", "in/out", "Interaction"],
  ];
  expect(handles(dataflow.edges)).toEqual(kept);

  const doc = new Y.Doc();
  dataflowToDoc(dataflow, doc, "linked-views");
  expect(handles(docToDataflow(doc).edges as any[])).toEqual(kept);
  // A load from the doc makes the same canvas edges as a load from the file.
  expect(handles((docToDataflow(doc).edges as any[]).map((edge) => canvasEdgeFromTrill(edge))))
    .toEqual(handles(loaded));
});
