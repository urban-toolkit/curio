import { useCallback, useEffect, useMemo, useState } from "react";

import { agentsApi, type AgentCard, type AgentCatalogFacets } from "../../api/agentsApi";
import { notifyAgentCatalogRefresh } from "../../utils/agentCatalogEvents";
import type { SortMode } from "../../components/packages/publishing/packageTypes";
import {
  matchesAgentSearch,
  sortAgentCards,
} from "../../components/agents/catalog/agentListUtils";

/**
 * State behind `/catalog/agents`, the account-scope Agent Catalog.
 *
 * Hook-per-surface, the direction both peers converged on: the Node Catalog
 * has `useNodeCatalogBrowse`, and the drawer next door has
 * `useAgentCatalogDrawer`. Keeping the page's state out of the component is
 * what lets the filtering be unit-tested without rendering a grid.
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


export function useAgentCatalogBrowse(): AgentCatalogBrowseState {
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState<SortMode>("new");
  const [filter, setFilter] = useState<AgentBrowseFilter>("all");
  const [categoryFilter, setCategoryFilterRaw] = useState("");
  const [agents, setAgents] = useState<AgentCard[]>([]);
  const [facets, setFacets] = useState<AgentCatalogFacets | null>(null);
  const [loading, setLoading] = useState(true);
  const [busyCoord, setBusyCoord] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  // Tri-state, matching useNodeCatalogBrowse and DataCatalogBrowse: `undefined`
  // means "nothing chosen yet, fall back to the first row" and `null` means the
  // user closed the drawer. Collapsing the two (a plain `string | null`) made
  // Close unusable, because the auto-select effect could not tell a dismissal
  // from a fresh page and immediately reopened on `filtered[0]`.
  const [selectedCoord, setSelectedCoord] = useState<string | null | undefined>(undefined);

  const setCategoryFilter = useCallback(
    (updater: (prev: string) => string) => setCategoryFilterRaw(updater),
    [],
  );

  const reload = useCallback(async () => {
    // No projectId: this page is account scope, so `installedInProject` is not
    // meaningful here and asking for it would only mark rows against whichever
    // dataflow happened to be open last.
    const resp = await agentsApi.catalog();
    setAgents(resp.items ?? resp.agents);
    setFacets(resp.facets ?? null);
  }, []);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    void (async () => {
      try {
        const resp = await agentsApi.catalog();
        if (cancelled) return;
        setAgents(resp.items ?? resp.agents);
        setFacets(resp.facets ?? null);
      } catch (err) {
        if (!cancelled) setActionError((err as Error)?.message ?? "Could not load the Agent Catalog.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  /**
   * Run one mutation, then refetch. The error banner sits OVER the rows rather
   * than replacing them: a failed publish should not blank the catalog the
   * user is reading.
   */
  const run = useCallback(
    async (agent: AgentCard, verb: string, op: () => Promise<unknown>) => {
      setBusyCoord(agent.dirName);
      setActionError(null);
      try {
        await op();
        await reload();
        // One notify fans out to the drawer and the palette; they hold their
        // own caches keyed differently, and this is the single chokepoint.
        notifyAgentCatalogRefresh();
      } catch (err) {
        const detail = (err as Error)?.message ?? "unknown error";
        setActionError(`Couldn't ${verb} ${agent.name}: ${detail}`);
      } finally {
        setBusyCoord(null);
      }
    },
    [reload],
  );

  const onImport = useCallback(
    (agent: AgentCard) => run(agent, "add", () => agentsApi.import(agent.dirName)),
    [run],
  );
  const onRemoveImport = useCallback(
    (agent: AgentCard) => run(agent, "remove", () => agentsApi.removeImport(agent.dirName)),
    [run],
  );
  const onPublish = useCallback(
    (agent: AgentCard) => run(agent, "publish", () => agentsApi.publish(agent.dirName)),
    [run],
  );
  const onUnpublish = useCallback(
    (agent: AgentCard) => run(agent, "unpublish", () => agentsApi.unpublish(agent.dirName)),
    [run],
  );

  const filtered = useMemo(() => {
    // The drawer's helpers, not a second copy. The private one here had already
    // drifted three ways: it did not trim the query, did not match `category`
    // (so "canvas" found category matches in the drawer and nothing here), and
    // sorted with a bare localeCompare rather than the shared base-sensitivity
    // comparator, so the two surfaces could order one roster differently.
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
    if (facets) {
      return Object.entries(facets.category).sort((a, b) => a[0].localeCompare(b[0]));
    }
    // Pre-facets fallback: count locally so the rail still renders if an older
    // backend answers without them.
    const counts = new Map<string, number>();
    for (const agent of agents) {
      if (!agent.category) continue;
      counts.set(agent.category, (counts.get(agent.category) ?? 0) + 1);
    }
    return [...counts.entries()].sort((a, b) => a[0].localeCompare(b[0]));
  }, [facets, agents]);

  // Resolve the tri-state: an explicit close stays closed, an explicit pick
  // wins, and "nothing chosen yet" falls back to the first visible row so the
  // drawer has something to show on arrival.
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
    loading,
    busyCoord,
    actionError,
    dismissActionError: useCallback(() => setActionError(null), []),
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
    onImport,
    onRemoveImport,
    onPublish,
    onUnpublish,
  };
}
