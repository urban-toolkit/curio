/**
 * Which view a Compare Scenarios node (#662) is in: Chart, its inputs stacked
 * and charted, or Difference, its second input minus its first.
 *
 * The user's choice (`metadata.compareScenarios.mode`) wins. Without one the
 * node picks: Difference for exactly two rasters or two layers, Chart for
 * anything else. An input's kind is read from the value its circle holds,
 * which it holds once the node feeding it has run or its output was restored;
 * until every input has one, the node keeps the view its code was written for.
 *
 * Pure, so it is testable under jest.
 */
import { modeOfCode } from "./compareCode";
import type { CompareMode, CompareSettings } from "./compareSettings";

/** What an input is, as far as the node's choice goes. */
export type InputKind = "raster" | "layer" | "table" | "other";

/** The kind of the value an input circle holds, or null while it holds none. */
export function inputKind(value: unknown): InputKind | null {
  if (value == null || value === "") return null;
  const type = typeof value === "object" ? (value as { dataType?: unknown }).dataType : undefined;
  if (type === "raster") return "raster";
  if (type === "geodataframe") return "layer";
  if (type === "dataframe") return "table";
  return "other";
}

/** The kinds of the values *slots* holds for the *wired* circles, in circle order. */
export function inputKinds(slots: unknown, wired: readonly number[]): (InputKind | null)[] {
  const values = Array.isArray(slots) ? slots : [];
  return wired.map((slot) => inputKind(values[slot]));
}

/**
 * The view the node picks for inputs of these kinds: Difference for exactly
 * two rasters or two layers, Chart otherwise, and null while it has no input
 * or an input's kind is not known (a project load adds the edges, and then the
 * restored outputs, after the nodes).
 */
export function automaticMode(kinds: readonly (InputKind | null)[]): CompareMode | null {
  if (kinds.length === 0 || kinds.some((kind) => kind === null)) return null;
  const [first, second] = kinds;
  if (kinds.length === 2 && first === second && (first === "raster" || first === "layer")) return "difference";
  return "chart";
}

/** The view the node's code should be written for, or null to keep it as it is. */
export function wantedMode(settings: CompareSettings | undefined, kinds: readonly (InputKind | null)[]): CompareMode | null {
  return settings?.mode ?? automaticMode(kinds);
}

/**
 * The view the node is in: the one it wants, else the one its code was
 * written for, else Chart. `chosen` says the user picked it.
 */
export function resolveMode(
  settings: CompareSettings | undefined,
  kinds: readonly (InputKind | null)[],
  code: string | undefined,
): { mode: CompareMode; chosen: boolean } {
  if (settings?.mode) return { mode: settings.mode, chosen: true };
  return { mode: automaticMode(kinds) ?? modeOfCode(code ?? "") ?? "chart", chosen: false };
}
