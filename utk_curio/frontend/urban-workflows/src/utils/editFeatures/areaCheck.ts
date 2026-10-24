/**
 * Whether autk-db would load an area a Map Edits gesture makes (#1112).
 *
 * autk-db checks each building it loads with GEOS's `ST_IsValid`, on the
 * coordinates the map hands it, and refuses the whole layer for one shape that
 * fails: the map then draws none of it. So the map's tools refuse such a shape
 * before it is written (`LayerWorkbench`), and the map's tip says why.
 *
 * A shape is checked as autk-db gets it: in its layer's own coordinates,
 * rounded by the map's own grid (`snapSourceToGrid`), each test exact on the
 * numbers GEOS reads. An area is refused for a ring whose sides cross or
 * touch, a ring with no area, a hole that crosses or leaves its outline (or
 * overlaps another hole, or cuts the area in two with the rings it touches),
 * and two parts that overlap. What GEOS accepts passes: neighbouring sides
 * meeting at the corner they share, a corner repeated where it is, a hole
 * touching its outline at one point, parts touching at corners. Lines and
 * points are not checked.
 */
import { detectCoordinateFormat } from "../geoCrs";
import { snapSourceToGrid } from "../geoPrecision";
import type { Geometry } from "./editFeatures";

/**
 * Why an area would be refused: a ring whose sides cross or touch, a ring
 * with no area, a hole that crosses or leaves its outline, two parts that
 * overlap.
 */
export type AreaProblem = "crosses" | "flat" | "hole" | "overlap";

/**
 * What a gesture on the map did to a shape: dragged a corner (or a
 * midpoint's new one), deleted a corner, moved the whole shape, or took a part
 * away.
 */
export type ReshapeGesture = "drag" | "delete" | "move" | "remove";

/** A corner, exactly: its coordinates as whole numbers, each the coordinate times one power of two (`exactly`). */
type Point = readonly [bigint, bigint];
/** A ring's corners in order, without its closing corner or a corner repeated next to itself. */
type Ring = Point[];
/** A part of an area: its outline, then its holes. */
type Part = Ring[];
/** Where a point is from an area: inside it, outside it, or on its boundary. */
type Place = "in" | "out" | "on";
/** How two rings meet: "cross" when sides of theirs cross or run along each other, else the points where they touch. */
type Meeting = "cross" | Point[];

/**
 * Why *geometry*, a shape of a layer whose coordinates are in
 * *coordinateFormat* (autk-db's, as `detectCoordinateFormat` reads it;
 * EPSG:4326 when left out), would be refused once the map hands it to
 * autk-db; null when it would load, or is not an area.
 */
export function areaProblem(geometry: Geometry | null | undefined, coordinateFormat?: string): AreaProblem | null {
  if (!geometry || (geometry.type !== "Polygon" && geometry.type !== "MultiPolygon")) return null;
  return shapeProblem(asLoaded(geometry, coordinateFormat));
}

/**
 * Why *geometry* would be refused as it is, its coordinates exactly as given,
 * before any rounding; null when it would load, or is not an area.
 */
export function shapeProblem(geometry: Geometry | null | undefined): AreaProblem | null {
  if (!geometry || (geometry.type !== "Polygon" && geometry.type !== "MultiPolygon")) return null;
  const parts = exactly(geometry.type === "Polygon" ? [geometry.coordinates] : geometry.coordinates);
  if (!parts) return null;
  const rings = parts.flat();
  if (rings.some(flat)) return "flat";
  const met = meetings(rings);
  if (met === "crosses") return "crosses";
  // Each part's rings are numbered after the rings of the parts before it.
  const firsts = parts.map((_, p) => parts.slice(0, p).reduce((count, part) => count + part.length, 0));
  if (parts.some((part, p) => holeProblem(part, firsts[p], met))) return "hole";
  for (let p = 0; p < parts.length; p++) {
    for (let q = p + 1; q < parts.length; q++) if (overlap(parts[p], firsts[p], parts[q], firsts[q], met)) return "overlap";
  }
  return null;
}

/**
 * The coordinate format the map hands autk-db the layer *fc* in
 * (`detectCoordinateFormat`, as `utils/autkInput` reads a layer), for a shape
 * of it: read from the layer's features, or from the shape while the layer
 * has none.
 */
export function layerFormat(fc: { features?: any[]; crs?: unknown } | undefined, geometry: Geometry): string {
  const features = fc?.features && fc.features.length > 0 ? fc.features : [{ type: "Feature", properties: {}, geometry }];
  return detectCoordinateFormat({ ...(fc ?? {}), features });
}

