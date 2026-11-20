import React, { useRef } from "react";
import clsx from "clsx";
import styles from "./TabBar.module.css";

/** One tab of a `TabBar`: the key it is chosen by, and its label. */
export interface TabBarTab<K extends string> {
  key: K;
  label: string;
}

/** The attributes of the panel a `TabBar`'s tab *key* shows. */
export function tabPanelProps(idPrefix: string, key: string) {
  return {
    role: "tabpanel",
    id: `${idPrefix}-panel-${key}`,
    "aria-labelledby": `${idPrefix}-tab-${key}`,
  } as const;
}

/**
 * A row of tabs as a tablist: the shown one selected and in the tab order,
 * the arrow keys moving to the next tab and the one before it (wrapping
 * round), each tab `<idPrefix>-tab-<key>` and controlling the panel
 * `<idPrefix>-panel-<key>` its caller renders (`tabPanelProps`). API Settings
 * and the monitor show their tabs with it, each on its page, which keeps the
 * tab in its URL, and in its drawer, which keeps it in its state.
 */
export function TabBar<K extends string>({
  tabs,
  selected,
  onSelect,
  label,
  idPrefix,
}: {
  tabs: TabBarTab<K>[];
  selected: K;
  onSelect: (key: K) => void;
  /** The tablist's accessible name. */
  label: string;
  idPrefix: string;
}) {
  const tabRefs = useRef<Record<string, HTMLButtonElement | null>>({});

  const onKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if (event.key !== "ArrowRight" && event.key !== "ArrowLeft") return;
    event.preventDefault();
    const at = tabs.findIndex((t) => t.key === selected);
    const next = tabs[(at + (event.key === "ArrowRight" ? 1 : tabs.length - 1)) % tabs.length].key;
    onSelect(next);
    tabRefs.current[next]?.focus();
  };

  return (
    <div className={styles.tabs} role="tablist" aria-label={label} onKeyDown={onKeyDown}>
      {tabs.map((t) => (
        <button
          key={t.key}
          ref={(el) => {
            tabRefs.current[t.key] = el;
          }}
          type="button"
          role="tab"
          id={`${idPrefix}-tab-${t.key}`}
          aria-selected={selected === t.key}
          aria-controls={`${idPrefix}-panel-${t.key}`}
          tabIndex={selected === t.key ? 0 : -1}
          className={clsx(styles.tab, selected === t.key && styles.tabActive)}
          onClick={() => onSelect(t.key)}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}

export default TabBar;
