import React, { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faChevronRight } from "@fortawesome/free-solid-svg-icons";
import shell from "../packages/publishing/CatalogDrawerShell.module.css";
import styles from "./ProvenanceHistory.module.css";
import {
  type BoxRect,
  type HistoryItem,
  type HistoryLine,
  historyGraph,
  historyLines,
  lineHolds,
  lineSize,
  linkEnds,
  linkPath,
} from "../../utils/provenanceTree";

export type { HistoryItem };

export type HistoryView = "list" | "graph";

export interface ProvenanceHistoryProps {
  items: readonly HistoryItem[];
  /** The item in use: the version on the canvas, or the run the node's next
   *  run branches from. A filled dot marks it. */
  currentId: string | null;
  view: HistoryView;
  /** What one item is called, and several: ["version", "versions"]. */
  noun: readonly [string, string];
  /** What an opened item shows. */
  details: (id: string) => React.ReactNode;
  /** Said while there is no item. */
  emptyText: string;
}

/** The height of an item's title line (`.head`), where a branch's link leaves
 *  and enters, so a box that opens keeps its links where they were. */
const HEAD_HEIGHT = 34;

const NO_RECT: BoxRect = { x: 0, y: 0, w: 0, h: 0 };

/**
 * A provenance history, the same for a dataflow's versions and a node's runs,
 * shown as the List or the Graph of Curio's Nest. A click opens an item in
 * place and shows its details; nothing is put back until its own button says
 * so. Opened items stay open when the view flips.
 */
export function ProvenanceHistory({ items, currentId, view, noun, details, emptyText }: ProvenanceHistoryProps) {
  const lines = useMemo(() => historyLines(items), [items]);
  const byId = useMemo(() => new Map(items.map((item) => [item.id, item])), [items]);
  const [open, setOpen] = useState<ReadonlySet<string>>(() => new Set());
  // A branch is named by its first item. The one holding the item in use
  // starts unfolded, so that item is in view.
  const [unfolded, setUnfolded] = useState<ReadonlySet<string>>(() => branchesHolding(lines, currentId));
  const rootRef = useRef<HTMLDivElement>(null);

  const toggle = useCallback((id: string) => setOpen((prev) => flip(prev, id)), []);
  const toggleFold = useCallback((first: string) => setUnfolded((prev) => flip(prev, first)), []);

  // Opens on the item in use, and finds it again after a flip.
  useEffect(() => {
    const el = rootRef.current?.querySelector<HTMLElement>('[data-provenance-current="true"]');
    if (el) scrollToItem(el);
  }, [view]);

  if (items.length === 0) return <div className={shell.empty}>{emptyText}</div>;

  const itemProps: ItemSharedProps = { byId, currentId, open, toggle, details };
  return (
    <div ref={rootRef} className={styles.history} data-provenance-view={view}>
      {view === "list" ? (
        lines.map((line) => (
          <ListLine
            key={line.rows[0].id}
            line={line}
            depth={0}
            noun={noun}
            unfolded={unfolded}
            toggleFold={toggleFold}
            {...itemProps}
          />
        ))
      ) : (
        <GraphView lines={lines} {...itemProps} />
      )}
    </div>
  );
}

interface ItemSharedProps {
  byId: ReadonlyMap<string, HistoryItem>;
  currentId: string | null;
  open: ReadonlySet<string>;
  toggle: (id: string) => void;
  details: (id: string) => React.ReactNode;
}

function Item({
  id,
  byId,
  currentId,
  open,
  toggle,
  details,
  showWhen,
  style,
}: ItemSharedProps & { id: string; showWhen: boolean; style?: React.CSSProperties }) {
  const item = byId.get(id);
  if (!item) return null;
  const isOpen = open.has(id);
  const current = id === currentId;
  return (
    <div
      className={current ? `${styles.item} ${styles.current}` : styles.item}
      style={style}
      data-provenance-item={id}
      data-provenance-current={current ? "true" : undefined}
    >
      <button
        type="button"
        className={styles.head}
        aria-expanded={isOpen}
        aria-current={current ? "true" : undefined}
        title={item.tooltip}
        onClick={() => toggle(id)}
      >
        <span className={styles.dot} aria-hidden="true" />
        <span className={styles.tag}>{item.tag}</span>
        <span className={styles.title}>{item.title}</span>
        {showWhen ? <span className={styles.when}>{item.when}</span> : null}
      </button>
      {isOpen ? <div className={styles.details}>{details(id)}</div> : null}
    </div>
  );
}

function ListLine({
  line,
  depth,
  noun,
  unfolded,
  toggleFold,
  ...itemProps
}: ItemSharedProps & {
  line: HistoryLine;
  depth: number;
  noun: readonly [string, string];
  unfolded: ReadonlySet<string>;
  toggleFold: (first: string) => void;
}) {
  const tone = depth === 0 ? "" : depth % 2 === 1 ? styles.depth1 : styles.depth2;
  return (
    <ol className={tone ? `${styles.line} ${tone}` : styles.line} data-provenance-line={depth}>
      {line.rows.map((row) => (
        <li key={row.id} className={styles.entry}>
          <Item id={row.id} showWhen {...itemProps} />
          {row.branches.map((branch) => {
            const first = branch.rows[0].id;
            const shown = unfolded.has(first);
            const size = lineSize(branch);
            return (
              <div key={first} className={styles.branch}>
                <button
                  type="button"
                  className={styles.fold}
                  aria-expanded={shown}
                  data-provenance-fold={first}
                  onClick={() => toggleFold(first)}
                >
                  <FontAwesomeIcon icon={faChevronRight} aria-hidden />
                  <span>
                    {size} {size === 1 ? noun[0] : noun[1]} on another branch
                  </span>
                </button>
                {shown ? (
                  <ListLine
                    line={branch}
                    depth={depth + 1}
                    noun={noun}
                    unfolded={unfolded}
                    toggleFold={toggleFold}
                    {...itemProps}
                  />
                ) : null}
              </div>
            );
          })}
        </li>
      ))}
    </ol>
  );
}

