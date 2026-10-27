/**
 * A chart's data tooltip in the one Curio tooltip.
 *
 * With no handler of its own, a Vega view writes the hovered mark's tooltip
 * into its chart element as a native `title`, the browser's grey box. This
 * handler writes the same text, at the same moments, as the element's
 * `data-tooltip`, which the TooltipLayer shows at the pointer and follows as
 * the pointer crosses marks; off every mark Vega passes no value, and it
 * clears it. Every place that builds a Vega view installs it: the Vega-Lite
 * node (useVega), the grammar adapter and the monitor page's charts.
 *
 * The text is formatted as vega-view's own handler formats it: a field per
 * line as "name: value", a list in brackets, and nested values cut short.
 *
 * Vega answers a line only within its stroke's width of one of its points
 * (vega-scenegraph's `pickLine`), and a thin rule or a small point barely
 * more, so a line's tooltip seldom showed, whether the mark said
 * `"tooltip": true` or an encoding named its fields. `reachVegaTooltips`
 * gives a view the tooltip of the mark nearest the pointer, within
 * VEGA_TOOLTIP_REACH_PX on screen, wherever Vega gives none; each place that
 * installs the handler calls it.
 */

const isObject = (value: unknown): value is Record<string, unknown> =>
  value !== null && typeof value === "object" && !(value instanceof Date);

function formatValue(value: unknown): unknown {
  if (Array.isArray(value)) return "[…]";
  if (isObject(value)) return "{…}";
  return value;
}

function formatArray(value: unknown[]): string {
  return `[${value.map(formatValue).join(", ")}]`;
}

/** What vega-view's own tooltip handler writes for *value*. */
export function formatVegaTooltip(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (Array.isArray(value)) return formatArray(value);
  if (isObject(value)) {
    return Object.keys(value)
      .map((key) => {
        const field = value[key];
        return `${key}: ${Array.isArray(field) ? formatArray(field) : String(formatValue(field))}`;
      })
      .join("\n");
  }
  return String(value);
}

/** The chart element's `data-tooltip` for *value*, at the pointer, or none. */
function writeTooltip(el: Element, value: unknown): void {
  const text = formatVegaTooltip(value);
  if (text) {
    el.setAttribute("data-tooltip", text);
    el.setAttribute("data-tooltip-side", "pointer");
  } else {
    el.removeAttribute("data-tooltip");
  }
}

/** The tooltip Vega itself last gave each chart element, with the event it came on. */
const vegaSaid = new WeakMap<Element, { event: unknown; value: unknown }>();

/** Vega's tooltip handler: the chart element's `data-tooltip`, at the pointer. */
export function vegaTooltipHandler(
  handler: { element(): Element | null },
  event: unknown,
  _item: unknown,
  value: unknown,
): void {
  const el = handler.element();
  if (!el) return;
  vegaSaid.set(el, { event, value });
  writeTooltip(el, value);
}

/** How far from a mark, in pixels on screen, the pointer still gets its tooltip. */
export const VEGA_TOOLTIP_REACH_PX = 8;

/** A mark of a Vega scenegraph, as far as the nearest mark's search reads one. */
export interface VegaSceneMark {
  marktype?: string;
  interactive?: boolean;
  items?: VegaSceneItem[];
}

/** An item of a Vega scenegraph, in its group's coordinates; a group's holds marks. */
export interface VegaSceneItem {
  x?: number;
  y?: number;
  x2?: number;
  y2?: number;
  defined?: boolean;
  tooltip?: unknown;
  bounds?: { x1: number; y1: number; x2: number; y2: number };
  items?: VegaSceneMark[];
}

/** How far (x, y) lies from the segment a to b, and where along it the nearest point is: 0 at a, 1 at b. */
function fromSegment(x: number, y: number, ax: number, ay: number, bx: number, by: number) {
  const dx = bx - ax;
  const dy = by - ay;
  const length = dx * dx + dy * dy;
  const along = length ? Math.min(1, Math.max(0, ((x - ax) * dx + (y - ay) * dy) / length)) : 0;
  return { distance: Math.hypot(x - (ax + along * dx), y - (ay + along * dy)), along };
}

/** How far (x, y) lies from a box; 0 inside it. */
function fromBox(x: number, y: number, box: { x1: number; y1: number; x2: number; y2: number }): number {
  return Math.hypot(Math.max(box.x1 - x, 0, x - box.x2), Math.max(box.y1 - y, 0, y - box.y2));
}

/** Keeps the nearest item with a tooltip seen so far; a later one wins a tie, as it is drawn on top. */
type Nearest = { item: VegaSceneItem | null; distance: number };

