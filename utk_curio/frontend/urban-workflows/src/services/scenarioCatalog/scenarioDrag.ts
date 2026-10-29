import type { ScenarioRow } from "./scenarioCatalogTypes";

/** What a scenario card puts on a drag: which scenarios, of which set of
 *  which project. A card of no set (`setId` "") drags its scenario alone. */
export interface ScenarioDragPayload {
  projectId: string;
  setId: string;
  setName: string;
  scenarioIds: string[];
  names: string[];
}

export const SCENARIO_DRAG_MIME = "application/x-curio-scenario";
const SCENARIO_DRAG_PLAIN_PREFIX = "curio-scenario:";

/** In-memory payload for the current drag (HTML5 getData is unreliable for custom MIME). */
let activeScenarioDrag: ScenarioDragPayload | null = null;

/** The drag of *rows*, all of one set of one project. */
export function createScenarioDragPayload(rows: readonly ScenarioRow[]): ScenarioDragPayload {
  const [first] = rows;
  return {
    projectId: first.project.id,
    setId: first.set?.id ?? "",
    setName: first.set?.name || first.project.name,
    scenarioIds: rows.map((row) => row.id),
    names: rows.map((row) => row.name),
  };
}

function parseScenarioDragJson(raw: string): ScenarioDragPayload | null {
  if (!raw) return null;
  try {
    const payload = JSON.parse(raw) as Partial<ScenarioDragPayload>;
    if (!payload.projectId || !Array.isArray(payload.scenarioIds) || payload.scenarioIds.length === 0) return null;
    return {
      projectId: payload.projectId,
      setId: payload.setId ?? "",
      setName: payload.setName ?? "",
      scenarioIds: payload.scenarioIds,
      names: payload.names ?? [],
    };
  } catch {
    return null;
  }
}

/** Call from `dragStart` on a scenario card, with the scenarios it drags. */
export function beginScenarioDrag(rows: readonly ScenarioRow[]): ScenarioDragPayload {
  activeScenarioDrag = createScenarioDragPayload(rows);
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
