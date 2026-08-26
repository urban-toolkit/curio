/**
 * Maps an agent's `category` to a palette color key used for its row chip and
 * avatar tint (see `AgentPaletteRow.module.css`). Categories mirror the manifest
 * contract (`data | node | canvas | package | evaluate`); anything absent or
 * unexpected falls back to a neutral key so a row never renders unstyled.
 *
 * Colors follow the approved concept (`png-concepts/11-agents-palette.png`):
 * canvas=orange, data=green, node=blue, evaluate=purple, package=teal.
 */
export type AgentCategoryKey =
  | "canvas"
  | "data"
  | "node"
  | "evaluate"
  | "package"
  | "default";

const KNOWN: Record<string, AgentCategoryKey> = {
  canvas: "canvas",
  data: "data",
  node: "node",
  evaluate: "evaluate",
  package: "package",
};

/** Normalize a category to its color key (case-insensitive; unknown → "default"). */
export function agentCategoryKey(category: string | null | undefined): AgentCategoryKey {
  if (!category) return "default";
  return KNOWN[category.toLowerCase()] ?? "default";
}
