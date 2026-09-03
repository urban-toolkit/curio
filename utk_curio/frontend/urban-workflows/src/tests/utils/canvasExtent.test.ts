/**
 * The dataflow canvas pan bound (#234).
 *
 * The bound had no test at all, which is how it came to be deleted in
 * `b88c6685 "fix canvas extent"` and restored in `44365b01` - a round trip
 * these cases exist to prevent a third time. Two properties matter and they
 * pull against each other:
 *
 *   1. Every placed node must be reachable (the bug as reported).
 *   2. The viewport must never be strandable (why the clamp exists at all:
 *      minZoom 0.05 with no bound means one gesture and no way back).
 *
 * The union with the floor is what satisfies both at once.
 */
import { CANVAS_EXTENT_FLOOR, computeTranslateExtent } from "../../utils/canvasExtent";

const node = (id: string, x: number, y: number) => ({
  id,
  position: { x, y },
  data: {},
  width: 200,
  height: 150,
});

const contains = (
  extent: [[number, number], [number, number]],
  x: number,
  y: number,
) =>
  x >= extent[0][0] && x <= extent[1][0] && y >= extent[0][1] && y <= extent[1][1];

describe("computeTranslateExtent", () => {
  it("returns the floor for an empty canvas", () => {
    expect(computeTranslateExtent([])).toEqual(CANVAS_EXTENT_FLOOR);
    expect(computeTranslateExtent(undefined)).toEqual(CANVAS_EXTENT_FLOOR);
    expect(computeTranslateExtent(null)).toEqual(CANVAS_EXTENT_FLOOR);
  });

  it("reaches a node far outside the old static box", () => {
    // usePosition places each palette node at maxX + 800, so the 9th is
    // already past the old x=6000 wall; a notebook import strides 700/level.
    const extent = computeTranslateExtent([node("far", 9000, 0)] as any);
    expect(contains(extent, 9000, 0)).toBe(true);
    expect(extent[1][0]).toBeGreaterThan(9000);
  });

  it("never shrinks below the floor", () => {
    // A single node near the origin must not pull the bound in around it -
    // that would make empty regions of the old canvas unreachable, which is a
    // worse bug than the one being fixed.
    const extent = computeTranslateExtent([node("a", 100, 100)] as any);
    expect(extent[0][0]).toBeLessThanOrEqual(CANVAS_EXTENT_FLOOR[0][0]);
    expect(extent[0][1]).toBeLessThanOrEqual(CANVAS_EXTENT_FLOOR[0][1]);
    expect(extent[1][0]).toBeGreaterThanOrEqual(CANVAS_EXTENT_FLOOR[1][0]);
    expect(extent[1][1]).toBeGreaterThanOrEqual(CANVAS_EXTENT_FLOOR[1][1]);
  });

  it("grows in every direction, not just to the right", () => {
    const extent = computeTranslateExtent([
      node("nw", -9000, -7000),
      node("se", 12000, 9000),
    ] as any);
    expect(contains(extent, -9000, -7000)).toBe(true);
    expect(contains(extent, 12000, 9000)).toBe(true);
  });

  it("quantizes, so a small drag does not churn the extent", () => {
    // React Flow keys its translateExtent effect on identity, so a bound that
    // changed with every mousemove would re-enter d3-zoom on every frame.
    const a = computeTranslateExtent([node("a", 9000, 0)] as any);
    const b = computeTranslateExtent([node("a", 9003, 4)] as any);
    expect(b).toEqual(a);
  });

  it("does change once a node crosses a boundary", () => {
    // The flip side: quantization must not be so coarse that the bound stops
    // tracking. A node dragged a long way still widens it.
    const a = computeTranslateExtent([node("a", 9000, 0)] as any);
    const b = computeTranslateExtent([node("a", 30000, 0)] as any);
    expect(b[1][0]).toBeGreaterThan(a[1][0]);
  });

  it("tolerates nodes React Flow has not measured yet", () => {
    // width/height are null until React Flow measures the DOM, which a project
    // load routinely beats. Positions are already correct, and the padding
    // dwarfs a node, so the bound is still right.
    const unmeasured = { id: "u", position: { x: 9000, y: 0 }, data: {} };
    const extent = computeTranslateExtent([unmeasured] as any);
    expect(contains(extent, 9000, 0)).toBe(true);
  });

  it("falls back to the floor on a non-finite position", () => {
    // One NaN would otherwise propagate through every comparison and leave an
    // extent that clamps panning to nothing at all.
    const extent = computeTranslateExtent([
      { id: "bad", position: { x: NaN, y: 0 }, data: {} },
    ] as any);
    expect(extent).toEqual(CANVAS_EXTENT_FLOOR);
  });
});