/** What a refusal says the shape would do, after "That would". */
const WOULD: Record<AreaProblem, string> = {
  crosses: "make the outline cross itself",
  flat: "leave the outline with no area",
  hole: "make a hole cross or leave its outline",
  overlap: "make two of its parts overlap",
};

/** What a refusal says became of the gesture. */
const AFTER: Record<ReshapeGesture, string> = {
  drag: "the corner went back",
  delete: "the corner stayed",
  move: "it went back",
  remove: "the part stayed",
};

/** What a refusal says of a shape drawn. */
const DRAWN: Record<AreaProblem, string> = {
  crosses: "That outline crosses itself",
  flat: "That outline has no area",
  hole: "A hole crosses or leaves its outline",
  overlap: "It overlaps another part",
};

/** The map's tip when a gesture (*how*) would give a shape *problem*: "That would make the outline cross itself, so the corner went back." */
export function reshapeRefusal(problem: AreaProblem, how: ReshapeGesture = "drag"): string {
  return `That would ${WOULD[problem]}, so ${AFTER[how]}.`;
}

/** The map's tip when a shape drawn, a new area or a part of one, has *problem*: "That outline crosses itself, so the area was not added." */
export function drawnRefusal(problem: AreaProblem, what: "area" | "part"): string {
  return `${DRAWN[problem]}, so the ${what} was not added.`;
}

/** *geometry* as autk-db gets it: rounded by the map's own grid for *coordinateFormat* (`snapSourceToGrid`). */
function asLoaded(geometry: Geometry, coordinateFormat: string | undefined): Geometry {
  const source = snapSourceToGrid({
    type: "geojson",
    geojsonObject: { type: "FeatureCollection", features: [{ type: "Feature", properties: {}, geometry }] },
    coordinateFormat,
  });
  return (source.geojsonObject as { features: { geometry: Geometry }[] }).features[0].geometry;
}

const bytes = new DataView(new ArrayBuffer(8));

/** *x* as a whole number times two to a power, exactly: the number and the power. */
function binary(x: number): [bigint, number] {
  bytes.setFloat64(0, x);
  const bits = bytes.getBigUint64(0);
  const biased = Number((bits >> 52n) & 0x7ffn);
  const fraction = bits & 0xfffffffffffffn;
  const whole = biased === 0 ? fraction : fraction | 0x10000000000000n;
  return [bits >> 63n ? -whole : whole, (biased === 0 ? 1 : biased) - 1075];
}

/**
 * *polygons*, an area's parts as GeoJSON holds them, with each coordinate a
 * whole number: the coordinate times one power of two, the least that makes
 * every coordinate whole, times two more, so the middle of two corners is
 * whole too. Null when a ring is not a list of positions of finite numbers.
 */
function exactly(polygons: unknown): Part[] | null {
  if (!Array.isArray(polygons)) return null;
  const numbers: number[] = [];
  for (const rings of polygons) {
    if (!Array.isArray(rings)) return null;
    for (const ring of rings) {
      if (!Array.isArray(ring)) return null;
      for (const position of ring) {
        if (!Array.isArray(position) || !Number.isFinite(position[0]) || !Number.isFinite(position[1])) return null;
        numbers.push(position[0], position[1]);
      }
    }
  }
  let least = Infinity;
  for (const value of numbers) {
    const [whole, power] = binary(value);
    if (whole !== 0n) least = Math.min(least, power);
  }
  if (!Number.isFinite(least)) least = 0;
  const scaled = (value: number): bigint => {
    const [whole, power] = binary(value);
    return whole << BigInt(power - least + 1);
  };
  return (polygons as number[][][][]).map((rings) => rings.map((ring) => cornersOf(ring.map(([x, y]) => [scaled(x), scaled(y)] as const))));
}

const same = (a: Point, b: Point) => a[0] === b[0] && a[1] === b[1];

/** *points*, each once. */
function distinct(points: Point[]): Point[] {
  const out: Point[] = [];
  for (const p of points) if (!out.some((q) => same(p, q))) out.push(p);
  return out;
}

/** *points* as a ring's corners: none repeated next to itself, and the corner that closes it dropped. */
function cornersOf(points: Point[]): Ring {
  const out: Point[] = [];
  for (const p of points) if (out.length === 0 || !same(out[out.length - 1], p)) out.push(p);
  while (out.length > 1 && same(out[0], out[out.length - 1])) out.pop();
  return out;
}

/** Which side of the line from *a* to *b* the point *c* is on: 1 to its left, -1 to its right, 0 on it. */
function turn(a: Point, b: Point, c: Point): number {
  const d = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]);
  return d > 0n ? 1 : d < 0n ? -1 : 0;
}

