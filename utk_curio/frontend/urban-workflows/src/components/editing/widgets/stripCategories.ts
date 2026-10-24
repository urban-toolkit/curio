/**
 * Which categories of a node's header are open, and which lists under its
 * Inputs (#662). The header above a node's code or spec lists the chips the
 * node can use in one row of categories, all closed until one is clicked, and
 * one open at a time: opening a category closes the one open. Inputs holds a
 * line per input, each opening to its list, and several lists can be open. A
 * category or a list opened stays open for its node while the dataflow is
 * open, so a tab switch, the notebook view or the node's editor mounting again
 * keeps it; opening another dataflow closes them all (`closeEveryCategory`,
 * called by ProjectLoader).
 *
 * Kept outside React, by node id, since a node's editor mounts again on its
 * own. A header with no node id keeps its categories and lists as long as it
 * is mounted.
 */
import { useCallback, useState, useSyncExternalStore } from "react";

/** The header's categories, in its row's order. */
export const STRIP_CATEGORIES = ["inputs", "scenarios", "widgets", "selections", "shared"] as const;
export type StripCategory = (typeof STRIP_CATEGORIES)[number];

const NONE: ReadonlySet<StripCategory> = new Set();
const NO_LISTS: ReadonlySet<string> = new Set();

let opened = new Map<string, ReadonlySet<StripCategory>>();
/** The lists open under each node's Inputs, by node id: an input's circle, or
 * `inputs` for the fields of the dataset that stacks them. */
let openLists = new Map<string, ReadonlySet<string>>();
const listeners = new Set<() => void>();

function notify(): void {
  for (const listener of listeners) listener();
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** *open* with *item* opened or closed. */
function toggled<T>(open: ReadonlySet<T>, item: T): ReadonlySet<T> {
  const next = new Set(open);
  if (next.has(item)) next.delete(item);
  else next.add(item);
  return next;
}

/** *item* alone open, or nothing when *item* was: one category of a header at a time. */
function alone<T>(open: ReadonlySet<T>, item: T): ReadonlySet<T> {
  return open.has(item) ? new Set() : new Set([item]);
}

/** The categories open in node *nodeId*'s header. */
export function openCategoriesOf(nodeId: string): ReadonlySet<StripCategory> {
  return opened.get(nodeId) ?? NONE;
}

/** Opens *category* in node *nodeId*'s header, closing the one open there, or closes it when it is open. */
export function toggleCategory(nodeId: string, category: StripCategory): void {
  opened = new Map(opened).set(nodeId, alone(openCategoriesOf(nodeId), category));
  notify();
}

/** The lists open under Inputs in node *nodeId*'s header. */
export function openListsOf(nodeId: string): ReadonlySet<string> {
  return openLists.get(nodeId) ?? NO_LISTS;
}

/** Opens the list *list* under Inputs in node *nodeId*'s header, or closes it when it is open. */
export function toggleList(nodeId: string, list: string): void {
  openLists = new Map(openLists).set(nodeId, toggled(openListsOf(nodeId), list));
  notify();
}

/** Closes every node's categories and lists: another dataflow is open. */
export function closeEveryCategory(): void {
  if (opened.size === 0 && openLists.size === 0) return;
  opened = new Map();
  openLists = new Map();
  notify();
}

/** What is open in node *nodeId*'s header, read by *read*, and a toggle for
 * one of them; *none* when nothing is. With no node id, kept while mounted,
 * where *change* says what a toggle leaves open, as *toggle* does by node. */
function useOpenIn<T>(
  nodeId: string | null | undefined,
  read: (nodeId: string) => ReadonlySet<T>,
  toggle: (nodeId: string, item: T) => void,
  none: ReadonlySet<T>,
  change: (open: ReadonlySet<T>, item: T) => ReadonlySet<T>,
): [ReadonlySet<T>, (item: T) => void] {
  const [own, setOwn] = useState<ReadonlySet<T>>(none);
  const kept = useSyncExternalStore(
    subscribe,
    () => (nodeId ? read(nodeId) : none),
    () => none,
  );
  const flip = useCallback(
    (item: T) => {
      if (nodeId) toggle(nodeId, item);
      else setOwn((open) => change(open, item));
    },
    [nodeId],
  );
  return [nodeId ? kept : own, flip];
}

/** The category open in node *nodeId*'s header, if any, and a toggle for one. */
export function useOpenCategories(
  nodeId?: string | null,
): [ReadonlySet<StripCategory>, (category: StripCategory) => void] {
  return useOpenIn(nodeId, openCategoriesOf, toggleCategory, NONE, alone);
}

/** The lists open under Inputs in node *nodeId*'s header, and a toggle for one. */
export function useOpenLists(nodeId?: string | null): [ReadonlySet<string>, (list: string) => void] {
  return useOpenIn(nodeId, openListsOf, toggleList, NO_LISTS, toggled);
}
