import { useCallback, useEffect, useMemo, useState } from "react";

import { agentsApi, type AgentCard, type AgentCatalogFacets } from "../../api/agentsApi";
import { notifyAgentCatalogRefresh } from "../../utils/agentCatalogEvents";
import type { SortMode } from "../../components/packages/publishing/packageTypes";

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

  selectedCoord: string | null;
  setSelectedCoord: (coord: string | null) => void;
  selectedAgent: AgentCard | null;

  onImport: (agent: AgentCard) => Promise<void>;
  onRemoveImport: (agent: AgentCard) => Promise<void>;
  onPublish: (agent: AgentCard) => Promise<void>;
  onUnpublish: (agent: AgentCard) => Promise<void>;
}

function matches(agent: AgentCard, query: string): boolean {
  if (!query) return true;
  const q = query.toLowerCase();
  return (
    agent.name.toLowerCase().includes(q) ||
    agent.id.toLowerCase().includes(q) ||
    (agent.purpose ?? "").toLowerCase().includes(q) ||
    (agent.provenance?.publisher ?? "").toLowerCase().includes(q) ||
    agent.capabilities.some((c) => c.toLowerCase().includes(q)) ||
    agent.hooks.some((h) => h.toLowerCase().includes(q))
  );
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
  const [selectedCoord, setSelectedCoord] = useState<string | null>(null);

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
    const rows = agents.filter((agent) => {
      if (!matches(agent, search)) return false;
      if (filter === "imported" && !agent.imported) return false;
      if (filter === "published" && !agent.published) return false;
      if (categoryFilter && agent.category !== categoryFilter) return false;
      return true;
    });
    const sorted = [...rows];
    if (sort === "name") {
      sorted.sort((a, b) => a.name.localeCompare(b.name));
    } else {
      // "new" has no timestamp to sort by on an agent card, so it holds the
      // roster order the backend returned (built-ins first, then published).
      // Named rather than silently aliased to `name`, which would make the two
      // options look broken by rendering identically.
    }
    return sorted;
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

  const selectedAgent = useMemo(
    () => agents.find((a) => a.dirName === selectedCoord) ?? null,
    [agents, selectedCoord],
  );

  // Auto-select the first row so the detail drawer has something to show, the
  // way both peers do.
  useEffect(() => {
    if (selectedCoord == null && filtered.length > 0) {
      setSelectedCoord(filtered[0].dirName);
    }
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
    onImport,
    onRemoveImport,
    onPublish,
    onUnpublish,
  };
}
