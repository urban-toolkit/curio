/**
 * Which categories of a node's header are open (#662). The header above a
 * node's code or spec lists the chips the node can use in one row of
 * categories, all closed until one is clicked. A category opened stays open
 * for its node while the dataflow is open, so a tab switch, the notebook view
 * or the node's editor mounting again keeps it; opening another dataflow
 * closes them all (`closeEveryCategory`, called by ProjectLoader).
 *
 * Kept outside React, by node id, since a node's editor mounts again on its
 * own. A header with no node id keeps its categories as long as it is mounted.
 */
import { useCallback, useState, useSyncExternalStore } from "react";

/** The header's categories, in its row's order. */
export const STRIP_CATEGORIES = ["inputs", "scenarios", "widgets", "selections", "shared"] as const;
export type StripCategory = (typeof STRIP_CATEGORIES)[number];

const NONE: ReadonlySet<StripCategory> = new Set();

let opened = new Map<string, ReadonlySet<StripCategory>>();
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

/** *open* with *category* opened or closed. */
function toggled(open: ReadonlySet<StripCategory>, category: StripCategory): ReadonlySet<StripCategory> {
  const next = new Set(open);
  if (next.has(category)) next.delete(category);
  else next.add(category);
  return next;
}

/** The categories open in node *nodeId*'s header. */
export function openCategoriesOf(nodeId: string): ReadonlySet<StripCategory> {
  return opened.get(nodeId) ?? NONE;
}

/** Opens *category* in node *nodeId*'s header, or closes it when it is open. */
export function toggleCategory(nodeId: string, category: StripCategory): void {
  opened = new Map(opened).set(nodeId, toggled(openCategoriesOf(nodeId), category));
  notify();
}

/** Closes every node's categories: another dataflow is open. */
export function closeEveryCategory(): void {
  if (opened.size === 0) return;
  opened = new Map();
  notify();
}

/** The categories open in node *nodeId*'s header, and a toggle for one. */
export function useOpenCategories(
  nodeId?: string | null,
): [ReadonlySet<StripCategory>, (category: StripCategory) => void] {
  const [own, setOwn] = useState<ReadonlySet<StripCategory>>(NONE);
  const kept = useSyncExternalStore(
    subscribe,
    () => (nodeId ? openCategoriesOf(nodeId) : NONE),
    () => NONE,
  );
  const toggle = useCallback(
    (category: StripCategory) => {
      if (nodeId) toggleCategory(nodeId, category);
      else setOwn((open) => toggled(open, category));
    },
    [nodeId],
  );
  return [nodeId ? kept : own, toggle];
}
