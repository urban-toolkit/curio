import type { ScenarioRow } from "../../services/scenarioCatalog";

/** Where a scenario's project came from. */
export type ScenarioOrigin = "yours" | "example";

export function scenarioOrigin(row: Pick<ScenarioRow, "project">): ScenarioOrigin {
  return row.project.isExample ? "example" : "yours";
}

/**
 * The "By origin" rows on `/catalog/scenarios`, mirroring
 * `pages/models/modelBrowseConstants.ts`.
 *
 * Declared rather than derived from the rows so the ORDER is stable; the
 * counts still come from the rows, and an origin with no scenario is hidden by
 * the rail.
 */
export const ORIGIN_FILTERS: { value: ScenarioOrigin; label: string }[] = [
  { value: "yours", label: "Your dataflows" },
  { value: "example", label: "Examples" },
];
