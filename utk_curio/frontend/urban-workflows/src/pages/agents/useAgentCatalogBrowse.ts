import { useCallback, useEffect, useMemo, useState } from "react";

import {
  agentsApi,
  matchesAgentSearch,
  sortAgentCards,
  useAgentCatalog,
  type AgentCard,
  type AgentCatalogFacets,
} from "../../services/agents";
import type { SortMode } from "../../services/packages";

/**
 * State behind `/catalog/agents`, the account-scope Agent Catalog: this page's
 * view of THE catalog hook (memo dev/142, F3). It keeps only the page's own
 * state — search, sort, the rail filter, the category and the selection — and
 * hands `useAgentCatalog` the account scope (no project id: `installedInProject`
 * is not meaningful here) and its action-error wording.
 *
 * Scope is the thing to keep straight. The in-canvas drawer installs an agent
 * into ONE dataflow; this page adds it to the user's account, after which it
 * can be installed into any dataflow. They are different writes, so they carry
 * different labels - see AgentCatalogBrowse's CTA.
 */

/** Which slice of the catalog the rail is showing. */
export type AgentBrowseFilter = "all" | "imported" | "published";

export interface AgentCatalogBrowseState {
  search: string;
  setSearch: (value: string) => void;
  sort: SortMode;
  setSort: (value: SortMode) => void;
  filter: AgentBrowseFilter;
  setFilter: (value: AgentBrowseFilter) => void;
  categoryFilter: string;
  setCategoryFilter: (updater: (prev: string) => string) => void;

  loading: boolean;
  busyCoord: string | null;
  actionError: string | null;
  dismissActionError: () => void;

  /** Every catalog row, unfiltered. */
  agents: AgentCard[];
  /** Rows after search + rail + category, in the chosen sort order. */
  filtered: AgentCard[];
  facets: AgentCatalogFacets | null;
  categories: [string, number][];

  allCount: number;
  importedCount: number;
  publishedCount: number;

  /** `undefined` = nothing chosen yet (show the first); `null` = closed. */
  selectedCoord: string | null | undefined;
  setSelectedCoord: (coord: string | null | undefined) => void;
  selectedAgent: AgentCard | null;

  onImport: (agent: AgentCard) => Promise<void>;
  onRemoveImport: (agent: AgentCard) => Promise<void>;
  onPublish: (agent: AgentCard) => Promise<void>;
  onUnpublish: (agent: AgentCard) => Promise<void>;
  /** Re-read the roster. The page's own import modal writes a new definition
   *  into the account, so it has to ask for the list again afterwards. */
  reload: () => Promise<void>;
}

/** A failed action reads as a sentence about the agent, over the rows the user
 *  is reading — never instead of them. */
function describeActionError(verb: string, card: { name?: string; dirName: string }, detail: string): string {
  return `Couldn't ${verb} ${card.name ?? card.dirName}: ${detail}`;
}

/**
 * The global catalog plus the account's own imports, one row per agent.
 *
 * Mirrors `useNodeCatalogBrowse.mergedRows`, with the winner reversed on the
 * fields that decide what the drawer offers: `list_global_catalog` never passes
 * `publishable`, so a catalog row reports false even for an agent this account
 * authored and published. Letting the catalog win there is what left both
 * Publish and Unpublish unreachable (#305, #294).
 */
export function mergeAgentRows(catalog: AgentCard[], imports: AgentCard[]): AgentCard[] {
  const rows = new Map<string, AgentCard>();
  for (const row of catalog ?? []) rows.set(row.dirName, row);
  for (const row of imports ?? []) {
    const existing = rows.get(row.dirName);
    rows.set(row.dirName, existing
      ? {
        ...existing,
        ...row,
        // Published is a fact about the catalog; either source seeing it counts.
        published: Boolean(existing.published || row.published),
        publishable: Boolean(row.publishable || existing.publishable),
        imported: true,
      }
      : row);
  }
  return Array.from(rows.values());
}

