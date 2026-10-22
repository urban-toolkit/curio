import { fromParts, partsOf, withPart, withoutPart } from "../../utils/editFeatures/geometryParts";

const square = (x: number) => ({ type: "Polygon", coordinates: [[[x, 0], [x + 1, 0], [x + 1, 1], [x, 0]]] }) as any;
const line = (x: number) => ({ type: "LineString", coordinates: [[x, 0], [x, 1]] }) as any;

describe("a feature's parts", () => {
  it("are one part for a single geometry and each member of a Multi one", () => {
    expect(partsOf(square(0))).toEqual([square(0)]);
    expect(partsOf({ type: "MultiPolygon", coordinates: [square(0).coordinates, square(2).coordinates] } as any)).toEqual([square(0), square(2)]);
    expect(partsOf(null)).toEqual([]);
  });

  it("join into the Multi kind of theirs, and one part stays single", () => {
    expect(fromParts([line(0)])).toEqual(line(0));
    expect(fromParts([line(0), line(2)])).toEqual({ type: "MultiLineString", coordinates: [line(0).coordinates, line(2).coordinates] });
    expect(fromParts([line(0), square(2)])).toBeNull();
  });

  it("grow by a part of the same kind", () => {
    const two = withPart(square(0), square(2));
    expect(two).toEqual({ type: "MultiPolygon", coordinates: [square(0).coordinates, square(2).coordinates] });
    expect(partsOf(withPart(two, square(4)))).toHaveLength(3);
    expect(withPart(square(0), line(2))).toBeNull();
    expect(withPart({ type: "Point", coordinates: [0, 0] } as any, { type: "Point", coordinates: [1, 1] } as any)).toEqual({
      type: "MultiPoint",
      coordinates: [[0, 0], [1, 1]],
    });
  });

  it("lose a part, back to a single geometry when one is left, never to none", () => {
    const two = withPart(line(0), line(2));
    expect(withoutPart(two, 0)).toEqual(line(2));
    expect(withoutPart(line(0), 0)).toBeNull();
    expect(withoutPart(two, 5)).toBeNull();
  });
});
