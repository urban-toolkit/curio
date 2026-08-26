import type { NodeCategoryKey } from "../../../../constants/nodeCategoryPalette";

/**
 * An agent's category, mapped onto the colour buckets Curio already has.
 *
 * Colour has to mean one thing across the whole app. The node-category palette
 * (`constants/nodeCategoryPalette.ts`) already fixes what blue, purple and the
 * neutral grey mean, and the projects list already fixes the dataflow slate,
 * so an agent that acts on data is the SAME blue as a data node rather than a
 * near-miss of it.
 *
 * This file used to declare five hues of its own - canvas orange, data green,
 * node blue, evaluate purple, package teal - taken from a design concept. Each
 * was within a few percent of a token that already existed (`#4caf72` beside
 * GeoJSON's `#2F8F4A`, `#5b9bd5` beside data's `#3498db`, `#9b7fda` beside
 * computation's `#8e44ad`, `#26c6da` beside vis's `#1abc9c`), which is exactly
 * the drift `styles/curioTokens.css` was written to end: the format palette had
 * been copied into five stylesheets with five different values.
 *
 * Two categories sharing a bucket is normal here, not a compromise:
 * `NODE_CATEGORY_KEY` already folds `vis_grammar` + `vis_simple` onto `vis`
 * and `flow` onto `package`.
 */

/** The manifest's category vocabulary (`docs/schemas/agent-package.v1.json`). */
export type AgentCategory = "data" | "node" | "canvas" | "package" | "evaluate";

/**
 * The palette bucket a category paints with. `dataflow` is not a node category
 * - it is the catalog *kind* colour the projects list uses for a dataflow,
 * which is what a canvas-scoped agent acts on.
 */
export type AgentPaletteKey = NodeCategoryKey | "dataflow";

/**
 * Category to bucket.
 *
 * - `data` keeps the data-node blue: same domain, same colour.
 * - `evaluate` is analysis, which is what computation's purple already means.
 * - `canvas` acts on the dataflow, so it takes the dataflow slate.
 * - `node` and `package` both act on node packages, so both take the neutral.
 */
export const AGENT_CATEGORY_KEY: Record<AgentCategory, AgentPaletteKey> = {
  data: "data",
  evaluate: "computation",
  canvas: "dataflow",
  node: "package",
  package: "package",
};

/** The bucket used for a category that is absent or outside the vocabulary. */
export const AGENT_CATEGORY_FALLBACK: AgentPaletteKey = "package";

/**
 * Normalize any category-ish string to its palette bucket (case-insensitive).
 *
 * Never returns a key with no rule behind it: an unknown value takes the
 * neutral, the same way the canvas falls back to its neutral border rather
 * than rendering a node unstyled.
 */
export function agentCategoryKey(category: string | null | undefined): AgentPaletteKey {
  if (!category) return AGENT_CATEGORY_FALLBACK;
  const key = category.toLowerCase() as AgentCategory;
  return AGENT_CATEGORY_KEY[key] ?? AGENT_CATEGORY_FALLBACK;
}
