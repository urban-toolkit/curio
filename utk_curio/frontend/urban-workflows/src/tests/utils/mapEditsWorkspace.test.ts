/**
 * What a Map Editor node hands on keeps each layer's workspace (autk-grammar
 * 5.0.0's `workspace`) in the browser too: `editedOutput`, which the map it
 * feeds draws from while the node's own run has not answered yet, is the twin
 * of the node's step (`feature_edits.edit_features`), so the map loads each
 * edited layer in the workspace it came from.
 */
jest.mock("../../services/api", () => ({ fetchData: jest.fn(), fetchPreviewData: jest.fn() }));

import { editedOutput } from "../../utils/editFeatures/mapEditsPreview";
import { framesFromPayload } from "../../utils/grammarInput";

const line = (id: number, x: number) => ({
  type: "Feature",
  geometry: { type: "LineString", coordinates: [[x, 41.88], [x + 0.001, 41.881]] },
  properties: { line_id: id },
});

/** An upstream Autark data node's layers: one in the default workspace, one in `east`. */
const RECORDS = [
  { name: "lines", type: "polylines", geojson: { type: "FeatureCollection", features: [line(0, -87.6)] } },
  {
    name: "east_lines", type: "polylines", workspace: "east",
    geojson: { type: "FeatureCollection", features: [line(0, -87.5), line(1, -87.49)] },
  },
];

test("a new layer is made in the workspace every layer of the input shares, else in the default one", () => {
  const inEast = [RECORDS[1], { ...RECORDS[1], name: "more_lines" }];
  const made = (records: any[]) => {
    const out: any = editedOutput({ frames: framesFromPayload(records).frames }, {
      settings: { newLayers: [{ name: "marks", geometry: "Point" }] } as any,
      circles: 1,
    });
    const last = out.data[out.data.length - 1];
    return [last.layerName, last.workspace];
  };
  expect(made(inEast)).toEqual(["marks", "east"]);
  expect(made(RECORDS)).toEqual(["marks", undefined]);
});

test("an edited layer and one it leaves are handed on in their workspaces", () => {
  const read = { frames: framesFromPayload(RECORDS).frames };
  const out: any = editedOutput(read, {
    settings: { edits: [{ op: "remove", ids: [0], layer: "east_lines" }], key: "line_id" } as any,
    circles: 1,
  });
  expect(out.dataType).toBe("outputs");
  expect(out.data.map((envelope: any) => [envelope.layerName, envelope.workspace])).toEqual([
    ["lines", undefined],
    ["east_lines", "east"],
  ]);
  expect(out.data[1].data.features.map((f: any) => f.properties.line_id)).toEqual([1]);
});
