import type { CatalogItemKind } from "../catalog/CatalogKindVisuals";

/** One of Curio's top-level sections, as the top bar names it. */
export interface AppSection {
  /** The full name: the link's or button's accessible name and its tooltip. */
  name: string;
  /** What the bar writes beside the icon while it has the room. */
  shortName: string;
  /** Picks the glyph, the one the section's own cards wear. */
  kind: CatalogItemKind;
  path: string;
  /** Lit on `path` alone. Without it, the pages under `path` light it too. */
  end: boolean;
  /** The canvas bar has a button that opens its drawer over the dataflow. */
  onCanvas: boolean;
}

export const PROJECTS_SECTION: AppSection = {
  name: "Projects",
  shortName: "Projects",
  kind: "dataflow",
  path: "/projects",
  end: true,
  onCanvas: false,
};

/**
 * The catalogs, in the order both bars list them: the section pages link to
 * each page, the canvas opens each drawer.
 */
export const CATALOG_SECTIONS: ReadonlyArray<AppSection> = [
  { name: "Node Catalog", shortName: "Node", kind: "package", path: "/catalog/nodes", end: true, onCanvas: true },
  // Not `end`: /catalog/data/:datasetId keeps it lit.
  { name: "Data Catalog", shortName: "Data", kind: "dataset", path: "/catalog/data", end: false, onCanvas: true },
  { name: "Agent Catalog", shortName: "Agent", kind: "agent", path: "/catalog/agents", end: true, onCanvas: true },
  // A page with no canvas button: on the canvas a skill is reached through an
  // agent's details. A skill's details are a modal, never a route of their own.
  { name: "Skill Catalog", shortName: "Skill", kind: "skill", path: "/catalog/skills", end: true, onCanvas: false },
  // Not `end`: /catalog/discovery/:sourceDir keeps it lit.
  { name: "Discovery Catalog", shortName: "Discovery", kind: "source", path: "/catalog/discovery", end: false, onCanvas: true },
  // Not `end`: /catalog/models/:modelId keeps it lit.
  { name: "Model Catalog", shortName: "Model", kind: "model", path: "/catalog/models", end: false, onCanvas: true },
  // Not `end`: /catalog/scenarios/:projectId/:scenarioId keeps it lit.
  { name: "Scenario Catalog", shortName: "Scenario", kind: "scenario", path: "/catalog/scenarios", end: false, onCanvas: true },
];
