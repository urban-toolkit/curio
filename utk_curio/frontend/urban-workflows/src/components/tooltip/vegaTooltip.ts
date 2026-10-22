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

/** Vega's tooltip handler: the chart element's `data-tooltip`, at the pointer. */
export function vegaTooltipHandler(
  handler: { element(): Element | null },
  _event: unknown,
  _item: unknown,
  value: unknown,
): void {
  const el = handler.element();
  if (!el) return;
  const text = formatVegaTooltip(value);
  if (text) {
    el.setAttribute("data-tooltip", text);
    el.setAttribute("data-tooltip-side", "pointer");
  } else {
    el.removeAttribute("data-tooltip");
  }
}
