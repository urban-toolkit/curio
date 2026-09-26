/**
 * Choosing a starter Autark document from the input: the counterpart of the
 * Vega-Lite ladder, offered the same way (hook/useStarterSpec).
 */
import {
  AUTK_STARTER_RULES,
  autkStarterText,
  chooseAutkStarter,
  starterLayer,
} from "../../utils/autkDefaultSpec";
import type { GrammarFrame } from "../../utils/grammarInput";

const point = { type: "Point", coordinates: [0, 0] };
const frame = (over: Partial<GrammarFrame>): GrammarFrame => ({
  name: null,
  dataType: "geodataframe",
  payload: { type: "FeatureCollection", features: [{ type: "Feature", geometry: point, properties: {} }] },
  schema: null,
  geometryName: "geometry",
  crsName: null,
  fromBundle: false,
  index: 0,
  ...over,
});
const geo = (properties: Record<string, unknown>, schema: Record<string, string> | null = null) =>
  frame({
    payload: { type: "FeatureCollection", features: [{ type: "Feature", geometry: point, properties }] },
    schema,
  });
const doc = (text: string | null) => (text ? JSON.parse(text) : null);

describe("AUTK_STARTER_RULES", () => {
  test("the ids and their order match the table in docs/USAGE.md", () => {
    // First match wins, so the order *is* the behaviour. If you add or reorder
    // a rule, update the Autark starter table in docs/USAGE.md to match.
    expect(AUTK_STARTER_RULES.map((r) => r.id)).toEqual([
      "layers",
      "geometry+quantitative",
      "geometry+nominal",
      "geometry",
    ]);
  });
});

describe("autkStarterText", () => {
  test("a layer with a number is coloured by it, explicitly", () => {
    const text = autkStarterText({ frames: [geo({ zone: "n", pop: 3 }, { zone: "str", pop: "int64", geometry: "geometry" })] });
    expect(doc(text)).toEqual({
      map: { layerRefs: [{ dataRef: "upstream", getFnv: "pop", getFnvType: "quantitative", colorMapInterpolator: "interpolateViridis" }] },
    });
  });

  test("a layer with only categories is coloured by the first", () => {
    const text = autkStarterText({ frames: [geo({ zone: "n" }, { zone: "str" })] });
    expect(doc(text).map.layerRefs[0]).toEqual({
      dataRef: "upstream", getFnv: "zone", getFnvType: "categorical", colorMapInterpolator: "schemeTableau10",
    });
  });

  test("geometry alone is a plain layer", () => {
    expect(doc(autkStarterText({ frames: [geo({})] }))).toEqual({ map: { layerRefs: [{ dataRef: "upstream" }] } });
  });

  test("several layers are drawn together, each under its own name", () => {
    const text = autkStarterText({
      frames: [
        frame({ name: "table_osm_roads", fromBundle: true, index: 0 }),
        frame({ fromBundle: true, index: 1 }),
      ],
    });
    expect(doc(text)).toEqual({ map: { layerRefs: [{ dataRef: "table_osm_roads" }, { dataRef: "upstream_1" }] } });
  });

  test("a layer named by its source keeps that name", () => {
    expect(doc(autkStarterText({ frames: [frame({ name: "census" })] })).map.layerRefs[0].dataRef).toBe("census");
  });

  test("a DataFrame with a geometry column is a layer; one without is nothing", () => {
    const withGeometry = frame({
      dataType: "dataframe", geometryName: null, payload: { where: [point], pop: [3] }, schema: { where: "str", pop: "int64" },
    });
    expect(doc(autkStarterText({ frames: [withGeometry] })).map.layerRefs[0]).toMatchObject({ getFnv: "pop" });

    const without = frame({ dataType: "dataframe", geometryName: null, payload: { pop: [3] } });
    expect(autkStarterText({ frames: [without] })).toBeNull();
  });

  test("empty layers and layers with no geometry are not offered", () => {
    const empty = frame({ payload: { type: "FeatureCollection", features: [] }, fromBundle: true, index: 0 });
    const nullGeometry = frame({
      payload: { type: "FeatureCollection", features: [{ type: "Feature", geometry: null, properties: {} }] },
      fromBundle: true, index: 1,
    });
    expect(starterLayer(empty)).toBeNull();
    expect(starterLayer(nullGeometry)).toBeNull();
    expect(autkStarterText({ frames: [empty, nullGeometry] })).toBeNull();
  });

  test("nothing drawable leaves the editor empty", () => {
    expect(chooseAutkStarter([])).toBeNull();
    expect(autkStarterText({ frames: [] })).toBeNull();
  });
});
