/**
 * A Vega-Lite chart after a Compare Scenarios node draws the node's scenarios
 * as the node's own chart presets do (`comparePresets.ts`), from the labels its
 * Chart tab draws with:
 *
 * - color, fill and stroke on the stacked table's `scenario_name` get the
 *   scenarios' names as the scale's domain and the colors of their boxes as
 *   its range (`scenarioScale`), a text mark's in the shade the Table preset
 *   writes text in (`tableTextColor`);
 * - x, y, xOffset, yOffset, row, column and facet on it get the names, in the
 *   order of the node's inputs, as their order: as their scale's domain when
 *   the spec writes one, else as their sort.
 *
 * They replace what the spec writes for that column, as a map layer's scenario
 * color replaces a color its layerRef writes (`adapters/node/autkScenarioColors.ts`).
 * Every other channel, and every channel on another column, is kept as
 * written.
 *
 * `scenarioScales.cases.json` holds specs and what they become: Jest checks
 * that this writes exactly that, and `test_compare_scenarios_node.py` checks
 * each against the Vega-Lite schema and the columns it reads.
 *
 * Pure, with no `vega` / `vega-lite` import, so it is testable under jest.
 */
import { SCENARIO_NAME_FIELD, scenarioScale, tableTextColor } from "./comparePresets";
import type { CompareInputLabel } from "./compareSettings";

/** The channels that draw the scenarios in their colors. */
const COLOR_CHANNELS: ReadonlySet<string> = new Set(["color", "fill", "stroke"]);
/** The channels that put the scenarios in order. */
const ORDER_CHANNELS: ReadonlySet<string> = new Set(["x", "y", "xOffset", "yOffset", "row", "column", "facet"]);
/** Where a view holds other views: its layers, its concatenated views, and a facet's or a repeat's spec. */
const VIEW_KEYS = ["layer", "concat", "hconcat", "vconcat", "spec"] as const;

type Json = Record<string, unknown>;

const isObject = (value: unknown): value is Json =>
  typeof value === "object" && value !== null && !Array.isArray(value);

/** *list* with *fn* applied to each item, or *list* itself when no item changed. */
function mapSame(list: readonly unknown[], fn: (item: unknown) => unknown): readonly unknown[] {
  const mapped = list.map(fn);
  return mapped.some((item, i) => item !== list[i]) ? mapped : list;
}

/**
 * *spec* with each channel on `scenario_name` drawn as *labels* say. *spec*
 * itself, unchanged, when there are no labels or no channel it fills reads
 * that column.
 */
export function withScenarioScales(spec: unknown, labels: readonly CompareInputLabel[]): unknown {
  if (labels.length === 0) return spec;
  const { domain, range } = scenarioScale(labels);
  const shades = range.map(tableTextColor);

  /** One channel's definition, its conditions included. */
  const fill = (channel: string, def: unknown, onText: boolean): unknown => {
    if (!isObject(def)) return def;
    let out = def;
    if (def.condition !== undefined) {
      const condition = Array.isArray(def.condition)
        ? mapSame(def.condition, (each) => fill(channel, each, onText))
        : fill(channel, def.condition, onText);
      if (condition !== def.condition) out = { ...def, condition };
    }
    if (out.field !== SCENARIO_NAME_FIELD) return out;
    if (COLOR_CHANNELS.has(channel)) {
      return { ...out, scale: { domain: [...domain], range: onText ? [...shades] : [...range] } };
    }
    if (ORDER_CHANNELS.has(channel)) {
      // A domain the spec writes is the order, over any sort.
      return isObject(out.scale) && out.scale.domain !== undefined
        ? { ...out, scale: { ...out.scale, domain: [...domain] } }
        : { ...out, sort: [...domain] };
    }
    return out;
  };

  /** An encoding, or a facet's row and column. */
  const fillChannels = (channels: unknown, onText: boolean): unknown => {
    if (!isObject(channels)) return channels;
    let out: Json | null = null;
    for (const [channel, def] of Object.entries(channels)) {
      const next = fill(channel, def, onText);
      if (next !== def) (out ??= { ...channels })[channel] = next;
    }
    return out ?? channels;
  };

  const view = (node: unknown): unknown => {
    if (Array.isArray(node)) return mapSame(node, view);
    if (!isObject(node)) return node;
    const mark = isObject(node.mark) ? node.mark.type : node.mark;
    const patch: Json = {};
    const encoding = fillChannels(node.encoding, mark === "text");
    if (encoding !== node.encoding) patch.encoding = encoding;
    // A facet's field, or its row and column fields.
    if (isObject(node.facet)) {
      const facet = "field" in node.facet ? fill("facet", node.facet, false) : fillChannels(node.facet, false);
      if (facet !== node.facet) patch.facet = facet;
    }
    for (const key of VIEW_KEYS) {
      if (node[key] === undefined) continue;
      const inner = view(node[key]);
      if (inner !== node[key]) patch[key] = inner;
    }
    return Object.keys(patch).length > 0 ? { ...node, ...patch } : node;
  };

  return view(spec);
}
