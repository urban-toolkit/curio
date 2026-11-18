/**
 * An Autark node tells its tables apart by key, as autk-grammar 5.0.0 does
 * (`tableKey`): a table's name in the default workspace, `<workspace>/<name>`
 * in another. Two workspaces can hold tables of one name, and a map, a plot or
 * a compute pass reads the tables of its own workspace.
 */
jest.mock("../../services/api", () => ({ fetchData: jest.fn(), fetchPreviewData: jest.fn() }));
jest.mock("@urban-toolkit/autk-db", () => ({ DEFAULT_WORKSPACE_NAME: "autk" }), { virtual: true });

import * as dataCompile from "../../adapters/node/autkDataCompile";
import * as autkInput from "../../utils/autkInput";
import { autkStarterText } from "../../utils/autkDefaultSpec";
import { framesFromPayload } from "../../utils/grammarInput";

const { autkSourcesFrom, documentTableRefs, ownTableNames, selectFieldsProblem, tablesToLoad } = autkInput;

const line = (x: number, properties: Record<string, unknown> = {}) => ({
  type: "Feature",
  geometry: { type: "LineString", coordinates: [[x, 41.88], [x + 0.001, 41.881]] },
  properties: { x, ...properties },
});
const lines = (...xs: number[]) => ({ type: "FeatureCollection", features: xs.map((x) => line(x)) });

/** An upstream Autark node's layer array: `lines` in the default workspace and in `east`. */
const BOTH = [
  { name: "lines", type: "polylines", geojson: lines(-87.6) },
  { name: "lines", type: "polylines", geojson: lines(-87.5, -87.49), workspace: "east" },
];

describe("autk-grammar's tableKey, written out", () => {
  test("is the grammar's own rule", () => {
    const { tableKey } = require("@urban-toolkit/autk-grammar/data");
    for (const workspace of [undefined, "autk", "east", "west"]) {
      expect(dataCompile.autkTableKey(workspace, "lines")).toBe(tableKey(workspace, "lines"));
    }
  });

  test("reads a workspace written as a name, and nothing else, as another workspace", () => {
    expect([{ workspace: "east" }, { workspace: "autk" }, { workspace: "" }, { workspace: null }, {}, null]
      .map((entry) => dataCompile.autkWorkspaceOf(entry))).toEqual(["east", undefined, undefined, undefined, undefined, undefined]);
  });

  test("tells a document that keeps tables in another workspace by any source, pass, map or plot", () => {
    const uses = dataCompile.autkUsesWorkspaces;
    expect(uses({ data: [{ type: "csv", outputTableName: "a", workspace: "east" }] })).toBe(true);
    expect(uses({ compute: [{ dataRef: "a" }, { dataRef: "a", workspace: "east" }] })).toBe(true);
    expect(uses({ map: { workspace: "east", layerRefs: [] } })).toBe(true);
    expect(uses({ plot: [{ workspace: "east", dataRef: "a" }] })).toBe(true);
    expect(uses({ data: [{ type: "csv", outputTableName: "a", workspace: "autk" }], map: { layerRefs: [] } })).toBe(false);
    expect(uses({})).toBe(false);
  });
});

describe("the tables a document reads", () => {
  test("are each in the workspace of the map, plot or pass that names it", () => {
    expect(documentTableRefs({
      map: { workspace: "east", layerRefs: [{ dataRef: "lines" }] },
      plot: { dataRef: "lines", mark: "bar", axis: ["x"] },
      compute: [{
        workspace: "west", dataRef: "zones", attributes: {}, wgslFunction: "return 1.0;", outputColumnName: "y",
        uniforms: { near: { fromFeature: { layer: "lines" } } },
      }],
    })).toEqual(["east/lines", "lines", "west/zones", "west/lines"]);
  });

  test("of its own data section are in their sources' workspaces", () => {
    expect(ownTableNames({
      data: [
        { type: "geojson", outputTableName: "lines", geojsonObject: lines(0) },
        { type: "geojson", outputTableName: "lines", geojsonObject: lines(0), workspace: "east" },
        { type: "osm", outputTableName: "area", autoLoadLayers: { layers: ["roads"] }, workspace: "boston" },
      ],
    })).toEqual(["lines", "east/lines", "boston/area_roads"]);
  });
});

