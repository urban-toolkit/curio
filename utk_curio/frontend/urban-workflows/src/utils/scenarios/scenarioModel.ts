/**
 * A dataflow's scenarios (#662), at `dataflow.scenarios`: named selections of
 * its nodes. What enters a scenario from outside is its fixed context, its
 * nodes are its levers, and the outputs of its last nodes are its outcomes.
 *
 * A node belongs to at most one scenario. The backend refuses a save that
 * puts one node in two; `normalizeScenarios` keeps it with the first, so a
 * canvas never holds such a list. It is the twin of `normalize_scenarios` in
 * `utk_curio/backend/app/projects/scenarios.py`, and both read
 * `scenarios.cases.json`.
 */

export interface Scenario {
  id: string;
  name: string;
  /** A CSS hex color, `#rrggbb`. */
  color: string;
  description?: string;
  /** Its nodes' ids. Empty once its last node is deleted. */
  nodes: string[];
  collapsed?: boolean;
  /** Where its collapsed box sits on the canvas. */
  box?: { x: number; y: number };
  /** The project and scenario it was dragged in from. */
  source?: { project: string; scenario: string };
}

/** Kept in sync with `COLOR_RE` in `scenarios.py`. */
export const SCENARIO_COLOR_RE = /^#[0-9a-fA-F]{6}$/;

const isNumber = (v: unknown): v is number => typeof v === "number" && !Number.isNaN(v);
const nonEmpty = (v: unknown): v is string => typeof v === "string" && v.length > 0;

function wellFormed(entry: unknown): entry is Record<string, unknown> & { id: string; name: string; color: string } {
  if (!entry || typeof entry !== "object" || Array.isArray(entry)) return false;
  const e = entry as Record<string, unknown>;
  return (
    nonEmpty(e.id) &&
    typeof e.name === "string" &&
    e.name.trim().length > 0 &&
    typeof e.color === "string" &&
    SCENARIO_COLOR_RE.test(e.color)
  );
}

function members(entry: Record<string, unknown>): string[] {
  const out: string[] = [];
  if (!Array.isArray(entry.nodes)) return out;
  for (const id of entry.nodes) {
    if (nonEmpty(id) && !out.includes(id)) out.push(id);
  }
  return out;
}

/**
 * The scenarios in *raw* as a spec keeps them. An entry without an id, a name
 * or a color is dropped, and so is a second entry with the same id. Members
 * are kept once each, only when *nodeIds* has them, and only in the first
 * scenario that names them. Optional fields are kept when well formed.
 */
export function normalizeScenarios(raw: unknown, nodeIds: Iterable<string>): Scenario[] {
  const nodes = new Set(nodeIds);
  const out: Scenario[] = [];
  const seenIds = new Set<string>();
  const claimed = new Set<string>();
  for (const entry of Array.isArray(raw) ? raw : []) {
    if (!wellFormed(entry) || seenIds.has(entry.id)) continue;
    seenIds.add(entry.id);
    const kept = members(entry).filter((id) => nodes.has(id) && !claimed.has(id));
    kept.forEach((id) => claimed.add(id));
    const scenario: Scenario = { id: entry.id, name: entry.name, color: entry.color, nodes: kept };
    if (nonEmpty(entry.description)) scenario.description = entry.description;
    if (typeof entry.collapsed === "boolean") scenario.collapsed = entry.collapsed;
    const box = entry.box as Record<string, unknown> | undefined;
    if (box && typeof box === "object" && isNumber(box.x) && isNumber(box.y)) {
      scenario.box = { x: box.x, y: box.y };
    }
    const source = entry.source as Record<string, unknown> | undefined;
    if (source && typeof source === "object" && nonEmpty(source.project) && nonEmpty(source.scenario)) {
      scenario.source = { project: source.project, scenario: source.scenario };
    }
    out.push(scenario);
  }
  return out;
}
