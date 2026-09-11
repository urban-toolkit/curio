import { useCallback, useEffect, useRef, useState } from "react";
import { agentsApi, AgentCard } from "../../../api/agentsApi";
import { notifyAgentCatalogRefresh } from "../../../utils/agentCatalogEvents";
import { useToastContext } from "../../../providers/ToastProvider";

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

/**
 * "imports" is gone. It listed the account's imported definitions inside a
 * PER-DATAFLOW drawer, which put an account-level scope in a place that is
 * about one project - and it was the surface reporting built-ins like
 * "Dataflow builder" and "Connection builder" as the user's own imports.
 *
 * Adding from this drawer goes straight to the open project. The account-level
 * decision ("Add to all projects") lives on the Agent Catalog PAGE, which is
 * the surface that has no project and can only speak about the account. Two
 * scopes, matching the Node drawer exactly.
 */
export type AgentScope = "browse" | "installed";

const ALL_SCOPES: AgentScope[] = ["browse", "installed"];

export interface AgentCatalogDrawerState {
  scope: AgentScope;
  setScope: (s: AgentScope) => void;
  cards: AgentCard[];
  loading: boolean;
  busyCoord: string | null;
  error: string | null;
  /** Agents in the open dataflow, for the "In project" tab badge. */
  installedCount: number;
  reload: () => Promise<void>;
  importAgent: (coord: string) => Promise<void>;
  removeImport: (coord: string) => Promise<void>;
  /** Takes the whole card, not just its coordinate, so the success toast can
   *  name the agent the way the card does (#198). */
  install: (card: AgentCard) => Promise<void>;
  uninstall: (card: AgentCard) => Promise<void>;
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
  const { showToast } = useToastContext();
  const [scope, setScope] = useState<AgentScope>("browse");
  const [cardsByScope, setCardsByScope] = useState<
    Partial<Record<AgentScope, AgentCard[]>>
  >({});
  const [fetching, setFetching] = useState(false);
  const [busyCoord, setBusyCoord] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const seqRef = useRef<Record<AgentScope, number>>({
    browse: 0,
    installed: 0,
  });

  /** The dataflow this drawer just created, before the prop catches up.
   *
   * `projectId` arrives from FlowProvider, so on the render where an install
   * creates the dataflow it is still null. Refetching against null asks for an
   * unscoped listing, every card comes back `installedInProject: false`, and the
   * agent that was just added still offers "Add to project". Reading the id
   * through this ref closes that window; the prop takes over on the next render.
   */
  const createdProjectIdRef = useRef<string | null>(null);
  const activeProjectId = () => projectId ?? createdProjectIdRef.current;

  // A project switch invalidates every scope's cache: installed state is
  // per-project.
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
      } else {
        // No project yet (a dataflow is created on its first save), so there is
        // no lockfile to read and this returned an empty list - the same blind
        // spot the agents palette had. The account's "in all projects" agents
        // belong here: `save_project` seeds them into this dataflow the moment
        // it exists, so listing them is a preview of a state one save away, not
        // a promise. Once there IS a project its lockfile is the truth again,
        // because the user may have removed an agent from THIS dataflow.
        resp = id
          ? await agentsApi.listProjectAgents(id)
          : await agentsApi.listImports();
      }
      if (seqRef.current[s] !== seq) return; // out-of-order response — dropped
      // An unscoped listing cannot know `installedInProject`, so publishing one
      // over a scoped listing silently un-marks every installed agent. That is
      // what left a just-added agent still offering "Add to project" after the
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

  // The "In project" tab's badge counts that scope's rows, so it needs them
  // fetched even while you are looking at "Browse all" - otherwise the count
  // reads 0 until you happen to click the tab it is describing. Its two peers
  // have the number up front because their drawers fetch one listing and
  // derive both tabs from it.
  useEffect(() => {
    if (!presented) return;
    if (cardsByScope.installed !== undefined) return;
    void fetchScope("installed").catch(() => {
      // A badge is not worth an error banner; the tab still loads on click.
    });
  }, [presented, cardsByScope.installed, fetchScope]);

  const run = useCallback(
    async (coord: string, fn: () => Promise<unknown>, successMessage?: string) => {
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
        // Only on the success path, and only once the refresh has landed, so
        // the toast never contradicts what the cards show. Failures keep the
        // drawer's own banner (a 5s toast is the wrong surface for them).
        if (successMessage) showToast(successMessage, "success");
      } catch (e) {
        setError(e instanceof Error ? e.message : "Action failed");
      } finally {
        setBusyCoord(null);
      }
    },
    [refreshAll, showToast],
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

  /** How many agents this dataflow has, for the "In project" tab badge.
   *
   *  Read off the project scope's own cached rows rather than the visible list,
   *  so the badge says the same thing whichever tab you are looking at - and
   *  matches what the Data and Node drawers put on the same tab. The Agent
   *  drawer was the only one of the three with no count there at all. */
  const installedCount = (cardsByScope.installed ?? []).length;

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
    installedCount,
    reload: refreshAll,
    importAgent: (coord) => run(coord, () => agentsApi.import(coord)),
    removeImport: (coord) => run(coord, () => agentsApi.removeImport(coord)),
    // Resolve the dataflow at click time rather than gating on one that already
    // exists. A never-saved dataflow is `projectId === null`, which used to
    // leave the Add button permanently disabled (#190, #199) - and, if it had
    // been clicked, silently resolve without adding anything. Both peers create
    // the project on the click instead; this is that, through the shared
    // `ensureProjectId`.
    install: (card) =>
      run(
        card.dirName,
        async () => {
          const id = await resolveProjectId();
          await agentsApi.installToProject(id, card.dirName);
          return id;
        },
        `Added ${card.name} to this project.`,
      ),
    uninstall: (card) =>
      run(
        card.dirName,
        async () => {
          const id = await resolveProjectId();
          await agentsApi.uninstallFromProject(id, card.dirName);
          return id;
        },
        `Removed ${card.name} from this project.`,
      ),
    publish: (coord) => run(coord, () => agentsApi.publish(coord)),
    unpublish: (coord) => run(coord, () => agentsApi.unpublish(coord)),
  };
}
