import { useCallback, useEffect, useMemo, useState, type DragEvent } from "react";

import {
  beginScenarioDrag,
  endScenarioDrag,
  sortScenarios,
  useScenarioCatalog,
  writeScenarioDragData,
  type ScenarioRow,
  type ScenarioSortMode,
} from "../../../services/scenarioCatalog";

/**
 * The canvas Scenario Catalog drawer's state, kept out of the component the
 * way `useModelCatalogDrawer` keeps the Model drawer's.
 *
 * Smaller still: a scenario is read-only here, so there is nothing to add,
 * remove or delete. What is left is the search, the sort, the details being
 * viewed, and the drag of a card onto the canvas.
 */
export function useScenarioCatalogDrawer(presented: boolean) {
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [sort, setSort] = useState<ScenarioSortMode>("recent");
  const [pinned, setPinned] = useState(false);

  const handleScenarioDragStart = useCallback((scenario: ScenarioRow, event: DragEvent<HTMLElement>) => {
    writeScenarioDragData(event.dataTransfer, beginScenarioDrag(scenario));
  }, []);

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

  return {
    search,
    setSearch,
    sort,
    setSort,
    pinned,
    setPinned,
    catalog,
    items,
    handleScenarioDragStart,
    handleScenarioDragEnd,
    detailScenario,
    openScenarioDetails: setDetailScenario,
    closeScenarioDetails: useCallback(() => setDetailScenario(null), []),
  };
}
