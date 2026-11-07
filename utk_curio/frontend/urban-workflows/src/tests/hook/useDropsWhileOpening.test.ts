/**
 * A drop kept while a dataflow opens lands in the view the canvas opens in.
 *
 * A load that brings nodes frames them a frame or more after it lands
 * (`loadFitPending`). What was dropped while the dataflow opened used to land
 * at the load itself, before that fit, at the place read over the empty
 * canvas: from a view the dataflow never showed, and possibly on one of its
 * nodes. Now it waits for the fit, lands on the next frame, once the fit's view
 * is set, and goes through *place*, which puts it in that view. A fit after the
 * canvas has opened (a version put back, a merge) keeps no drop, and a load
 * that asks for no fit lands what was kept at once, as before.
 */
import { act, renderHook } from "@testing-library/react";

import { useDropsWhileOpening, type CanvasOpening } from "../../hook/useDropsWhileOpening";

const OWNER = { viewerMode: "owner", roomRole: "owner" } as const;
const OPENING: CanvasOpening = { load: "loading", ...OWNER };
const LOADED: CanvasOpening = { load: "loaded", ...OWNER };

/** Frames come when the test says. */
let frames: FrameRequestCallback[] = [];
const realFrame = window.requestAnimationFrame;
const realCancel = window.cancelAnimationFrame;

function runFrames() {
  act(() => {
    frames.splice(0).forEach((frame) => frame(0));
  });
}

function canvas(initial: CanvasOpening) {
  const landed: string[] = [];
  const placed: string[][] = [];
  const place = (kept: string[]) => {
    placed.push([...kept]);
    return kept.map((drop) => `${drop}, placed`);
  };
  const view = renderHook(
    ({ opening }: { opening: CanvasOpening }) =>
      useDropsWhileOpening<string>(opening, (drop) => landed.push(drop), place),
    { initialProps: { opening: initial } },
  );
  return {
    keep: (drop: string) => view.result.current(drop),
    open: (opening: CanvasOpening) => view.rerender({ opening }),
    landed,
    placed,
  };
}

beforeEach(() => {
  frames = [];
  window.requestAnimationFrame = (frame: FrameRequestCallback) => frames.push(frame);
  window.cancelAnimationFrame = (id: number) => {
    delete frames[id - 1];
  };
});

afterEach(() => {
  window.requestAnimationFrame = realFrame;
  window.cancelAnimationFrame = realCancel;
});

test("a drop kept while a dataflow's nodes are framed lands once their fit is set, on the next frame, placed", () => {
  const tab = canvas(OPENING);
  const keptWhileLoading = tab.keep("tile");

  tab.open({ ...LOADED, framing: true });
  const keptWhileFraming = tab.keep("card");
  const landedWhileFraming = [...tab.landed];

  tab.open({ ...LOADED, framing: false });
  const landedBeforeTheFrame = [...tab.landed];
  runFrames();

  expect({
    keptWhileLoading,
    keptWhileFraming,
    landedWhileFraming,
    landedBeforeTheFrame,
    placed: tab.placed,
    landed: tab.landed,
  }).toEqual({
    keptWhileLoading: true,
    keptWhileFraming: true,
    landedWhileFraming: [],
    landedBeforeTheFrame: [],
    placed: [["tile", "card"]],
    landed: ["tile, placed", "card, placed"],
  });
});

test("a drop made while kept drops wait for their frame lands after them", () => {
  const tab = canvas(OPENING);
  tab.keep("tile");
  tab.open({ ...LOADED, framing: true });
  tab.open({ ...LOADED, framing: false });

  const keptBeforeTheFrame = tab.keep("card");
  runFrames();

  expect({ keptBeforeTheFrame, landed: tab.landed }).toEqual({
    keptBeforeTheFrame: true,
    landed: ["tile, placed", "card, placed"],
  });
});

test("a fit after the canvas has opened keeps no drop", () => {
  const tab = canvas(OPENING);
  tab.open({ ...LOADED, framing: true });
  tab.open({ ...LOADED, framing: false });
  runFrames();

  // A version put back, or a merge, asks for a fit of its own.
  tab.open({ ...LOADED, framing: true });
  expect(tab.keep("tile")).toBe(false);
});

test("a load that asks for no fit lands what was kept at once, placed", () => {
  const tab = canvas(OPENING);
  tab.keep("tile");

  tab.open({ ...LOADED, framing: false });

  expect({ landed: tab.landed, frames: frames.length }).toEqual({
    landed: ["tile, placed"],
    frames: 0,
  });
});
