import { useCallback, useEffect, useMemo, useState, type DragEvent } from "react";

import {
  beginScenarioDrag,
  endScenarioDrag,
  groupScenariosBySet,
  sortScenarios,
  useScenarioCatalog,
  writeScenarioDragData,
  type ScenarioRow,
  type ScenarioSortMode,
} from "../../../services/scenarioCatalog";

/** The set a row is of, as `<project>/<set>`. */
const setKeyOf = (row: ScenarioRow) => `${row.project.id}/${row.set?.id ?? ""}`;

/** Drag a small badge reading *text* instead of the card. */
function dragBadge(event: DragEvent<HTMLElement>, text: string) {
  if (typeof event.dataTransfer.setDragImage !== "function") return;
  const badge = document.createElement("div");
  badge.textContent = text;
  badge.style.cssText =
    "position:fixed;top:-100px;left:-100px;padding:6px 12px;border-radius:999px;" +
    "background:#2f3034;color:#fff;font:600 12px sans-serif;";
  document.body.appendChild(badge);
  event.dataTransfer.setDragImage(badge, 0, 0);
  window.setTimeout(() => badge.remove(), 0);
}

/**
 * The canvas Scenario Catalog drawer's state, kept out of the component the
 * way `useModelCatalogDrawer` keeps the Model drawer's.
 *
 * Smaller still: a scenario is read-only here, so there is nothing to add,
 * remove or delete. What is left is the search, the sort, the details being
 * viewed, the scenarios checked, and the drag of cards onto the canvas.
 *
 * Checked scenarios are of one set at a time: checking one of another set
 * starts over there. A checked card drags every checked one; an unchecked
 * card drags itself alone.
 */
export function useScenarioCatalogDrawer(presented: boolean) {
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [sort, setSort] = useState<ScenarioSortMode>("recent");
  const [pinned, setPinned] = useState(false);

  // The checked scenarios' keys, and the set (`<project>/<set>`) they are of.
  const [checked, setChecked] = useState<{ set: string; keys: string[] }>({ set: "", keys: [] });

  const handleScenarioDragEnd = useCallback(() => {
    endScenarioDrag();
  }, []);
  // Its own state, not shared with anything that selects: a card's
  // "View details" opens the modal and nothing else.
  const [detailScenario, setDetailScenario] = useState<ScenarioRow | null>(null);

  useEffect(() => {
    const handle = window.setTimeout(() => setDebouncedSearch(search), 280);
    return () => window.clearTimeout(handle);
  }, [search]);

  // Fetched only while the drawer is open, and afresh on each opening: the
  // listing is read off the account's projects, which change with every save.
  const catalog = useScenarioCatalog({ q: debouncedSearch, enabled: presented });
  const items = useMemo(() => sortScenarios(catalog.data.items, sort), [catalog.data.items, sort]);
  // Browse all lists each project's scenarios under its name.
  const groups = useMemo(() => groupScenariosBySet(items), [items]);

  const isChecked = useCallback((row: ScenarioRow) => checked.keys.includes(row.key), [checked]);
  /** Check or uncheck *rows*, all of one set; another set's checks go. */
  const setRowsChecked = useCallback((rows: readonly ScenarioRow[], on: boolean) => {
    if (rows.length === 0) return;
    const set = setKeyOf(rows[0]);
    setChecked((now) => {
      const keys = new Set(now.set === set ? now.keys : []);
      for (const row of rows) {
        if (on) keys.add(row.key);
        else keys.delete(row.key);
      }
      return { set, keys: [...keys] };
    });
  }, []);

  const handleScenarioDragStart = useCallback(
    (scenario: ScenarioRow, event: DragEvent<HTMLElement>) => {
      const rows = checked.keys.includes(scenario.key)
        ? items.filter((row) => checked.keys.includes(row.key))
        : [scenario];
      writeScenarioDragData(event.dataTransfer, beginScenarioDrag(rows));
      if (rows.length > 1) dragBadge(event, `${rows.length} scenarios`);
    },
    [checked, items],
  );

  return {
    search,
    setSearch,
    sort,
    setSort,
    pinned,
    setPinned,
    catalog,
    items,
    groups,
    handleScenarioDragStart,
    handleScenarioDragEnd,
    isChecked,
    setRowsChecked,
    detailScenario,
    openScenarioDetails: setDetailScenario,
    closeScenarioDetails: useCallback(() => setDetailScenario(null), []),
  };
}
