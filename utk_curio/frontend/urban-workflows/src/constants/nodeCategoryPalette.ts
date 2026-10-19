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
 * reintroduces a hex. It maps categories to colours and names no node type:
 * a node's category is the one its template declares.
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

/** The neutral used for a node with no category, or one with no bucket. */
export const CATEGORY_FALLBACK_FG = categoryFg("package");

/**
 * The colour of a node in *category*: the canvas border reads its descriptor's,
 * and a dataflow's thumbnail the one its preview carries, which is what the
 * node's template declares, read as written. So only the palette's own
 * categories count; anything else, or none, is the neutral.
 */
export function colorForCategory(category: string | null | undefined): string {
  return category && Object.prototype.hasOwnProperty.call(NODE_CATEGORY_KEY, category)
    ? categoryFg(NODE_CATEGORY_KEY[category as NodeCategory])
    : CATEGORY_FALLBACK_FG;
}
