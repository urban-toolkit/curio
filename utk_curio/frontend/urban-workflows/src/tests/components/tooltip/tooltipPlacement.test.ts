/**
 * Where the one Curio tooltip goes, as a pure function of the target's box on
 * screen, the tooltip's size and the window's: above the target, centered on
 * it, 6 px away; below it when there is no room above; shifted to stay 8 px
 * inside the window. Tool rail palette rows open it to the right, and a chart's
 * data tooltip goes where the pointer is, by the same rules.
 *
 * Its size caps are pure too: plain text is at most 320 px wide, a preview at
 * most 480 x 360 px, and neither is wider than the window less 16 px.
 *
 * The numbers are the plan's, written out, so a change to any of them shows
 * here.
 */
import { placeTooltip, tooltipMaxSize } from "../../../components/tooltip/tooltipPlacement";

/** A box as getBoundingClientRect gives it. */
function box(left: number, top: number, width: number, height: number) {
  return { left, top, width, height, right: left + width, bottom: top + height, x: left, y: top };
}

const WINDOW = { width: 1000, height: 800 };
const SIZE = { width: 120, height: 40 };

describe("above the target", () => {
  test("centered on it, 6 px above it", () => {
    // Centered on x = 420: 420 - 60. Its bottom 6 px above the target's top.
    expect(placeTooltip({ target: box(400, 300, 40, 20), size: SIZE, viewport: WINDOW, side: "top" })).toEqual({
      left: 360,
      top: 254,
      placement: "top",
    });
  });

  test("above is the default side", () => {
    expect(placeTooltip({ target: box(400, 300, 40, 20), size: SIZE, viewport: WINDOW })).toEqual({
      left: 360,
      top: 254,
      placement: "top",
    });
  });

  test("below it, 6 px away, when there is no room above", () => {
    // Above, its top would be 20 - 6 - 40 = -26, out of the window.
    expect(placeTooltip({ target: box(400, 20, 40, 20), size: SIZE, viewport: WINDOW })).toEqual({
      left: 360,
      top: 46,
      placement: "bottom",
    });
  });

  test("shifted right to stay 8 px inside the window's left edge", () => {
    // Centered on x = 8 it would start at -52.
    expect(placeTooltip({ target: box(0, 300, 16, 16), size: SIZE, viewport: WINDOW })).toEqual({
      left: 8,
      top: 254,
      placement: "top",
    });
  });

  test("shifted left to stay 8 px inside the window's right edge", () => {
    // Centered on x = 992 it would end at 1052; it ends at 1000 - 8 instead.
    expect(placeTooltip({ target: box(984, 300, 16, 16), size: SIZE, viewport: WINDOW })).toEqual({
      left: 872,
      top: 254,
      placement: "top",
    });
  });
});

describe("to the right, for a tool rail palette row", () => {
  test("6 px right of the row, centered on it from top to bottom", () => {
    expect(placeTooltip({ target: box(40, 300, 200, 24), size: SIZE, viewport: WINDOW, side: "right" })).toEqual({
      left: 246,
      top: 292,
      placement: "right",
    });
  });

  test("shifted up to stay 8 px inside the window's bottom edge", () => {
    // Centered on y = 788 it would end at 808; it ends at 800 - 8 instead.
    expect(placeTooltip({ target: box(40, 780, 200, 16), size: SIZE, viewport: WINDOW, side: "right" })).toEqual({
      left: 246,
      top: 752,
      placement: "right",
    });
  });
});

describe("at the pointer, for a chart's data tooltip", () => {
  const chart = box(100, 100, 600, 400);

  test("above the pointer, centered on it, 6 px away, wherever the chart is", () => {
    const placed = { left: 240, top: 204, placement: "top" };
    expect(
      placeTooltip({ target: chart, size: SIZE, viewport: WINDOW, side: "pointer", pointer: { x: 300, y: 250 } }),
    ).toEqual(placed);
    // The chart's own box does not move it: the pointer does.
    expect(
      placeTooltip({ target: box(0, 0, 900, 700), size: SIZE, viewport: WINDOW, side: "pointer", pointer: { x: 300, y: 250 } }),
    ).toEqual(placed);
  });

  test("below the pointer when there is no room above it", () => {
    expect(
      placeTooltip({ target: chart, size: SIZE, viewport: WINDOW, side: "pointer", pointer: { x: 300, y: 30 } }),
    ).toEqual({ left: 240, top: 36, placement: "bottom" });
  });

  test("shifted to stay 8 px inside the window", () => {
    expect(
      placeTooltip({ target: chart, size: SIZE, viewport: WINDOW, side: "pointer", pointer: { x: 990, y: 250 } }),
    ).toEqual({ left: 872, top: 204, placement: "top" });
  });
});

describe("how large it may grow", () => {
  test("plain text is at most 320 px wide", () => {
    expect(tooltipMaxSize("text", { width: 1280, height: 800 }).maxWidth).toBe(320);
  });

  test("a preview is at most 480 x 360 px", () => {
    expect(tooltipMaxSize("preview", { width: 1280, height: 800 })).toEqual({ maxWidth: 480, maxHeight: 360 });
  });

  test("neither is wider than the window less 16 px", () => {
    expect(tooltipMaxSize("preview", { width: 400, height: 800 }).maxWidth).toBe(384);
    expect(tooltipMaxSize("text", { width: 300, height: 600 }).maxWidth).toBe(284);
  });
});
