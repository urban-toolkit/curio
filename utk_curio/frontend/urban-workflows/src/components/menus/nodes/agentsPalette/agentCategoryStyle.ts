import {
  faCircleNodes,
  faClipboardCheck,
  faCube,
  faDatabase,
  faDiagramProject,
  faRobot,
} from "@fortawesome/free-solid-svg-icons";
import type { IconDefinition } from "@fortawesome/fontawesome-svg-core";

/**
 * How an agent's category is drawn: one colour and one glyph per category.
 *
 * **Colour.** The tokens live in `styles/curioTokens.css` as the
 * `--curio-category-agent-*` family; this file only names which key a category
 * uses. Three of the five alias an existing colour because the tie is honest
 * (data is the data blue, evaluate the computation purple, package the package
 * grey) and two are the family's own (canvas indigo, node rose).
 *
 * This file has been wrong twice, in opposite directions, and both are worth
 * remembering:
 *
 * 1. It first declared five hues of its own, taken from a design concept -
 *    canvas orange, data green, node blue, evaluate purple, package teal. Each
 *    was within a few percent of a token that already existed (`#4caf72`
 *    beside GeoJSON's `#2F8F4A`, `#5b9bd5` beside data's `#3498db`, `#9b7fda`
 *    beside computation's `#8e44ad`, `#26c6da` beside vis's `#1abc9c`), which
 *    is the drift `curioTokens.css` was written to end.
 * 2. The fix over-corrected: all five folded onto the node buckets, so `node`
 *    and `package` both painted the neutral grey and `canvas` the dataflow
 *    slate. 16 of the 21 built-ins came out grey or near-grey and the tile
 *    stopped carrying information at all.
 *
 * **Glyph.** Colour was never the only problem: every agent surface drew the
 * same `faRobot`, so 21 cards showed 21 identical robots. The glyph now varies
 * by category, and it reuses the vocabulary the catalog already established -
 * `faDatabase` is a dataset, `faCube` a package, `faDiagramProject` a dataflow
 * - so an icon means one thing here too. `faRobot` stays as the *kind* icon
 * for "an agent" in general (`CatalogKindVisuals`) and in the chat surfaces,
 * where the subject is one known agent and the category adds nothing.
 */

/** The manifest's category vocabulary (`docs/schemas/agent-package.v1.json`). */
export type AgentCategory = "data" | "node" | "canvas" | "package" | "evaluate";

/**
 * The palette key a category paints with, and the suffix of its CSS-module
 * class (`.avatar_canvas`) and its token family
 * (`--curio-category-agent-canvas-*`).
 */
export type AgentPaletteKey = AgentCategory;

/** The key used for a category that is absent or outside the vocabulary. */
export const AGENT_CATEGORY_FALLBACK: AgentPaletteKey = "package";

/** Every key the palette declares, in the order the docs list them. */
export const AGENT_CATEGORY_KEYS: readonly AgentPaletteKey[] = [
  "node",
  "canvas",
  "data",
  "evaluate",
  "package",
];

/**
 * Category to glyph.
 *
 * - `data` is the dataset glyph: it acts on data.
 * - `package` is the package cube: it acts on node packages.
 * - `canvas` is the dataflow glyph: the canvas *is* the dataflow.
 * - `node` is a node graph, for an agent scoped to one node.
 * - `evaluate` is a checked clipboard: it reviews rather than acts.
 */
export const AGENT_CATEGORY_ICON: Record<AgentPaletteKey, IconDefinition> = {
  data: faDatabase,
  package: faCube,
  canvas: faDiagramProject,
  node: faCircleNodes,
  evaluate: faClipboardCheck,
};

/** The glyph for "an agent", where the category is not the point. */
export const AGENT_KIND_ICON: IconDefinition = faRobot;

/**
 * Normalize any category-ish string to its palette key (case-insensitive).
 *
 * Never returns a key with no rule behind it: an unknown value takes the
 * neutral, the same way the canvas falls back to its neutral border rather
 * than rendering a node unstyled.
 */
export function agentCategoryKey(category: string | null | undefined): AgentPaletteKey {
  if (!category) return AGENT_CATEGORY_FALLBACK;
  const key = category.toLowerCase() as AgentCategory;
  return AGENT_CATEGORY_KEYS.includes(key) ? key : AGENT_CATEGORY_FALLBACK;
}

/** The glyph for a category-ish string, with the same fallback. */
export function agentCategoryIcon(category: string | null | undefined): IconDefinition {
  return AGENT_CATEGORY_ICON[agentCategoryKey(category)];
}