const between = (u: bigint, v: bigint, w: bigint) => (u <= w && w <= v) || (v <= w && w <= u);

/** Whether *p* lies on the side from *a* to *b*, its ends included. */
const onSide = (a: Point, b: Point, p: Point) => between(a[0], b[0], p[0]) && between(a[1], b[1], p[1]) && turn(a, b, p) === 0;

/**
 * Where the sides *a*-*b* and *c*-*d* meet: "cross" when they cross or run
 * along each other (share two points), else the point where one touches the
 * other, or none.
 */
function meeting(a: Point, b: Point, c: Point, d: Point): Meeting {
  if (turn(a, b, c) * turn(a, b, d) < 0 && turn(c, d, a) * turn(c, d, b) < 0) return "cross";
  const touching = distinct([...[c, d].filter((p) => onSide(a, b, p)), ...[a, b].filter((p) => onSide(c, d, p))]);
  return touching.length > 1 ? "cross" : touching;
}

/** Whether *ring* encloses no area: fewer than three corners, or all of them on one line. */
const flat = (ring: Ring) => ring.length < 3 || ring.every((p) => turn(ring[0], ring[1], p) === 0);

/** A side of a ring, *rings*' *ring*-th: its ends, its place in the ring, and the box around it in plain numbers, for a quick look. */
interface Side {
  a: Point;
  b: Point;
  ring: number;
  at: number;
  x0: number;
  x1: number;
  y0: number;
  y1: number;
}

/**
 * How the sides of *rings* meet, each pair whose boxes meet looked at
 * exactly: "crosses" when two sides of one ring meet that are not
 * neighbours, or two neighbours run back along each other; else how each
 * two rings that meet do, by "i j", the lower number first.
 */
function meetings(rings: Ring[]): "crosses" | Map<string, Meeting> {
  const sides: Side[] = [];
  rings.forEach((ring, r) =>
    ring.forEach((a, at) => {
      const b = ring[(at + 1) % ring.length];
      const [ax, ay, bx, by] = [Number(a[0]), Number(a[1]), Number(b[0]), Number(b[1])];
      sides.push({ a, b, ring: r, at, x0: Math.min(ax, bx), x1: Math.max(ax, bx), y0: Math.min(ay, by), y1: Math.max(ay, by) });
    }),
  );
  // Plain numbers keep the order of the whole ones they stand for, so two
  // boxes apart in them are apart.
  sides.sort((s, t) => (s.x0 < t.x0 ? -1 : s.x0 > t.x0 ? 1 : 0));
  const met = new Map<string, Meeting>();
  for (let i = 0; i < sides.length; i++) {
    const s = sides[i];
    for (let j = i + 1; j < sides.length && sides[j].x0 <= s.x1; j++) {
      const t = sides[j];
      if (t.y0 > s.y1 || s.y0 > t.y1) continue;
      const here = meeting(s.a, s.b, t.a, t.b);
      if (s.ring === t.ring) {
        const gap = Math.abs(s.at - t.at);
        const neighbours = gap === 1 || gap === rings[s.ring].length - 1;
        if (here === "cross" || (!neighbours && here.length > 0)) return "crosses";
        continue;
      }
      if (here !== "cross" && here.length === 0) continue;
      const key = s.ring < t.ring ? `${s.ring} ${t.ring}` : `${t.ring} ${s.ring}`;
      const before = met.get(key) ?? [];
      met.set(key, here === "cross" || before === "cross" ? "cross" : distinct([...before, ...here]));
    }
  }
  return met;
}

/** How rings *i* and *j* of *met* meet. */
const meetingOf = (met: Map<string, Meeting>, i: number, j: number): Meeting => met.get(i < j ? `${i} ${j}` : `${j} ${i}`) ?? [];

/** Where *p* is from the area *ring* bounds. */
function placeIn(p: Point, ring: Ring): Place {
  let inside = false;
  for (let i = 0; i < ring.length; i++) {
    const a = ring[i];
    const b = ring[(i + 1) % ring.length];
    if (onSide(a, b, p)) return "on";
    // A side across the line through p, to its right: up with p on its left, or down with p on its right.
    if (a[1] > p[1] !== b[1] > p[1] && turn(a, b, p) === (b[1] > a[1] ? 1 : -1)) inside = !inside;
  }
  return inside ? "in" : "out";
}

