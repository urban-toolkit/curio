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
 * viewed, and the drag onto the canvas.
 *
 * A card drags its scenario alone. To drag several, a set is put in select
 * mode ("Pick scenarios to drag"), one set at a time: its cards show checkboxes and
 * no longer drag, and the one handle in its header drags the checked ones.
 */
export function useScenarioCatalogDrawer(presented: boolean) {
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [sort, setSort] = useState<ScenarioSortMode>("recent");
  const [pinned, setPinned] = useState(false);

  // The set in select mode (`<project>/<set>`), and its checked scenarios' keys.
  const [selecting, setSelecting] = useState<{ set: string; keys: string[] } | null>(null);

  const handleScenarioDragEnd = useCallback(() => {
    endScenarioDrag();
  }, []);
  // Its own state, not shared with anything that selects: a card's
  // "View details" opens the modal and nothing else.
  const [detailScenario, setDetailScenario] = useState<ScenarioRow | null>(null);

  // A drawer that closes leaves select mode.
  useEffect(() => {
    if (!presented) setSelecting(null);
  }, [presented]);

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

  /** Whether *row*'s set is in select mode. */
  const isSelecting = useCallback((row: ScenarioRow) => selecting?.set === setKeyOf(row), [selecting]);
  const isChecked = useCallback((row: ScenarioRow) => Boolean(selecting?.keys.includes(row.key)), [selecting]);
  /** Put the set of *row* in select mode, with nothing checked; another set leaves it. */
  const startSelecting = useCallback((row: ScenarioRow) => setSelecting({ set: setKeyOf(row), keys: [] }), []);
  const stopSelecting = useCallback(() => setSelecting(null), []);
  /** Check or uncheck *rows*, of the set in select mode. */
  const setRowsChecked = useCallback((rows: readonly ScenarioRow[], on: boolean) => {
    setSelecting((now) => {
      if (!now) return now;
      const keys = new Set(now.keys);
      for (const row of rows) {
        if (setKeyOf(row) !== now.set) continue;
        if (on) keys.add(row.key);
        else keys.delete(row.key);
      }
      return { ...now, keys: [...keys] };
    });
  }, []);

  /** A card's drag: its scenario alone. */
  const handleScenarioDragStart = useCallback((scenario: ScenarioRow, event: DragEvent<HTMLElement>) => {
    writeScenarioDragData(event.dataTransfer, beginScenarioDrag([scenario]));
  }, []);

  /** The select-mode handle's drag: the checked scenarios, in the listing's order. */
  const handleCheckedDragStart = useCallback(
    (event: DragEvent<HTMLElement>) => {
      const rows = items.filter((row) => selecting?.keys.includes(row.key));
      if (rows.length === 0) {
        event.preventDefault();
        return;
      }
      writeScenarioDragData(event.dataTransfer, beginScenarioDrag(rows));
      dragBadge(event, rows.length === 1 ? rows[0].name : `${rows.length} scenarios`);
    },
    [selecting, items],
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
    handleCheckedDragStart,
    isSelecting,
    isChecked,
    startSelecting,
    stopSelecting,
    setRowsChecked,
    detailScenario,
    openScenarioDetails: setDetailScenario,
    closeScenarioDetails: useCallback(() => setDetailScenario(null), []),
  };
}
