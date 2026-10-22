/**
 * Queries by the one Curio tooltip's text: the `data-tooltip` an element
 * writes where it used to write a `title` (components/tooltip). Testing
 * Library's ByTitle queries read the attribute the app no longer writes.
 *
 *   getByTooltip(document.body, "Open built-in palette")
 *   getByTooltip(row, /Drag onto a node/)
 *
 * A string matches the whole text, as getByTitle's does; a RegExp matches
 * part of it.
 */
import { buildQueries, queryAllByAttribute, type Matcher, type MatcherOptions } from "@testing-library/react";

export const queryAllByTooltip = (container: HTMLElement, text: Matcher, options?: MatcherOptions) =>
  queryAllByAttribute("data-tooltip", container, text, options);

const [queryByTooltip, getAllByTooltip, getByTooltip, findAllByTooltip, findByTooltip] = buildQueries(
  queryAllByTooltip,
  (_container, text) => `Found more than one element with the tooltip ${String(text)}`,
  (_container, text) => `Found no element with the tooltip ${String(text)}`,
);

export { queryByTooltip, getAllByTooltip, getByTooltip, findAllByTooltip, findByTooltip };
