/**
 * How a Vega-Lite spec is sized to its node (#202).
 *
 * `compileGrammar` used to set `width`/`height` to `"container"`
 * unconditionally. That is wrong twice over:
 *
 * 1. **Multi-view specs discard it.** vega-lite's `normalizeAutoSize` throws
 *    both away for `vconcat` / `hconcat` / `concat` / `facet` / `repeat` and
 *    leaves `autosize: pad`, so the natural size is authoritative. The repro
 *    spec (`docs/examples/05-vega-lite-multi-view-drilldown.json`) is a
 *    top-level `vconcat` of 650x400 and 650x300 sub-views: roughly 750px of
 *    chart into a ~292px pane, clipped, with the `ResizeObserver` unable to
 *    help because `autosize: pad` ignores the container.
 * 2. **It clobbers the author's own sizing.** A spec that deliberately says
 *    `width: 800` had it overwritten with no way to opt out.
 *
 * So: leave multi-view specs alone (vega-lite would discard the injection
 * anyway, and the mount container scrolls now), and for unit/layer specs fill
 * the container only where the author has not said otherwise.
 *
 * Kept as a pure function so it is testable without mocking `vega` /
 * `vega-lite`, which are ESM and unloadable under jest.
 */

/** Top-level keys whose presence makes a spec multi-view. */
const MULTI_VIEW_KEYS = ["vconcat", "hconcat", "concat", "facet", "repeat"] as const;

export function isMultiViewSpec(spec: Record<string, unknown> | null | undefined): boolean {
  if (!spec || typeof spec !== "object") return false;
  return MULTI_VIEW_KEYS.some((key) => spec[key] != null);
}

/**
 * Applies container sizing in place and returns the same object.
 *
 * - multi-view: untouched.
 * - unit/layer: a `width` or `height` the author left out becomes
 *   `"container"`, so the chart fills its node there.
 * - A spec with no `autosize` gets one that fits only the sizes that are
 *   `"container"` now, left out or written so by the author: both (`fit`),
 *   the width (`fit-x`) or the height (`fit-y`), with `resize` so the view
 *   follows its node when the node is resized.
 * - A size the author set, a number or a `{step}`, is the plot's own. Vega-Lite's
 *   default (`pad`) lays the axes, title and legend out around it, and the
 *   node's pane scrolls when the chart is larger than the node. A `fit` on such
 *   a size fitted the whole chart into it instead, so the axes and the legend
 *   took their room from the plot, and `resize: true` laid it out again on
 *   every hover (#1097).
 * - An `autosize` the author set is kept.
 */
export function applyContainerSizing<T extends Record<string, unknown>>(spec: T): T {
  if (!spec || typeof spec !== "object") return spec;
  if (isMultiViewSpec(spec)) return spec;

  if (spec.width === undefined) {
    (spec as Record<string, unknown>).width = "container";
  }
  if (spec.height === undefined) {
    (spec as Record<string, unknown>).height = "container";
  }
  if (spec.autosize === undefined) {
    const type = fitType(spec.width === "container", spec.height === "container");
    if (type) {
      (spec as Record<string, unknown>).autosize = {
        type,
        contains: "padding",
        resize: true,
      };
    }
  }
  return spec;
}

/** The autosize type that fits the sizes the node gives: both, one, or none. */
function fitType(width: boolean, height: boolean): "fit" | "fit-x" | "fit-y" | undefined {
  if (width && height) return "fit";
  if (width) return "fit-x";
  if (height) return "fit-y";
  return undefined;
}

/**
 * Reads the mount's size into a container-sized view before it is resized (#496).
 *
 * vega-lite turns `"container"` into a `width` / `height` signal that reads
 * `containerSize()` when the view starts and again only on `window:resize`.
 * `view.resize()` re-runs autosize with whatever the signal holds, so a
 * scrollbar that appeared after the first draw, or a node resized by hand,
 * left the chart at its old width: wider than the pane, legends cut off.
 *
 * `containerSize()` is the mount's `clientWidth` / `clientHeight`, so this
 * sets the same numbers it would.
 */
export function refitToContainer(
  view: { width(value: number): unknown; height(value: number): unknown } | null | undefined,
  el: { clientWidth: number; clientHeight: number } | null | undefined,
  spec: Record<string, unknown> | null | undefined,
): void {
  if (!view || !el || !spec) return;
  if (spec.width === "container" && el.clientWidth > 0) view.width(el.clientWidth);
  if (spec.height === "container" && el.clientHeight > 0) view.height(el.clientHeight);
}

/** Whether *spec*'s plot is sized from its container: a `fit` autosize. */
export function fitsItsContainer(spec: Record<string, unknown> | null | undefined): boolean {
  if (!spec || typeof spec !== "object") return false;
  const autosize = spec.autosize as string | { type?: unknown } | undefined;
  const type = typeof autosize === "string" ? autosize : autosize?.type;
  return type === "fit" || type === "fit-x" || type === "fit-y";
}

/** The most fit passes one settle makes (settleFit). */
export const MAX_SETTLE_PASSES = 3;

/** What settleFit reads and runs of a vega view. */
export type SettlingView = {
  width(): number;
  height(): number;
  origin(): number[];
  resize(): { runAsync(): Promise<unknown> };
};

/**
 * Fits a container-sized view again until its plot holds still.
 *
 * Vega fits a plot to its container in one pass. It lays the plot out for the
 * axis labels it makes at the size it starts from, then draws the labels the
 * fitted size makes, and an axis asks for about a tick per 40 px, so the two
 * can differ. Fitted from its node's full height, a y axis up to 9 ticked every
 * 0.5 ("0.0" to "9.0"), while the plot's own height draws a tick every 1 ("0"
 * to "9"): the plot kept the room of the wider labels, an empty band beside the
 * axis. A view that gets new rows in place starts from its plot's height and
 * fitted, so the same rows were drawn two ways.
 *
 * Each pass starts from the size the pass before left, not from the mount
 * (unlike refitToContainer), so the first pass that moves nothing has the
 * layout that fits what it draws. At most MAX_SETTLE_PASSES, for an axis whose
 * labels would flip back and forth. A view that cannot say where its plot is
 * (a test's stand-in for vega's, which several suites trim to the members
 * they use) is left as it is.
 */
export async function settleFit(view: SettlingView | null | undefined): Promise<void> {
  if (!view || typeof view.origin !== "function") return;
  for (let pass = 0; pass < MAX_SETTLE_PASSES; pass += 1) {
    const before = layoutOf(view);
    await view.resize().runAsync();
    if (sameLayout(before, layoutOf(view))) return;
  }
}

function layoutOf(view: SettlingView): number[] {
  return [view.width(), view.height(), ...view.origin()];
}

function sameLayout(a: number[], b: number[]): boolean {
  return a.length === b.length && a.every((value, index) => value === b[index]);
}

/**
 * Tells a genuine resize from a refit flipping the mount's scrollbars (#496).
 *
 * When re-fitting makes a scrollbar appear or vanish, the mount changes size
 * because of the refit itself, and the next refit undoes it: A, B, A, B, every
 * frame. A size equal to the one two callbacks back is that flip, so the caller
 * resizes without re-reading the mount, and the view settles at the size that
 * fits. The cost is one missed refit when a node really is resized back to the
 * size it had two resizes ago.
 */
export function createFlipGuard(): (size: string) => boolean {
  const recent: string[] = [];
  return (size) => {
    const flipping = recent.length >= 2 && recent[recent.length - 2] === size;
    recent.push(size);
    if (recent.length > 2) recent.shift();
    return flipping;
  };
}