/** Where *p* is from a part's area: inside its outline and outside its holes is in. */
function placeInPart(p: Point, [outline, ...holes]: Part): Place {
  const at = placeIn(p, outline);
  if (at !== "in") return at;
  for (const hole of holes) {
    const there = placeIn(p, hole);
    if (there !== "out") return there === "on" ? "on" : "out";
  }
  return "in";
}

/**
 * A point of each stretch of *ring* between the points *cuts* on it: a
 * corner when there are none, else the middle of the piece after each cut.
 * An area whose boundary meets the ring at those points alone, crossing it
 * nowhere, has each stretch all inside it or all outside it.
 */
function stretchesOf(ring: Ring, cuts: Point[]): Point[] {
  if (cuts.length === 0) return [ring[0]];
  const out: Point[] = [];
  for (let i = 0; i < ring.length; i++) {
    const a = ring[i];
    const b = ring[(i + 1) % ring.length];
    const on = cuts.filter((p) => onSide(a, b, p));
    if (on.length === 0) continue;
    const along = (p: Point) => (p[0] - a[0]) * (b[0] - a[0]) + (p[1] - a[1]) * (b[1] - a[1]);
    const stops = distinct([a, ...on, b]).sort((p, q) => {
      const d = along(p) - along(q);
      return d > 0n ? 1 : d < 0n ? -1 : 0;
    });
    for (let k = 0; k + 1 < stops.length; k++) {
      if (cuts.some((p) => same(p, stops[k]))) out.push([(stops[k][0] + stops[k + 1][0]) / 2n, (stops[k][1] + stops[k + 1][1]) / 2n]);
    }
  }
  return out;
}

/** The points where rings *i* and *j* of *met* touch: none when they cross. */
const touchesOf = (met: Map<string, Meeting>, i: number, j: number): Point[] => {
  const here = meetingOf(met, i, j);
  return here === "cross" ? [] : here;
};

/**
 * Whether a hole of *part*, whose rings are *met*'s from *first* on, crosses
 * or leaves its outline, overlaps another hole or lies in one, or the rings
 * that touch cut the area in two: two rings that touch twice, or rings that
 * touch in a loop.
 */
function holeProblem(part: Part, first: number, met: Map<string, Meeting>): boolean {
  if (part.length < 2) return false;
  // The rings and the points where they touch, joined: a loop cuts the area in two.
  const joinedTo = new Map<string, string>();
  const root = (node: string): string => {
    let at = node;
    for (let next = joinedTo.get(at); next !== undefined; next = joinedTo.get(at)) at = next;
    return at;
  };
  const links = new Set<string>();
  for (let i = 0; i < part.length; i++) {
    for (let j = i + 1; j < part.length; j++) {
      const here = meetingOf(met, first + i, first + j);
      if (here === "cross") return true;
      for (const p of here) {
        const point = `point ${p[0]} ${p[1]}`;
        for (const ring of [i, j]) {
          const link = `${ring} ${point}`;
          if (links.has(link)) continue;
          links.add(link);
          const a = root(`ring ${ring}`);
          const b = root(point);
          if (a === b) return true;
          joinedTo.set(a, b);
        }
      }
    }
  }
  // Each hole lies inside its outline, and outside every other hole.
  for (let j = 1; j < part.length; j++) {
    const leaves = stretchesOf(part[j], touchesOf(met, first, first + j)).some((p) => placeIn(p, part[0]) === "out");
    if (leaves) return true;
    for (let i = 1; i < j; i++) {
      const cuts = touchesOf(met, first + i, first + j);
      if (stretchesOf(part[j], cuts).some((p) => placeIn(p, part[i]) === "in")) return true;
      if (stretchesOf(part[i], cuts).some((p) => placeIn(p, part[j]) === "in")) return true;
    }
  }
  return false;
}

/**
 * Whether the parts *p* and *q*, whose rings are *met*'s from *firstP* and
 * *firstQ* on, overlap: sides of theirs cross or run along each other, or a
 * stretch of a ring of one lies inside the other's area.
 */
function overlap(p: Part, firstP: number, q: Part, firstQ: number, met: Map<string, Meeting>): boolean {
  for (let i = 0; i < p.length; i++) for (let j = 0; j < q.length; j++) if (meetingOf(met, firstP + i, firstQ + j) === "cross") return true;
  const inArea = (ring: Ring, r: number, area: Part, firstArea: number) => {
    const cuts = distinct(area.flatMap((_, k) => touchesOf(met, r, firstArea + k)));
    return stretchesOf(ring, cuts).some((x) => placeInPart(x, area) === "in");
  };
  return p.some((ring, i) => inArea(ring, firstP + i, q, firstQ)) || q.some((ring, j) => inArea(ring, firstQ + j, p, firstP));
}
