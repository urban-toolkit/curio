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
 * A card is selected by a click, alone; Ctrl-click (Cmd-click on a Mac) adds
 * or takes out a card of the same scenario set, and a card of another set
 * starts anew, since scenarios of different sets never mix. Dragging a
 * selected card brings every selected scenario; dragging another selects it
 * alone and brings it, as a file manager does.
 */
export function useScenarioCatalogDrawer(presented: boolean) {
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [sort, setSort] = useState<ScenarioSortMode>("recent");
  const [pinned, setPinned] = useState(false);

  // The set of the selected cards (`<project>/<set>`), and their keys.
  const [selection, setSelection] = useState<{ set: string; keys: string[] } | null>(null);

  const handleScenarioDragEnd = useCallback(() => {
    endScenarioDrag();
  }, []);
  // Its own state, not shared with anything that selects: a card's
  // "View details" opens the modal and nothing else.
  const [detailScenario, setDetailScenario] = useState<ScenarioRow | null>(null);

  // A drawer that closes, or a listing searched or sorted anew, drops it.
  useEffect(() => {
    if (!presented) setSelection(null);
  }, [presented]);
  useEffect(() => setSelection(null), [debouncedSearch, sort]);

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

  const isSelected = useCallback((row: ScenarioRow) => Boolean(selection?.keys.includes(row.key)), [selection]);
  /** Select *row* alone, or with *toggle* add it to the selection or take it
   *  out, when the selection is of its set; a row of another set, or of no
   *  set (a listing from before sets, copied one at a time), starts anew. */
  const selectRow = useCallback((row: ScenarioRow, { toggle = false }: { toggle?: boolean } = {}) => {
    setSelection((now) => {
      const set = setKeyOf(row);
      if (!toggle || !now || now.set !== set || !row.set?.id) return { set, keys: [row.key] };
      const keys = now.keys.includes(row.key) ? now.keys.filter((key) => key !== row.key) : [...now.keys, row.key];
      return keys.length ? { set, keys } : null;
    });
  }, []);
  const clearSelection = useCallback(() => setSelection(null), []);

  /** A card's drag: every selected scenario when it is selected, in the
   *  listing's order; else its scenario alone, which it then selects. */
  const handleCardDragStart = useCallback(
    (row: ScenarioRow, event: DragEvent<HTMLElement>) => {
      const selected = selection?.keys.includes(row.key) ? items.filter((r) => selection.keys.includes(r.key)) : [row];
      if (!selection?.keys.includes(row.key)) setSelection({ set: setKeyOf(row), keys: [row.key] });
      writeScenarioDragData(event.dataTransfer, beginScenarioDrag(selected));
      dragBadge(event, selected.length === 1 ? selected[0].name : `${selected.length} scenarios`);
    },
    [selection, items],
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
    handleScenarioDragEnd,
    handleCardDragStart,
    isSelected,
    selectRow,
    clearSelection,
    detailScenario,
    openScenarioDetails: setDetailScenario,
    closeScenarioDetails: useCallback(() => setDetailScenario(null), []),
  };
}
