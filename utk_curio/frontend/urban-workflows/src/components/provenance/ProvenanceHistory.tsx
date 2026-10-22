import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faChevronRight } from "@fortawesome/free-solid-svg-icons";
import shell from "../packages/publishing/CatalogDrawerShell.module.css";
import styles from "./ProvenanceHistory.module.css";
import { type HistoryItem, type HistoryLine, historyLines, lineHolds, lineSize } from "../../utils/provenanceTree";

export type { HistoryItem };

export interface ProvenanceHistoryProps {
  items: readonly HistoryItem[];
  /** The item in use: the version on the canvas, or the run the node's next
   *  run branches from. A filled dot marks it. */
  currentId: string | null;
  /** What one item is called, and several: ["version", "versions"]. */
  noun: readonly [string, string];
  /** What an opened item shows. */
  details: (id: string) => React.ReactNode;
  /** Said while there is no item. */
  emptyText: string;
}

/**
 * A provenance history, the same for a dataflow's versions and a node's runs,
 * listed as Curio's Nest lists work: the line to the newest item on a rail,
 * and each branch folded under the item it left from. A click opens an item in
 * place and shows its details; nothing is put back until its own button says
 * so.
 */
export function ProvenanceHistory({ items, currentId, noun, details, emptyText }: ProvenanceHistoryProps) {
  const lines = useMemo(() => historyLines(items), [items]);
  const byId = useMemo(() => new Map(items.map((item) => [item.id, item])), [items]);
  const [open, setOpen] = useState<ReadonlySet<string>>(() => new Set());
  // A branch is named by its first item. The one holding the item in use
  // starts unfolded, so that item is in view.
  const [unfolded, setUnfolded] = useState<ReadonlySet<string>>(() => branchesHolding(lines, currentId));
  const rootRef = useRef<HTMLDivElement>(null);

  const toggle = useCallback((id: string) => setOpen((prev) => flip(prev, id)), []);
  const toggleFold = useCallback((first: string) => setUnfolded((prev) => flip(prev, first)), []);

  // Opens on the item in use.
  useEffect(() => {
    const el = rootRef.current?.querySelector<HTMLElement>('[data-provenance-current="true"]');
    if (el) scrollToItem(el);
  }, []);

  if (items.length === 0) return <div className={shell.empty}>{emptyText}</div>;

  const itemProps: ItemSharedProps = { byId, currentId, open, toggle, details };
  return (
    <div ref={rootRef} className={styles.history}>
      {lines.map((line) => (
        <ListLine
          key={line.rows[0].id}
          line={line}
          depth={0}
          noun={noun}
          unfolded={unfolded}
          toggleFold={toggleFold}
          {...itemProps}
        />
      ))}
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

function Item({ id, byId, currentId, open, toggle, details }: ItemSharedProps & { id: string }) {
  const item = byId.get(id);
  if (!item) return null;
  const isOpen = open.has(id);
  const current = id === currentId;
  return (
    <div
      className={current ? `${styles.item} ${styles.current}` : styles.item}
      data-provenance-item={id}
      data-provenance-current={current ? "true" : undefined}
    >
      <button
        type="button"
        className={styles.head}
        aria-expanded={isOpen}
        aria-current={current ? "true" : undefined}
        data-tooltip={item.tooltip ? `${item.title}\n${item.tooltip}` : item.title}
        onClick={() => toggle(id)}
      >
        <span className={styles.dot} aria-hidden="true" />
        <span className={styles.tag}>{item.tag}</span>
        <span className={styles.title}>{item.title}</span>
        <span className={styles.when}>{item.when}</span>
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
          <Item id={row.id} {...itemProps} />
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
