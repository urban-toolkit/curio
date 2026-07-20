import { useCallback, useEffect, useState } from "react";
import { agentsApi, AgentCard } from "../../../api/agentsApi";
import { notifyAgentsPaletteRefresh } from "../../../utils/agentsPaletteEvents";

/**
 * Self-contained data hook for the Agents Catalog drawer. Owns the active scope,
 * the cards for that scope, and the lifecycle actions — all over ``agentsApi``.
 * Deliberately light on provider coupling (only ``projectId``) so it is easy to
 * test and reuse.
 */

export type AgentScope = "global" | "my-imports" | "installed";

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
  const [cards, setCards] = useState<AgentCard[]>([]);
  const [loading, setLoading] = useState(false);
  const [busyCoord, setBusyCoord] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const fetchScope = useCallback(
    async (s: AgentScope) => {
      setLoading(true);
      setError(null);
      try {
        let resp: { agents: AgentCard[] };
        if (s === "global") {
          resp = await agentsApi.catalog(projectId ?? undefined);
        } else if (s === "my-imports") {
          resp = await agentsApi.listImports();
        } else {
          resp = projectId ? await agentsApi.listProjectAgents(projectId) : { agents: [] };
        }
        setCards(resp.agents);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Failed to load agents");
        setCards([]);
      } finally {
        setLoading(false);
      }
    },
    [projectId],
  );

  const reload = useCallback(() => fetchScope(scope), [fetchScope, scope]);

  useEffect(() => {
    if (presented) fetchScope(scope);
  }, [presented, scope, fetchScope]);

  const run = useCallback(
    async (coord: string, fn: () => Promise<unknown>) => {
      setBusyCoord(coord);
      setError(null);
      try {
        await fn();
        notifyAgentsPaletteRefresh(); // keep the AGENTS palette in sync after a lifecycle change
        await fetchScope(scope);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Action failed");
      } finally {
        setBusyCoord(null);
      }
    },
    [fetchScope, scope],
  );

  return {
    scope,
    setScope,
    cards,
    loading,
    busyCoord,
    error,
    reload,
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
