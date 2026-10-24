/**
 * The check of an area a Map Editor gesture makes (`utils/editFeatures/areaCheck`),
 * on the cases `areaCheck.cases.json` holds: autk-db refuses a shape that
 * GEOS's ST_IsValid refuses once the map's grid has rounded it, and with it
 * the whole layer (#1112). Each case's problem is the one `areaProblem` finds,
 * null for a shape GEOS accepts; the words the map's tip says for each.
 */
import shared from "../../utils/editFeatures/areaCheck.cases.json";
import {
  areaProblem,
  drawnRefusal,
  layerFormat,
  reshapeRefusal,
  shapeProblem,
  type AreaProblem,
} from "../../utils/editFeatures/areaCheck";
import type { Geometry } from "../../utils/editFeatures/editFeatures";

type AreaCase = { name: string; geometry: Geometry; coordinateFormat?: string; problem: AreaProblem | null; unrounded?: AreaProblem | null };

const cases = shared.cases as unknown as AreaCase[];

describe("an area as autk-db would get it", () => {
  test.each(cases.map((c) => [c.name, c] as const))("%s", (_name, c) => {
    expect(areaProblem(c.geometry, c.coordinateFormat)).toBe(c.problem);
  });

  test.each(cases.filter((c) => "unrounded" in c).map((c) => [c.name, c] as const))("before the map's grid, %s", (_name, c) => {
    expect(shapeProblem(c.geometry)).toBe(c.unrounded);
  });

  test("the cases hold a shape with each problem, shapes GEOS accepts, and one the map's grid makes refused", () => {
    const problems = cases.map((c) => c.problem);
    for (const problem of ["crosses", "flat", "hole", "overlap", null]) expect(problems).toContain(problem);
    expect(cases.some((c) => c.unrounded === null && c.problem !== null)).toBe(true);
  });

  test("lines and points are not checked", () => {
    expect(areaProblem({ type: "LineString", coordinates: [[0, 0], [2, 2], [2, 0], [0, 2]] })).toBeNull();
    expect(areaProblem({ type: "MultiLineString", coordinates: [[[0, 0], [2, 2]], [[2, 0], [0, 2]]] })).toBeNull();
    expect(areaProblem({ type: "MultiPoint", coordinates: [[0, 0], [0, 0]] })).toBeNull();
    expect(areaProblem({ type: "Point", coordinates: [0, 0] })).toBeNull();
  });
});

describe("the words the map's tip says for a refusal", () => {
  test.each([
    ["crosses", "That would make the outline cross itself, so the corner went back.", "That outline crosses itself, so the area was not added."],
    ["flat", "That would leave the outline with no area, so the corner went back.", "That outline has no area, so the area was not added."],
    ["hole", "That would make a hole cross or leave its outline, so the corner went back.", "A hole crosses or leaves its outline, so the area was not added."],
    ["overlap", "That would make two of its parts overlap, so the corner went back.", "It overlaps another part, so the area was not added."],
  ] as const)("%s: a corner dragged, and an area drawn", (problem, dragged, drawn) => {
    expect(reshapeRefusal(problem)).toBe(dragged);
    expect(reshapeRefusal(problem, "drag")).toBe(dragged);
    expect(drawnRefusal(problem, "area")).toBe(drawn);
  });

  test("a corner deleted, a shape moved, a part taken away, and a part drawn", () => {
    expect(reshapeRefusal("crosses", "delete")).toBe("That would make the outline cross itself, so the corner stayed.");
    expect(reshapeRefusal("crosses", "move")).toBe("That would make the outline cross itself, so it went back.");
    expect(reshapeRefusal("overlap", "remove")).toBe("That would make two of its parts overlap, so the part stayed.");
    expect(drawnRefusal("overlap", "part")).toBe("It overlaps another part, so the part was not added.");
  });
});

describe("the coordinate format a layer is handed to autk-db in", () => {
  const inMetres: Geometry = { type: "Polygon", coordinates: [[[-9755000, 5140000], [-9754990, 5140000], [-9754990, 5140010], [-9755000, 5140000]]] };

  test("is read from the layer's features, or from the shape while the layer has none", () => {
    const inDegrees = { features: [{ type: "Feature", properties: {}, geometry: { type: "Point", coordinates: [-87.6, 41.88] } }] };
    expect(layerFormat(inDegrees, inMetres)).toBe("EPSG:4326");
    expect(layerFormat({ features: [] }, inMetres)).toBe("EPSG:3395");
    expect(layerFormat(undefined, inMetres)).toBe("EPSG:3395");
  });

  test("is the one a layer names", () => {
    const named = { features: [], crs: { type: "name", properties: { name: "urn:ogc:def:crs:EPSG::4326" } } };
    expect(layerFormat(named, inMetres)).toBe("EPSG:4326");
  });
});
