import { insideOutline, lassoPicks, outlineLength } from "../../utils/editFeatures/lasso";

const square: [number, number][] = [
  [0, 0],
  [10, 0],
  [10, 10],
  [0, 10],
];
const same = (xy: [number, number]): [number, number] => xy;

describe("lasso", () => {
  test("a point inside the outline is inside, one outside is not", () => {
    expect(insideOutline([5, 5], square)).toBe(true);
    expect(insideOutline([15, 5], square)).toBe(false);
  });

  test("picks every feature with a corner inside, of any kind", () => {
    const features = [
      { id: "p", geometry: { type: "Point", coordinates: [2, 2] } },
      { id: "far", geometry: { type: "Point", coordinates: [20, 20] } },
      { id: "line", geometry: { type: "LineString", coordinates: [[-5, 5], [5, 5]] } },
      { id: "area", geometry: { type: "Polygon", coordinates: [[[8, 8], [20, 8], [20, 20], [8, 8]]] } },
      { id: "multi", geometry: { type: "MultiPoint", coordinates: [[30, 30], [1, 9]] } },
      { id: null, geometry: { type: "Point", coordinates: [3, 3] } },
    ] as any[];
    expect(lassoPicks(features, square, same)).toEqual(["p", "line", "area", "multi"]);
  });

  test("goes through the screen projection", () => {
    const features = [{ id: 1, geometry: { type: "Point", coordinates: [100, 100] } }] as any[];
    expect(lassoPicks(features, square, ([x, y]) => [x / 20, y / 20])).toEqual([1]);
  });

  test("an outline under three points picks nothing", () => {
    expect(lassoPicks([{ id: 1, geometry: { type: "Point", coordinates: [0, 0] } }] as any[], [[0, 0], [1, 1]], same)).toEqual([]);
  });

  test("measures the drag", () => {
    expect(outlineLength([[0, 0], [3, 4], [3, 10]])).toBe(11);
  });
});