describe("an input that brings a table of one name in two workspaces", () => {
  const read = { frames: framesFromPayload(BOTH).frames };

  test("brings both, each in its workspace, and no clash", () => {
    const prepared = autkSourcesFrom(read, { map: { layerRefs: [{ dataRef: "lines" }] } });
    expect(prepared.sources.map((s) => [s.outputTableName, s.workspace, s.geojsonObject.features.length])).toEqual([
      ["lines", undefined, 1],
      ["lines", "east", 2],
    ]);
    expect(prepared.tables).toEqual(["lines", "east/lines"]);
    expect(prepared.inputProblem).toBeUndefined();
  });

  test("loads for a map only the table of the map's workspace", () => {
    const { sources } = autkSourcesFrom(read, {});
    const east = tablesToLoad(sources, { map: { workspace: "east", layerRefs: [{ dataRef: "lines" }] } });
    expect(east.map((s) => [s.outputTableName, s.workspace])).toEqual([["lines", "east"]]);
    const plain = tablesToLoad(sources, { map: { layerRefs: [{ dataRef: "lines" }] } });
    expect(plain.map((s) => [s.outputTableName, s.workspace])).toEqual([["lines", undefined]]);
  });

  test("names its one layer input_0 in that layer's workspace", () => {
    const one = { frames: framesFromPayload([BOTH[1]]).frames };
    const east = autkSourcesFrom(one, { map: { workspace: "east", layerRefs: [{ dataRef: "input_0" }] } });
    expect(east.sources.map((s) => [s.outputTableName, s.workspace])).toEqual([["input_0", "east"], ["lines", "east"]]);
    const plain = autkSourcesFrom(one, { map: { layerRefs: [{ dataRef: "input_0" }] } });
    expect(plain.sources.map((s) => [s.outputTableName, s.workspace])).toEqual([["lines", "east"]]);
  });
});

describe("an OpenStreetMap load in each of two workspaces", () => {
  const source = (name: string, layerType: string, workspace: string) => ({
    type: "geojson", outputTableName: name, layerType, workspace, geojsonObject: lines(0),
  });
  const tables = [
    source("area_surface", "surface", "boston"),
    source("area_roads", "roads", "boston"),
    source("area_surface", "surface", "chicago"),
    source("area_roads", "roads", "chicago"),
  ];

  test("brings to a map the surface of its own workspace's load, first", () => {
    const loaded = tablesToLoad(tables, { map: { workspace: "chicago", layerRefs: [{ dataRef: "area_roads" }] } });
    expect(loaded.map((s) => `${s.workspace}/${s.outputTableName}`)).toEqual(["chicago/area_surface", "chicago/area_roads"]);
  });
});

describe("selectFields", () => {
  test("are read from the input's table of the view's workspace", () => {
    const { sources } = autkSourcesFrom({ frames: framesFromPayload([
      { name: "lines", type: "polylines", geojson: { type: "FeatureCollection", features: [line(0, { id: 1 })] } },
      { name: "lines", type: "polylines", geojson: lines(1), workspace: "east" },
    ]).frames }, {});
    const pick = (workspace?: string) => ({
      map: { ...(workspace ? { workspace } : {}), layerRefs: [{ dataRef: "lines", isPick: true, selectFields: ["id"] }] },
    });
    expect(selectFieldsProblem(pick(), sources)).toBeNull();
    expect(selectFieldsProblem(pick("east"), sources)).toBe("selectFields names id, which no feature of east/lines has.");
  });
});

describe("a starter document", () => {
  const drawn = (text: string | null) => {
    const { map } = JSON.parse(text!);
    return { workspace: map.workspace, tables: map.layerRefs.map((ref: any) => ref.dataRef) };
  };

  test("draws what arrives from a workspace in that workspace", () => {
    expect(drawn(autkStarterText({ frames: framesFromPayload([BOTH[1]]).frames })))
      .toEqual({ workspace: "east", tables: ["lines"] });
  });

  test("draws the layers of the first layer's workspace", () => {
    expect(drawn(autkStarterText({ frames: framesFromPayload(BOTH).frames })))
      .toEqual({ workspace: undefined, tables: ["lines"] });
  });
});