function consider(nearest: Nearest, item: VegaSceneItem, distance: number): void {
  if (item.tooltip == null || item.tooltip === "" || distance > nearest.distance) return;
  nearest.item = item;
  nearest.distance = distance;
}

function search(mark: VegaSceneMark, x: number, y: number, nearest: Nearest): void {
  if (mark.interactive === false || !mark.items) return;
  const n = (value: number | undefined) => value ?? 0;
  switch (mark.marktype) {
    case "group":
      for (const group of mark.items) {
        for (const child of group.items ?? []) search(child, x - n(group.x), y - n(group.y), nearest);
      }
      return;
    case "line":
    case "trail":
    case "area": {
      // The path through the points, each stretch answered by its nearer end.
      let previous: VegaSceneItem | null = null;
      for (const item of mark.items) {
        if (item.defined === false) {
          previous = null;
          continue;
        }
        if (previous) {
          const { distance, along } = fromSegment(x, y, n(previous.x), n(previous.y), n(item.x), n(item.y));
          consider(nearest, along < 0.5 ? previous : item, distance);
        } else {
          consider(nearest, item, Math.hypot(x - n(item.x), y - n(item.y)));
        }
        previous = item;
      }
      return;
    }
    case "rule":
      for (const item of mark.items) {
        const { distance } = fromSegment(x, y, n(item.x), n(item.y), item.x2 ?? n(item.x), item.y2 ?? n(item.y));
        consider(nearest, item, distance);
      }
      return;
    case "symbol":
    case "rect":
    case "text":
      for (const item of mark.items) {
        if (item.bounds) consider(nearest, item, fromBox(x, y, item.bounds));
      }
      return;
    default:
      // A shape, an arc, an image or a path: Vega picks it wherever it is drawn.
      return;
  }
}

/**
 * The item with a tooltip nearest (x, y), within *reach*, both in the
 * coordinates of the group that holds *mark*; or null. A line, a trail or an
 * area is the path through its points, and the nearer end of its nearest
 * stretch answers; a rule is its segment; a point, a bar or a text is its box.
 * A mark Vega does not pick (`interactive: false`) answers nothing.
 */
export function nearestVegaTooltip(mark: VegaSceneMark, x: number, y: number, reach: number): VegaSceneItem | null {
  const nearest: Nearest = { item: null, distance: reach };
  search(mark, x, y, nearest);
  return nearest.item;
}

/** The part of a Vega view the nearest mark's tooltip reads. */
export interface TooltipView {
  addEventListener(type: string, handler: (event: PointerEvent) => void): unknown;
  container(): Element | null;
  scenegraph(): { root: unknown };
  padding(): { left: number; top: number };
  origin(): [number, number];
}

/**
 * Give *view* the nearest mark's tooltip wherever Vega gives none: on each
 * move of the pointer over the chart, after Vega's own handler has had its
 * turn, and none once the pointer leaves the chart.
 */
export function reachVegaTooltips(view: TooltipView): void {
  view.addEventListener("pointermove", (event) => {
    const el = view.container();
    // The canvas or SVG Vega draws into: Vega's own listener on it calls this one.
    const chart = event.currentTarget;
    if (!el || !(chart instanceof Element) || event.pointerType === "touch") return;
    const said = vegaSaid.get(el);
    if (said && said.event === event && formatVegaTooltip(said.value)) return;
    // Vega's own map from the pointer to the chart's pixels, which takes the
    // canvas's CSS scale (React Flow's zoom) off: vega-scenegraph's `point`,
    // which vega's typings leave out. Less the view's padding and origin, it is
    // where Vega's scenegraph puts its items.
    const [px, py] = require("vega").point(event, chart) as [number, number];
    const padding = view.padding();
    const [ox, oy] = view.origin();
    const box = chart.getBoundingClientRect();
    const laidOut = (chart as HTMLElement).offsetWidth || chart.clientWidth || box.width;
    const scale = laidOut ? box.width / laidOut : 1;
    const root = view.scenegraph().root as VegaSceneMark;
    const item = nearestVegaTooltip(root, px - padding.left - ox, py - padding.top - oy, VEGA_TOOLTIP_REACH_PX / scale);
    writeTooltip(el, item ? item.tooltip : null);
  });
  view.addEventListener("pointerout", (event) => {
    const el = view.container();
    const chart = event.currentTarget;
    // Vega fires it with a move's own event as the pointer crosses from one
    // mark to another, and an SVG chart's marks send theirs up to it: only
    // the pointer leaving the chart takes the tooltip away.
    if (!el || event.type === "pointermove") return;
    if (chart instanceof Element && event.relatedTarget instanceof Node && chart.contains(event.relatedTarget)) return;
    writeTooltip(el, null);
  });
}
