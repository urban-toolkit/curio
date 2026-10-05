import type { ScenarioRow } from "./scenarioCatalogTypes";

/** What a scenario card puts on a drag: which scenario, of which project. */
export interface ScenarioDragPayload {
  projectId: string;
  scenarioId: string;
  name: string;
}

export const SCENARIO_DRAG_MIME = "application/x-curio-scenario";
const SCENARIO_DRAG_PLAIN_PREFIX = "curio-scenario:";

/** In-memory payload for the current drag (HTML5 getData is unreliable for custom MIME). */
let activeScenarioDrag: ScenarioDragPayload | null = null;

export function createScenarioDragPayload(row: ScenarioRow): ScenarioDragPayload {
  return { projectId: row.project.id, scenarioId: row.id, name: row.name };
}

function parseScenarioDragJson(raw: string): ScenarioDragPayload | null {
  if (!raw) return null;
  try {
    const payload = JSON.parse(raw) as Partial<ScenarioDragPayload>;
    if (!payload.projectId || !payload.scenarioId) return null;
    return { projectId: payload.projectId, scenarioId: payload.scenarioId, name: payload.name ?? "" };
  } catch {
    return null;
  }
}

/** Call from `dragStart` on a scenario card. */
export function beginScenarioDrag(row: ScenarioRow): ScenarioDragPayload {
  activeScenarioDrag = createScenarioDragPayload(row);
  return activeScenarioDrag;
}

/** Call from `dragEnd` so a stale payload is not reused. */
export function endScenarioDrag(): void {
  activeScenarioDrag = null;
}

/** Write drag data (custom MIME + text/plain fallback for the drop handler). */
export function writeScenarioDragData(dataTransfer: DataTransfer, payload: ScenarioDragPayload): void {
  const json = JSON.stringify(payload);
  dataTransfer.setData(SCENARIO_DRAG_MIME, json);
  dataTransfer.setData("text/plain", `${SCENARIO_DRAG_PLAIN_PREFIX}${json}`);
  dataTransfer.effectAllowed = "copy";
}

export function readScenarioDragPayload(dataTransfer: DataTransfer): ScenarioDragPayload | null {
  if (activeScenarioDrag) return activeScenarioDrag;
  const fromMime = parseScenarioDragJson(dataTransfer.getData(SCENARIO_DRAG_MIME));
  if (fromMime) return fromMime;
  const plain = dataTransfer.getData("text/plain");
  if (plain.startsWith(SCENARIO_DRAG_PLAIN_PREFIX)) {
    return parseScenarioDragJson(plain.slice(SCENARIO_DRAG_PLAIN_PREFIX.length));
  }
  return null;
}

export function hasScenarioDrag(dataTransfer: DataTransfer): boolean {
  if (activeScenarioDrag) return true;
  return Array.from(dataTransfer.types || []).includes(SCENARIO_DRAG_MIME);
}
