import { useCallback, useEffect, useRef, useState } from "react";
import { agentsApi, AgentCard } from "../../../api/agentsApi";
import { notifyAgentsPaletteRefresh } from "../../../utils/agentsPaletteEvents";

/**
 * Self-contained data hook for the Agents Catalog drawer. Owns the active
 * scope, a **per-scope card cache**, and the lifecycle actions — all over
 * ``agentsApi``.
 *
 * Transition + consistency semantics (memo dev/47):
 * - **Stale-while-revalidate tabs**: each scope keeps its last-known rows;
 *   switching tabs renders the cache instantly and refreshes in the
 *   background. `loading` is true only for a scope's FIRST ever fetch — tab
 *   changes never blank previously loaded content.
 * - **Race guard**: a per-scope request sequence drops out-of-order
 *   responses, so rapid tab switching can never paint stale data.
 * - **All-scope refresh after actions**: install/uninstall/import/publish
 *   refresh every scope in parallel (and notify the AGENTS palette), so all
 *   tabs agree immediately.
 * - Errors keep the cached rows (banner over content, never instead of it).
 */

export type AgentScope = "global" | "my-imports" | "installed";

const ALL_SCOPES: AgentScope[] = ["global", "my-imports", "installed"];

export interface AgentsCatalogDrawerState {
  scope: AgentScope;
  setScope: (s: AgentScope) => void;
  cards: AgentCard[];
  loading: boolean;
  busyCoord: string | null;
  error: string | null;
  reload: () => Promise<void>;
  importAgent: (coord: string) => Promise<void>;
  removeImport: (coord: string) => Promise<void>;
  install: (coord: string) => Promise<void>;
  uninstall: (coord: string) => Promise<void>;
  publish: (coord: string) => Promise<void>;
  unpublish: (coord: string) => Promise<void>;
}

export function useAgentsCatalogDrawer(
  presented: boolean,
  projectId: string | null,
): AgentsCatalogDrawerState {
  const [scope, setScope] = useState<AgentScope>("global");
  const [cardsByScope, setCardsByScope] = useState<
    Partial<Record<AgentScope, AgentCard[]>>
  >({});
  const [fetching, setFetching] = useState(false);
  const [busyCoord, setBusyCoord] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const seqRef = useRef<Record<AgentScope, number>>({
    global: 0,
    "my-imports": 0,
    installed: 0,
  });

  // A project switch invalidates every scope's cache (installed state is
  // per-project; My Imports marks installs against the open project too).
  useEffect(() => {
    setCardsByScope({});
  }, [projectId]);

  const fetchScope = useCallback(
    async (s: AgentScope) => {
      const seq = ++seqRef.current[s];
      let resp: { agents: AgentCard[] };
      if (s === "global") {
        resp = await agentsApi.catalog(projectId ?? undefined);
      } else if (s === "my-imports") {
        resp = await agentsApi.listImports(projectId ?? undefined);
      } else {
        resp = projectId ? await agentsApi.listProjectAgents(projectId) : { agents: [] };
      }
      if (seqRef.current[s] !== seq) return; // out-of-order response — dropped
      setCardsByScope((prev) => ({ ...prev, [s]: resp.agents }));
    },
    [projectId],
  );

  const refreshScope = useCallback(
    async (s: AgentScope) => {
      setError(null);
      setFetching(true);
      try {
        await fetchScope(s);
      } catch (e) {
        // Cached rows stay — the banner renders over content, not instead.
        setError(e instanceof Error ? e.message : "Failed to load agents");
      } finally {
        setFetching(false);
      }
    },
    [fetchScope],
  );

  const refreshAll = useCallback(async () => {
    setError(null);
    const results = await Promise.allSettled(ALL_SCOPES.map((s) => fetchScope(s)));
    const failed = results.find(
      (r): r is PromiseRejectedResult => r.status === "rejected",
    );
    if (failed) {
      const reason = failed.reason;
      setError(reason instanceof Error ? reason.message : "Failed to refresh agents");
    }
  }, [fetchScope]);

  useEffect(() => {
    if (presented) void refreshScope(scope);
  }, [presented, scope, refreshScope]);

  const run = useCallback(
    async (coord: string, fn: () => Promise<unknown>) => {
      setBusyCoord(coord);
      setError(null);
      try {
        await fn();
        notifyAgentsPaletteRefresh(); // keep the AGENTS palette in sync
        await refreshAll(); // every tab agrees immediately (dev/47)
      } catch (e) {
        setError(e instanceof Error ? e.message : "Action failed");
      } finally {
        setBusyCoord(null);
      }
    },
    [refreshAll],
  );

  const cards = cardsByScope[scope] ?? [];
  // First-ever fetch for this scope only — cached tabs render instantly.
  const loading = cardsByScope[scope] === undefined && fetching;

  return {
    scope,
    setScope,
    cards,
    loading,
    busyCoord,
    error,
    reload: refreshAll,
    importAgent: (coord) => run(coord, () => agentsApi.import(coord)),
    removeImport: (coord) => run(coord, () => agentsApi.removeImport(coord)),
    install: (coord) =>
      run(coord, () => (projectId ? agentsApi.installToProject(projectId, coord) : Promise.resolve())),
    uninstall: (coord) =>
      run(coord, () => (projectId ? agentsApi.uninstallFromProject(projectId, coord) : Promise.resolve())),
    publish: (coord) => run(coord, () => agentsApi.publish(coord)),
    unpublish: (coord) => run(coord, () => agentsApi.unpublish(coord)),
  };
}
