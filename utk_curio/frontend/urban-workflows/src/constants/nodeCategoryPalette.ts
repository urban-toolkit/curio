import type { NodeCategory } from "../registry/types";

/**
 * The node-category colour palette, as CSS custom-property references.
 *
 * Colour on a node means its category, and that has to hold everywhere the
 * node shows up: the left border the canvas paints, the miniature inside a
 * project card's thumbnail, the category pill in the node's own title bar, the
 * package card in the Node Catalog (browse page and canvas drawer), and the
 * category chips in the catalog's filter bar.
 *
 * Those surfaces used to each pick their own colour. Two of them hand-kept
 * copies of the same hex map, the catalog picked one by hashing the package's
 * directory name (so three `data` packages could render in three unrelated
 * colours), and the title-bar pill was a single flat peach for every category.
 *
 * The values live in `src/styles/curioTokens.css` under "Node category
 * palette". Everything here is a `var(--curio-category-*)` reference rather
 * than a literal, so the palette has exactly one definition —
 * `src/tests/styles/nodeCategoryPalette.test.ts` asserts no consumer
 * reintroduces a hex.
 */

/** The four colour buckets. `NodeCategory` has five members; both `vis_*` share one. */
export type NodeCategoryKey = "data" | "computation" | "vis" | "package";

/**
 * `NodeCategory` (the registry's five-member union) collapsed onto the four
 * colour buckets. `flow` rides with `package`: it is the neutral grey that the
 * canvas already used as its fallback border.
 */
export const NODE_CATEGORY_KEY: Record<NodeCategory, NodeCategoryKey> = {
  data: "data",
  computation: "computation",
  vis_grammar: "vis",
  vis_simple: "vis",
  flow: "package",
};

/** Saturated fill: canvas border, card strip, filter chip dot, thumbnail bar. */
export const categoryFg = (key: NodeCategoryKey): string =>
  `var(--curio-category-${key}-fg)`;

/** Tint background for a badge or an icon tile. */
export const categoryBg = (key: NodeCategoryKey): string =>
  `var(--curio-category-${key}-bg)`;

/** Text on that tint. */
export const categoryOnTint = (key: NodeCategoryKey): string =>
  `var(--curio-category-${key}-on-tint)`;

/** The neutral used when a node's type is not in any category bucket. */
export const CATEGORY_FALLBACK_FG = categoryFg("package");

/**
 * Canonical unversioned node types per colour bucket.
 *
 * The canvas keys its border off the node *type* rather than off a category
 * field, because a flow node carries no descriptor at paint time. Keeping the
 * type lists here means the canvas and the projects-list thumbnail read one
 * source instead of two copies that have to be kept in step by hand.
 */
export const NODE_TYPE_CATEGORY: Record<string, NodeCategoryKey> = {
  "curio.builtin/data-loading": "data",
  "curio.builtin/data-export": "data",
  "curio.builtin/data-transformation": "data",
  "curio.builtin/data-summary": "data",
  "curio.builtin/computation-analysis": "computation",
  "curio.builtin/merge-flow": "computation",
  "curio.builtin/data-pool": "computation",
  "curio.builtin/js-computation": "computation",
  "curio.builtin/vis-vega": "vis",
  "curio.builtin/vis-simple": "vis",
  "curio.builtin/autk-grammar": "vis",
};

/** Border/accent colour for a node type, falling back to the neutral. */
export function colorForNodeType(unversioned: string): string {
  const key = NODE_TYPE_CATEGORY[unversioned];
  return key ? categoryFg(key) : CATEGORY_FALLBACK_FG;
}
