/**
 * What a dashboard tile says while a step above it downloads what it reads on
 * its first use (hook/useGrammarInputState).
 *
 * On a dashboard the node that downloads is often hidden: a visitor sees the
 * tiles below it, which say "Computing..." for the whole download. A viewer's
 * run says how far each download has come as its step's progress
 * (useDashboardRun keeps it by node), and a tile reads the progress of every
 * node its data comes from, however far up, so it can say it on a line under
 * "Computing...". An interaction edge carries a selection, never data, so a
 * node linked to the tile by one alone is not above it.
 */
import { renderHook } from "@testing-library/react";

const mockFlow = jest.fn();
jest.mock("../../providers/FlowProvider", () => ({
  useFlowContext: () => mockFlow(),
}));

import { useGrammarInputState } from "../../hook/useGrammarInputState";

const MESSAGE = "Downloading model.safetensors, a file of the weights of model.curio.sam3: 1.21 of 3.44 GB (35%)";
const OTHER = "Downloading datasets/data.utk.milan-mrt@1/data/milan-mrt.tif: 4.00 of 13.04 MB (30%)";

/** sam3 feeds tracks, which feeds the tile; a map beside it is linked to the
 *  tile by an interaction edge alone; rows feed nothing here. */
const EDGES = [
  { id: "e1", source: "sam3", target: "tracks" },
  { id: "e2", source: "tracks", target: "tile" },
  { id: "e3", source: "map", target: "tile", sourceHandle: "in/out", targetHandle: "in/out" },
];

/** What the hook says of *nodeId* when the steps *downloads* names download. */
function said(nodeId: string, downloads: Record<string, string>, dashboardOn = true) {
  mockFlow.mockReturnValue({
    edges: EDGES, nodeExecStatus: {}, dashboardOn, serverRunActive: true, dashboardDownloads: downloads,
  });
  // The tile's downloads, whatever the types of the code under test name.
  return (renderHook(() => useGrammarInputState(nodeId)).result.current as any).upstreamDownloads;
}

describe("a dashboard tile below a step that downloads", () => {
  test("says how far the download of a step its data comes from has come, however far up", () => {
    expect(said("tile", { sam3: MESSAGE })).toEqual([MESSAGE]);
    expect(said("tracks", { sam3: MESSAGE })).toEqual([MESSAGE]);
  });

  test("says nothing of a node linked to it by an interaction edge alone, nor of one below it", () => {
    expect(said("tile", { map: OTHER, rows: OTHER })).toEqual([]);
    expect(said("sam3", { tracks: OTHER })).toEqual([]);
  });

  test("says each download above it on its own line, and none once they are over", () => {
    expect(said("tile", { sam3: MESSAGE, tracks: OTHER })).toEqual([OTHER, MESSAGE]);
    expect(said("tile", {})).toEqual([]);
  });

  test("on the canvas says none: the node that downloads says it itself", () => {
    expect(said("tile", { sam3: MESSAGE }, false)).toEqual([]);
  });
});