export function useAgentCatalogBrowse(): AgentCatalogBrowseState {
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState<SortMode>("new");
  const [filter, setFilter] = useState<AgentBrowseFilter>("all");
  const [categoryFilter, setCategoryFilterRaw] = useState("");
  // Tri-state, matching useNodeCatalogBrowse and DataCatalogBrowse: `undefined`
  // means "nothing chosen yet, fall back to the first row" and `null` means the
  // user closed the drawer. Collapsing the two made Close unusable, because the
  // auto-select effect could not tell a dismissal from a fresh page.
  const [selectedCoord, setSelectedCoord] = useState<string | null | undefined>(undefined);
  const catalog = useAgentCatalog({
    describeActionError,
    loadErrorFallback: "Could not load the Agent Catalog.",
  });
  // Two feeds, like `useNodeCatalogBrowse` (catalog + listInstalled): the
  // catalog is built-ins union published definitions, so an agent the user
  // authored and imported is in neither, and the page that owns the Publish
  // pill could never show it (#305). The imports feed is an addition, not a
  // precondition - a failure there must not blank the roster.
  const [imports, setImports] = useState<AgentCard[]>([]);
  const loadImports = useCallback(async () => {
    try {
      const resp = await agentsApi.listImports();
      setImports(resp.agents ?? []);
    } catch (err) {
      console.warn("[agent-catalog] could not read this account's imports:", err);
      setImports([]);
    }
  }, []);
  useEffect(() => {
    void loadImports();
  }, [loadImports]);
  const agents = useMemo(() => mergeAgentRows(catalog.cards, imports), [catalog.cards, imports]);
  const facets = catalog.facets;
  const reload = useCallback(async () => {
    await Promise.all([catalog.reload(), loadImports()]);
  }, [catalog, loadImports]);
  /** Every action refreshes the imports feed too: the hook refreshes only its own scopes. */
  const withImports = useCallback(
    <A extends unknown[]>(fn: (...args: A) => Promise<void>) => async (...args: A) => {
      await fn(...args);
      await loadImports();
    },
    [loadImports],
  );

  const setCategoryFilter = useCallback(
    (updater: (prev: string) => string) => setCategoryFilterRaw(updater),
    [],
  );

  const filtered = useMemo(() => {
    // The drawer's helpers, not a second copy: one search, one sort order.
    const rows = agents.filter((agent) => {
      if (!matchesAgentSearch(agent, search)) return false;
      if (filter === "imported" && !agent.imported) return false;
      if (filter === "published" && !agent.published) return false;
      if (categoryFilter && agent.category !== categoryFilter) return false;
      return true;
    });
    return sortAgentCards(rows, sort);
  }, [agents, search, filter, categoryFilter, sort]);

  const categories = useMemo<[string, number][]>(() => {
    // Counted from the rows on screen, not from the response's facets: those
    // are computed over the global catalog alone, so an agent this account
    // authored would be listed under a category the rail did not count - or
    // not offer at all, when nothing else shares its category (#305).
    const counts = new Map<string, number>();
    for (const agent of agents) {
      if (!agent.category) continue;
      counts.set(agent.category, (counts.get(agent.category) ?? 0) + 1);
    }
    return [...counts.entries()].sort((a, b) => a[0].localeCompare(b[0]));
  }, [agents]);

  // Resolve the tri-state: an explicit close stays closed, an explicit pick
  // wins, and "nothing chosen yet" falls back to the first visible row.
  const selectedAgent = useMemo(() => {
    if (selectedCoord === null) return null;
    if (selectedCoord != null) {
      return filtered.find((a) => a.dirName === selectedCoord) ?? null;
    }
    return filtered[0] ?? null;
  }, [filtered, selectedCoord]);

  // Keep the explicit selection honest as the filters change: drop back to the
  // undefined default when the chosen agent leaves the visible set, and never
  // resurrect a drawer the user closed.
  useEffect(() => {
    if (filtered.length === 0) {
      if (selectedCoord !== undefined) setSelectedCoord(undefined);
      return;
    }
    if (selectedCoord === null) return;
    if (selectedCoord != null && filtered.some((a) => a.dirName === selectedCoord)) return;
    if (selectedCoord !== undefined) setSelectedCoord(undefined);
  }, [filtered, selectedCoord]);

  return {
    search,
    setSearch,
    sort,
    setSort,
    filter,
    setFilter,
    categoryFilter,
    setCategoryFilter,
    loading: catalog.loading,
    busyCoord: catalog.busyCoord,
    actionError: catalog.error,
    dismissActionError: catalog.dismissError,
    agents,
    filtered,
    facets,
    categories,
    allCount: agents.length,
    importedCount: agents.filter((a) => a.imported).length,
    publishedCount: agents.filter((a) => a.published).length,
    selectedCoord,
    setSelectedCoord,
    selectedAgent,
    reload,
    onImport: withImports(catalog.importAgent),
    onRemoveImport: withImports(catalog.removeImport),
    onPublish: withImports(catalog.publish),
    onUnpublish: withImports(catalog.unpublish),
  };
}
