/**
 * A shape's corners as rings of points (#662): what the Interaction node's
 * map overlay (`MapEditOverlay`) picks, reshapes and moves, and how to make
 * the shape again from them.
 */
import type { Geometry } from "./editFeatures";

export type XY = [number, number];

/** What a pointer does on the map: pick, draw a shape, reshape one, or move one. */
export type EditMode = "select" | "draw" | "reshape" | "move";

/** A shape's corners as rings of points, and how to make the shape again from them. */
export interface Rings {
  rings: XY[][];
  /** Whether a ring is an area's: closed, at least 3 corners. */
  closed: boolean[];
  rebuild: (rings: XY[][]) => Geometry;
}

/** *geometry*'s corners, rings of an area without their closing corner. */
export function toRings(geometry: Geometry): Rings {
  const c = geometry.coordinates as any;
  const open = (ring: XY[]) => (ring.length > 1 && ring[0][0] === ring[ring.length - 1][0] && ring[0][1] === ring[ring.length - 1][1] ? ring.slice(0, -1) : ring);
  const close = (ring: XY[]) => [...ring, ring[0]];
  switch (geometry.type) {
    case "Point":
      return { rings: [[c as XY]], closed: [false], rebuild: (r) => ({ type: "Point", coordinates: r[0][0] }) };
    case "MultiPoint":
      return { rings: (c as XY[]).map((p) => [p]), closed: c.map(() => false), rebuild: (r) => ({ type: "MultiPoint", coordinates: r.map((ring) => ring[0]) }) };
    case "LineString":
      return { rings: [c as XY[]], closed: [false], rebuild: (r) => ({ type: "LineString", coordinates: r[0] }) };
    case "MultiLineString":
      return { rings: c as XY[][], closed: c.map(() => false), rebuild: (r) => ({ type: "MultiLineString", coordinates: r }) };
    case "Polygon":
      return { rings: (c as XY[][]).map(open), closed: c.map(() => true), rebuild: (r) => ({ type: "Polygon", coordinates: r.map(close) }) };
    case "MultiPolygon": {
      const shape = (c as XY[][][]).map((poly) => poly.length);
      const flat = (c as XY[][][]).flat().map(open);
      return {
        rings: flat,
        closed: flat.map(() => true),
        rebuild: (r) => {
          const out: XY[][][] = [];
          let at = 0;
          for (const n of shape) {
            out.push(r.slice(at, at + n).map(close));
            at += n;
          }
          return { type: "MultiPolygon", coordinates: out };
        },
      };
    }
    default:
      return { rings: [], closed: [], rebuild: () => geometry };
  }
}
