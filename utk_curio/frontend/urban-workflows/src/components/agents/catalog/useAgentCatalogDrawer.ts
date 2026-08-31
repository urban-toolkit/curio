import { useCallback, useEffect, useRef, useState } from "react";
import { agentsApi, AgentCard } from "../../../api/agentsApi";
import { notifyAgentCatalogRefresh } from "../../../utils/agentCatalogEvents";

/**
 * Self-contained data hook for the Agent Catalog drawer. Owns the active
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

export type AgentScope = "browse" | "imports" | "installed";

const ALL_SCOPES: AgentScope[] = ["browse", "imports", "installed"];

export interface AgentCatalogDrawerState {
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

export function useAgentCatalogDrawer(
  presented: boolean,
  projectId: string | null,
  /** Creates and saves the dataflow when it has never been persisted, and
   *  answers with its id. ``FlowProvider.ensureProjectId``; the Data catalog
   *  drawer takes the same dependency, and the Node catalog does the save by
   *  hand. Optional so a caller with a project already open (and every existing
   *  test) needs no change. */
  onEnsureProject?: () => Promise<string | null>,
): AgentCatalogDrawerState {
  const [scope, setScope] = useState<AgentScope>("browse");
  const [cardsByScope, setCardsByScope] = useState<
    Partial<Record<AgentScope, AgentCard[]>>
  >({});
  const [fetching, setFetching] = useState(false);
  const [busyCoord, setBusyCoord] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const seqRef = useRef<Record<AgentScope, number>>({
    browse: 0,
    imports: 0,
    installed: 0,
  });

  /** The dataflow this drawer just created, before the prop catches up.
   *
   * `projectId` arrives from FlowProvider, so on the render where an install
   * creates the dataflow it is still null. Refetching against null asks for an
   * unscoped listing, every card comes back `installedInProject: false`, and the
   * agent that was just added still offers "Add to dataflow". Reading the id
   * through this ref closes that window; the prop takes over on the next render.
   */
  const createdProjectIdRef = useRef<string | null>(null);
  const activeProjectId = () => projectId ?? createdProjectIdRef.current;

  // A project switch invalidates every scope's cache (installed state is
  // per-project; My imports marks installs against the open project too).
  useEffect(() => {
    if (projectId) createdProjectIdRef.current = null;
    setCardsByScope({});
  }, [projectId]);

  const fetchScope = useCallback(
    async (s: AgentScope, idOverride?: string) => {
      const seq = ++seqRef.current[s];
      const id = idOverride ?? activeProjectId();
      let resp: { agents: AgentCard[] };
      if (s === "browse") {
        resp = await agentsApi.catalog(id ?? undefined);
      } else if (s === "imports") {
        resp = await agentsApi.listImports(id ?? undefined);
      } else {
        resp = id ? await agentsApi.listProjectAgents(id) : { agents: [] };
      }
      if (seqRef.current[s] !== seq) return; // out-of-order response — dropped
      // An unscoped listing cannot know `installedInProject`, so publishing one
      // over a scoped listing silently un-marks every installed agent. That is
      // what left a just-added agent still offering "Add to dataflow" after the
      // drawer auto-saved the dataflow: the save re-rendered mid-flight and a
      // fetch that started before the id existed landed last.
      if (!id && activeProjectId()) return;
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

  const refreshAll = useCallback(async (idOverride?: string) => {
    setError(null);
    const results = await Promise.allSettled(
      ALL_SCOPES.map((s) => fetchScope(s, idOverride)),
    );
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
        // A per-project action answers with the id of the dataflow it acted on,
        // which may be one it had to create - the prop will not carry it until
        // the next render, and the refresh below cannot wait for that. The
        // account-scope actions answer with their own payloads; only a string
        // is a dataflow id.
        const result = await fn();
        const actedOn = typeof result === "string" ? result : undefined;
        notifyAgentCatalogRefresh(); // keep the AGENTS palette in sync
        await refreshAll(actedOn); // every tab agrees immediately (dev/47)
      } catch (e) {
        setError(e instanceof Error ? e.message : "Action failed");
      } finally {
        setBusyCoord(null);
      }
    },
    [refreshAll],
  );

  /** The dataflow to act on, creating it if this one has never been saved.
   *
   * Throws rather than returning null so `run`'s catch surfaces it in the
   * drawer's banner - the previous `Promise.resolve()` no-op reported success
   * for an add that never happened.
   */
  const resolveProjectId = useCallback(async (): Promise<string> => {
    const known = activeProjectId();
    if (known) return known;
    const created = onEnsureProject ? await onEnsureProject() : null;
    if (!created) throw new Error("Couldn't save this dataflow, so nothing was added to it.");
    createdProjectIdRef.current = created;
    return created;
  }, [projectId, onEnsureProject]);

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
    // Resolve the dataflow at click time rather than gating on one that already
    // exists. A never-saved dataflow is `projectId === null`, which used to
    // leave the Add button permanently disabled (#190, #199) - and, if it had
    // been clicked, silently resolve without adding anything. Both peers create
    // the project on the click instead; this is that, through the shared
    // `ensureProjectId`.
    install: (coord) =>
      run(coord, async () => {
        const id = await resolveProjectId();
        await agentsApi.installToProject(id, coord);
        return id;
      }),
    uninstall: (coord) =>
      run(coord, async () => {
        const id = await resolveProjectId();
        await agentsApi.uninstallFromProject(id, coord);
        return id;
      }),
    publish: (coord) => run(coord, () => agentsApi.publish(coord)),
    unpublish: (coord) => run(coord, () => agentsApi.unpublish(coord)),
  };
}
