/**
 * A provenance history laid out the way Curio's Nest lays out work: as a List,
 * each line of items on a rail with the branches left behind folded under the
 * item they left from, or as a Graph, one box per item with each branch in the
 * next column, starting beside the item it left from.
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
  /** When it was made, as the List's row says it. */
  when: string;
  /** Said on hover under the title: the date and time it was made, which the
   *  Graph's box has no room for. */
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

export interface GraphBox {
  id: string;
  /** 0 for the main line, one more for each branch it hangs from. */
  col: number;
  row: number;
}

export interface GraphLink {
  from: string;
  to: string;
  /** "next" joins two items of a line, one under the other; "branch" joins
   *  an item to the first item of a line that leaves from it. */
  kind: "next" | "branch";
}

export interface HistoryGraph {
  boxes: GraphBox[];
  links: GraphLink[];
  cols: number;
  rows: number;
}

/**
 * The Graph's boxes, after the Nest's graph turned top to bottom.
 *
 * A line runs down one column. A branch runs down the next column, its first
 * item beside the item it left from, and that line's next item moves down past
 * it, so no two lines share a row and no two links cross. A second branch from
 * the same item starts below the first.
 */
export function historyGraph(lines: readonly HistoryLine[]): HistoryGraph {
  const boxes: GraphBox[] = [];
  const links: GraphLink[] = [];
  let maxCol = 0;
  const place = (line: HistoryLine, col: number, startRow: number): number => {
    let row = startRow;
    line.rows.forEach((item, k) => {
      boxes.push({ id: item.id, col, row });
      maxCol = Math.max(maxCol, col);
      if (k > 0) links.push({ from: line.rows[k - 1].id, to: item.id, kind: "next" });
      let branchRow = row;
      for (const branch of item.branches) {
        if (branch.rows.length === 0) continue;
        links.push({ from: item.id, to: branch.rows[0].id, kind: "branch" });
        branchRow = place(branch, col + 1, branchRow);
      }
      row = Math.max(row + 1, branchRow);
    });
    return row;
  };
  let row = 0;
  for (const line of lines) row = place(line, 0, row);
  return { boxes, links, cols: maxCol + 1, rows: row };
}

/** A box where the Graph drew it, in its own coordinates. */
export interface BoxRect {
  x: number;
  y: number;
  w: number;
  h: number;
}

/**
 * The path of a link between two drawn boxes. *head* is the height of a box's
 * title line, where a branch leaves and enters, so an opened box keeps its
 * links where they were.
 *
 * - "next": straight down, from the middle of one box's bottom edge to the
 *   middle of the next one's top edge.
 * - "branch": from the item's right edge to the branch's left edge, straight
 *   when they share a row, else the Nest's elbow: across to half way, a rounded
 *   turn, down, another turn, across.
 */
export function linkPath(kind: GraphLink["kind"], a: BoxRect, b: BoxRect, head: number): string {
  if (kind === "next") {
    const x1 = a.x + a.w / 2;
    const x2 = b.x + b.w / 2;
    const y1 = a.y + a.h;
    const y2 = b.y;
    return Math.abs(x2 - x1) < 1 ? `M${x1} ${y1}V${y2}` : `M${x1} ${y1}V${(y1 + y2) / 2}H${x2}V${y2}`;
  }
  const x1 = a.x + a.w;
  const y1 = a.y + head / 2;
  const x2 = b.x;
  const y2 = b.y + head / 2;
  if (Math.abs(y2 - y1) < 1) return `M${x1} ${y1}H${x2}`;
  const mx = (x1 + x2) / 2;
  const sign = y2 > y1 ? 1 : -1;
  const r = Math.min(8, Math.abs(y2 - y1) / 2, Math.abs(mx - x1));
  return (
    `M${x1} ${y1}H${mx - r}Q${mx} ${y1} ${mx} ${y1 + sign * r}` +
    `V${y2 - sign * r}Q${mx} ${y2} ${mx + r} ${y2}H${x2}`
  );
}

/** Where a link starts and ends, for the small circles the Nest draws there. */
export function linkEnds(kind: GraphLink["kind"], a: BoxRect, b: BoxRect, head: number): [number, number, number, number] {
  return kind === "next"
    ? [a.x + a.w / 2, a.y + a.h, b.x + b.w / 2, b.y]
    : [a.x + a.w, a.y + head / 2, b.x, b.y + head / 2];
}