function GraphView({ lines, ...itemProps }: ItemSharedProps & { lines: HistoryLine[] }) {
  const graph = useMemo(() => historyGraph(lines), [lines]);
  const gridRef = useRef<HTMLDivElement>(null);
  const [rects, setRects] = useState<Record<string, BoxRect>>({});
  const [size, setSize] = useState({ w: 0, h: 0 });

  // Where each box landed in the grid, read from layout (not from the screen,
  // which the drawer's slide moves), so the links meet the boxes.
  const measure = useCallback(() => {
    const grid = gridRef.current;
    if (!grid) return;
    const next: Record<string, BoxRect> = {};
    for (const el of Array.from(grid.children)) {
      const id = (el as HTMLElement).dataset?.provenanceItem;
      if (!id) continue;
      const box = el as HTMLElement;
      next[id] = { x: box.offsetLeft, y: box.offsetTop, w: box.offsetWidth, h: box.offsetHeight };
    }
    setRects((prev) => (sameRects(prev, next) ? prev : next));
    setSize((prev) =>
      prev.w === grid.scrollWidth && prev.h === grid.scrollHeight ? prev : { w: grid.scrollWidth, h: grid.scrollHeight },
    );
  }, []);

  // After every render: an opened box moves every row under it.
  useLayoutEffect(() => {
    measure();
  });

  useEffect(() => {
    const grid = gridRef.current;
    if (!grid || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(() => measure());
    observer.observe(grid);
    return () => observer.disconnect();
  }, [measure]);

  return (
    <div className={styles.canvas}>
      <div
        ref={gridRef}
        className={styles.graph}
        style={{ gridTemplateColumns: `repeat(${graph.cols}, minmax(180px, 1fr))` }}
      >
        <svg className={styles.edges} width={size.w} height={size.h} aria-hidden="true">
          {graph.links.map((link) => {
            const a = rects[link.from] ?? NO_RECT;
            const b = rects[link.to] ?? NO_RECT;
            const [x1, y1, x2, y2] = linkEnds(link.kind, a, b, HEAD_HEIGHT);
            return (
              <g key={`${link.from}->${link.to}`} data-provenance-link={link.kind} data-from={link.from} data-to={link.to}>
                <path d={linkPath(link.kind, a, b, HEAD_HEIGHT)} fill="none" stroke="#A2A6AE" strokeWidth={1.6} />
                <circle cx={x1} cy={y1} r={3} fill="#fff" stroke="#A2A6AE" strokeWidth={1.4} />
                <circle cx={x2} cy={y2} r={3} fill="#fff" stroke="#A2A6AE" strokeWidth={1.4} />
              </g>
            );
          })}
        </svg>
        {graph.boxes.map((box) => (
          <Item
            key={box.id}
            id={box.id}
            showWhen={false}
            style={{ gridColumn: box.col + 1, gridRow: box.row + 1 }}
            {...itemProps}
          />
        ))}
      </div>
    </div>
  );
}

function flip(set: ReadonlySet<string>, id: string): ReadonlySet<string> {
  const next = new Set(set);
  if (!next.delete(id)) next.add(id);
  return next;
}

/** The first items of the branches, at any depth, that hold *id*. */
function branchesHolding(lines: readonly HistoryLine[], id: string | null): ReadonlySet<string> {
  const found = new Set<string>();
  const walk = (line: HistoryLine) => {
    for (const row of line.rows) {
      for (const branch of row.branches) {
        if (lineHolds(branch, id)) found.add(branch.rows[0].id);
        walk(branch);
      }
    }
  };
  lines.forEach(walk);
  return found;
}

function sameRects(a: Record<string, BoxRect>, b: Record<string, BoxRect>): boolean {
  const keys = Object.keys(b);
  if (keys.length !== Object.keys(a).length) return false;
  return keys.every((k) => {
    const p = a[k];
    const q = b[k];
    return !!p && p.x === q.x && p.y === q.y && p.w === q.w && p.h === q.h;
  });
}

/**
 * Brings *el* to the middle of the box that scrolls it: the drawer's body.
 * Not `scrollIntoView`, which also scrolls the page under a fixed drawer.
 */
function scrollToItem(el: HTMLElement) {
  const scrolls = (box: HTMLElement) =>
    box.scrollHeight > box.clientHeight && /auto|scroll/.test(getComputedStyle(box).overflowY);
  let box = el.parentElement;
  while (box && !scrolls(box)) box = box.parentElement;
  if (!box || box === document.body || box === document.documentElement) return;
  const top = el.getBoundingClientRect().top - box.getBoundingClientRect().top + box.scrollTop;
  box.scrollTop = Math.max(0, top - (box.clientHeight - el.offsetHeight) / 2);
}

export default ProvenanceHistory;
