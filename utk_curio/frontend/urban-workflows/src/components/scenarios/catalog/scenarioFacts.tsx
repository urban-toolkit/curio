import React from "react";

import { tryGetNodeDescriptor } from "../../../registry/nodeRegistry";
import type {
  ScenarioDetails,
  ScenarioNodeEntry,
  ScenarioResult,
  ScenarioRow,
} from "../../../services/scenarioCatalog";
import type { ThumbnailHighlight } from "../../DataflowThumbnail";
import styles from "./scenarioFacts.module.css";

/**
 * What the Scenario Catalog says about one scenario, for its browse card and
 * drawer, its canvas card and its details view alike, as `modelFacts` is for
 * a model: none of them can word a scenario differently from another.
 */

export interface ScenarioFact {
  label: string;
  value: React.ReactNode;
}

/** The scenario's colour, as a small square. */
export const ScenarioSwatch: React.FC<{ color: string }> = ({ color }) => (
  <span
    className={styles.swatch}
    style={{ "--scenario-color": color } as React.CSSProperties}
    data-curio-scenario-swatch="true"
    aria-hidden
  />
);

/** A scenario's name with its swatch in front. */
export const ScenarioName: React.FC<{ row: Pick<ScenarioRow, "name" | "color"> }> = ({ row }) => (
  <span className={styles.named}>
    <ScenarioSwatch color={row.color} />
    <span>{row.name}</span>
  </span>
);

/** `"3 nodes"`, singular for one. */
export function scenarioNodeCount(row: Pick<ScenarioRow, "nodeCount">): string {
  return `${row.nodeCount} ${row.nodeCount === 1 ? "node" : "nodes"}`;
}

/** How many scenarios a project's group holds: `"2 scenarios"`, singular for
 *  one. */
export function scenarioCount(count: number): string {
  return `${count} ${count === 1 ? "scenario" : "scenarios"}`;
}

/** Where its project came from: one of Curio's examples, or the account's own. */
export function scenarioOriginLabel(row: Pick<ScenarioRow, "project">): string {
  return row.project.isExample ? "Example" : "Your dataflow";
}

/** The canvas route of the project a scenario lives in. */
export function scenarioProjectPath(projectId: string): string {
  return `/dataflow/${encodeURIComponent(projectId)}`;
}

/** The project graph's marks: the levers in the scenario's colour, the fixed
 *  context dashed. */
export function scenarioHighlight(details: ScenarioDetails): ThumbnailHighlight {
  return {
    color: details.color,
    members: details.levers.map((entry) => entry.id),
    context: details.context.map((entry) => entry.id),
  };
}

/** `"curio.builtin/vis-vega@1"` to `"vis-vega"`. */
function templateName(type: string): string {
  return type.replace(/@\d+$/, "").split("/").pop() ?? type;
}

/** What a node is called: its own title, else its template's label when the
 *  node registry knows the template, else the template's name. */
export function scenarioNodeLabel(entry: Pick<ScenarioNodeEntry, "id" | "type" | "label">): string {
  const title = entry.label?.trim();
  if (title) return title;
  const descriptor = entry.type ? tryGetNodeDescriptor(entry.type) : undefined;
  if (descriptor?.label) return descriptor.label;
  return (entry.type && templateName(entry.type)) || entry.id;
}

function countLabel(count: number, one: string, many: string): string {
  return `${count.toLocaleString("en-US")} ${count === 1 ? one : many}`;
}

/** One saved output: `"Parcels · GeoJSON · 1,204 features"`. */
export function scenarioResultLine(result: ScenarioResult): string {
  const size =
    result.featureCount != null
      ? countLabel(result.featureCount, "feature", "features")
      : result.rowCount != null
        ? countLabel(result.rowCount, "row", "rows")
        : null;
  return [result.title || result.datasetId, result.format, size].filter(Boolean).join(" · ");
}

/** The rows the browse drawer and the details view both list. The counts of
 *  the shared context and the outcomes need the scenario's details. A scenario
 *  of the open dataflow (`origin: false`) has no origin to tell: the canvas
 *  does not know whether its dataflow came from an example. */
export function scenarioInfoRows(
  row: ScenarioRow,
  details?: ScenarioDetails | null,
  { origin = true }: { origin?: boolean } = {},
): ScenarioFact[] {
  const rows: (ScenarioFact | null)[] = [
    { label: "Project", value: row.project.name },
    origin ? { label: "Origin", value: scenarioOriginLabel(row) } : null,
    row.set?.name ? { label: "Set", value: row.set.name } : null,
    { label: "Scenario nodes", value: String(row.nodeCount) },
    details ? { label: "Shared context", value: String(details.context.length) } : null,
    details ? { label: "Shared outcomes", value: String(details.outcomes.length) } : null,
  ];
  return rows.filter((fact): fact is ScenarioFact => fact != null);
}

/** One section of the details view: its nodes, each with its saved outputs.
 *  Without *results*, the nodes alone: a scenario read off the canvas, whose
 *  outputs may not be saved yet. */
export const ScenarioNodeList: React.FC<{
  entries: ScenarioNodeEntry[];
  /** What an empty section says. */
  empty?: string;
  results?: boolean;
}> = ({ entries, empty = "None.", results = true }) => {
  if (entries.length === 0) return <p className={styles.none}>{empty}</p>;
  return (
    <ul className={styles.nodeList}>
      {entries.map((entry) => (
        <li key={entry.id} className={styles.nodeItem} data-scenario-node-id={entry.id}>
          <span className={styles.nodeLabel}>{scenarioNodeLabel(entry)}</span>
          {!results ? null : entry.results.length > 0 ? (
            <ul className={styles.resultList}>
              {entry.results.map((result) => (
                <li key={result.datasetId}>{scenarioResultLine(result)}</li>
              ))}
            </ul>
          ) : (
            <p className={styles.noOutput}>No saved output</p>
          )}
        </li>
      ))}
    </ul>
  );
};
