/**
 * How an Autark plot is sized to its node.
 *
 * autk-plot draws a plot at a fixed 800 x 500 pixels unless its config sets
 * `width` and `height`, and autk-grammar passes a plot spec's own `width` and
 * `height` through. So a plot whose document set neither was wider and taller
 * than its node: the pane scrolled where scrollbars show, and cut off the last
 * bar where they hide.
 *
 * The rule is the Vega-Lite node's (`vegaSpecSizing.ts`): a plot fills its
 * pane where the document did not say otherwise, a size the document set is
 * kept (the pane scrolls), and a spec with several plots is left alone. One
 * difference: a Vega view lays itself out again when its node is resized, but
 * autk-plot cannot change a plot's size once it is drawn, so an Autark plot is
 * fitted to its pane each time its node runs.
 */

/**
 * The smallest size a plot is fitted to. autk-plot keeps 130 px of a plot's
 * height and 60 px of its width for the title and axes, so a pane smaller than
 * this gets a plot this big, and scrolls.
 */
export const MIN_FITTED_PLOT_PX = 200;

export interface PaneSize {
  width: number;
  height: number;
}

function fitted(declared: unknown, pane: number): number | undefined {
  if (declared !== undefined || !(pane > 0)) return undefined;
  return Math.max(Math.floor(pane), MIN_FITTED_PLOT_PX);
}

/**
 * The plot section with `width` and `height` filled from *pane* wherever the
 * document left them out. A new object: the spec it came from is not changed.
 * A pane that measures 0 (not laid out) leaves that dimension to autk-plot.
 */
export function fitPlotToPane<T>(plot: T, pane: PaneSize): T {
  if (!plot || typeof plot !== "object" || Array.isArray(plot)) return plot;
  const spec = plot as Record<string, unknown>;
  const width = fitted(spec.width, pane.width);
  const height = fitted(spec.height, pane.height);
  if (width === undefined && height === undefined) return plot;
  return {
    ...spec,
    ...(width !== undefined ? { width } : {}),
    ...(height !== undefined ? { height } : {}),
  } as T;
}
