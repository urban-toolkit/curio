/**
 * A provenance history laid out the way Curio's Nest lists work: each line of
 * items on a rail, with the branches left behind folded under the item they
 * left from.
 *
 * One layout for a dataflow's versions and for a node's runs. Each item names
 * the item it was made from; the line through the newest item is the main one,
 * so the rail always leads to the latest work and an abandoned try hangs off
 * where it left.
 */

export interface HistoryEntry {
  id: string;
  /** The item this one was made from; null for a first item. */
  parentId: string | null;
  /** When it was made, as a sort key: a later item has a larger one. */
  order: number;
}

/** One version of a dataflow, or one run of a node, as the history shows it. */
export interface HistoryItem extends HistoryEntry {
  /** The number on its tag. */
  tag: string;
  /** What it is, in a few words. */
  title: string;
  /** When it was made, as its row says it. */
  when: string;
  /** Said on hover under the title, which a row cuts when it is long: the
   *  date and time it was made. */
  tooltip?: string;
}

/** One line of items on a rail, oldest first. */
export interface HistoryLine {
  rows: HistoryRow[];
}

export interface HistoryRow {
  id: string;
  /** The lines that leave from this item, apart from the one it continues on. */
  branches: HistoryLine[];
}

/**
 * The lines of a history: one per first item, oldest first, each running down
 * to the newest item it leads to.
 *
 * An item whose parent is missing starts a line of its own, and a loop in the
 * parent links (a saved file can hold anything) is cut where it closes, so
 * every item is listed exactly once.
 */
export function historyLines(entries: readonly HistoryEntry[]): HistoryLine[] {
  const byId = new Map<string, HistoryEntry>();
  for (const entry of entries) if (!byId.has(entry.id)) byId.set(entry.id, entry);
  const all = [...byId.values()].sort((a, b) => a.order - b.order);

  const children = new Map<string, HistoryEntry[]>();
  const firsts: HistoryEntry[] = [];
  for (const entry of all) {
    const parent = entry.parentId != null ? byId.get(entry.parentId) : undefined;
    if (!parent || parent.id === entry.id) {
      firsts.push(entry);
      continue;
    }
    const kids = children.get(parent.id);
    if (kids) kids.push(entry);
    else children.set(parent.id, [entry]);
  }

  // The newest item under each one, itself included, without recursion: a
  // long dataflow's history is a chain hundreds of versions deep.
  const newest = new Map<string, number>();
  const newestUnder = (start: HistoryEntry): number => {
    const known = newest.get(start.id);
    if (known !== undefined) return known;
    const stack: [HistoryEntry, boolean][] = [[start, false]];
    const onStack = new Set<string>();
    while (stack.length > 0) {
      const [entry, expanded] = stack.pop()!;
      if (newest.has(entry.id)) continue;
      const kids = children.get(entry.id) ?? [];
      if (!expanded) {
        onStack.add(entry.id);
        stack.push([entry, true]);
        for (const kid of kids) if (!newest.has(kid.id) && !onStack.has(kid.id)) stack.push([kid, false]);
        continue;
      }
      let best = entry.order;
      for (const kid of kids) best = Math.max(best, newest.get(kid.id) ?? kid.order);
      newest.set(entry.id, best);
      onStack.delete(entry.id);
    }
    return newest.get(start.id) ?? start.order;
  };

  const listed = new Set<string>();
  const lineFrom = (start: HistoryEntry): HistoryLine => {
    const rows: HistoryRow[] = [];
    let current: HistoryEntry | undefined = start;
    while (current && !listed.has(current.id)) {
      listed.add(current.id);
      const kids = (children.get(current.id) ?? []).filter((kid) => !listed.has(kid.id));
      let next: HistoryEntry | undefined;
      for (const kid of kids) if (!next || newestUnder(kid) > newestUnder(next)) next = kid;
      const row: HistoryRow = { id: current.id, branches: [] };
      rows.push(row);
      for (const kid of kids) if (kid !== next) row.branches.push(lineFrom(kid));
      current = next;
    }
    return { rows };
  };

  const lines: HistoryLine[] = [];
  for (const first of firsts) if (!listed.has(first.id)) lines.push(lineFrom(first));
  // What a loop kept from every first item: start a line at its oldest.
  for (const entry of all) if (!listed.has(entry.id)) lines.push(lineFrom(entry));
  return lines;
}

/** How many items a line holds, its branches' included. */
export function lineSize(line: HistoryLine): number {
  return line.rows.reduce((n, row) => n + 1 + row.branches.reduce((m, b) => m + lineSize(b), 0), 0);
}

/** Whether *id* is on *line* or on one of its branches. */
export function lineHolds(line: HistoryLine, id: string | null): boolean {
  if (id == null) return false;
  return line.rows.some((row) => row.id === id || row.branches.some((b) => lineHolds(b, id)));
}
