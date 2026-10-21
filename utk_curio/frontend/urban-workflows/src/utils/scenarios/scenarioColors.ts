/**
 * How a chart names and colors scenarios (#662): the label an input's rows
 * carry (the id, name and color of the scenario box its node is in, or, for a
 * node in no box, the node's name and a neutral color), the columns stacked
 * rows carry them in, and the scale the scenario chips write
 * (utils/references/codeReferences): the labels in the boxes' order, their
 * names and their colors, and the shades a text mark reads in.
 *
 * Pure, with no `vega` / `vega-lite` import, so it is testable under jest.
 */
import { SCENARIO_COLOR_RE } from "./scenarioModel";

/** What an input's rows are named and drawn by. */
export interface ScenarioLabel {
  /** The scenario's id; absent for a node in no scenario. */
  scenario?: string;
  name: string;
  /** A CSS hex color, `#rrggbb`. */
  color: string;
  /** Where its box is in the dataflow's list of boxes, counted from 0, which
   * orders the scenario chips; absent for a node in no scenario. */
  rank?: number;
}

/** The color of an input whose node is in no scenario. */
export const NO_SCENARIO_COLOR = "#8a8f98";

/** The columns stacked rows name their scenario in (`scenario_stack.py`). */
export const SCENARIO_FIELD = "scenario";
export const SCENARIO_NAME_FIELD = "scenario_name";

/**
 * The labels the scenario chips list, from *labels*, each wired input's in
 * circle order: each box once, in the order the dataflow lists the boxes (its
 * `rank`), then each input from no box, in circle order. Kept in sync with
 * `scale_labels` in `code_references.py`.
 */
export function scaleLabels(labels: readonly ScenarioLabel[]): ScenarioLabel[] {
  const boxes = new Map<string, ScenarioLabel>();
  for (const label of labels) {
    if (label.scenario != null && !boxes.has(label.scenario)) boxes.set(label.scenario, label);
  }
  const rank = (label: ScenarioLabel) => label.rank ?? Number.MAX_SAFE_INTEGER;
  return [
    ...[...boxes.values()].sort((a, b) => rank(a) - rank(b)),
    ...labels.filter((label) => label.scenario == null),
  ];
}

/** The scenarios' names and colors, each name once, in the order of *labels*. */
export function scenarioScale(labels: readonly ScenarioLabel[]): { domain: string[]; range: string[] } {
  const domain: string[] = [];
  const range: string[] = [];
  for (const label of labels) {
    if (domain.includes(label.name)) continue;
    domain.push(label.name);
    range.push(label.color);
  }
  return { domain, range };
}

/**
 * A table writes its text in the scenarios' colors, and a light one reads pale
 * on white (#a1d99b is 1.6:1). So a color under TABLE_TEXT_CONTRAST, WCAG's
 * 3:1 for large text, is drawn in its lightest shade that reaches it, taking
 * TABLE_TEXT_SHADE_STEP percent toward black at a time: the text keeps its
 * scenario's hue, and the scenario keeps its color everywhere else. Curio's
 * own scenario colors all reach 3:1.
 */
const TABLE_TEXT_CONTRAST = 3;
const TABLE_TEXT_SHADE_STEP = 1;

function contrastOnWhite(channels: readonly number[]): number {
  const [r, g, b] = channels.map((channel) => {
    const value = channel / 255;
    return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
  });
  return 1.05 / (0.2126 * r + 0.7152 * g + 0.0722 * b + 0.05);
}

/** *color* as a table's text draws it: itself when it reads on white, else its
 * lightest shade that does. The `[!! scenario text_colors !!]` chip writes
 * these. Kept in sync with `table_text_color` in `code_references.py`. */
export function tableTextColor(color: string): string {
  if (!SCENARIO_COLOR_RE.test(color)) return color;
  const channels = [1, 3, 5].map((at) => parseInt(color.slice(at, at + 2), 16));
  for (let left = 100; left > 0; left -= TABLE_TEXT_SHADE_STEP) {
    const shade = channels.map((channel) => Math.round((channel * left) / 100));
    if (contrastOnWhite(shade) < TABLE_TEXT_CONTRAST) continue;
    return left === 100 ? color : `#${shade.map((channel) => channel.toString(16).padStart(2, "0")).join("")}`;
  }
  return "#000000";
}
