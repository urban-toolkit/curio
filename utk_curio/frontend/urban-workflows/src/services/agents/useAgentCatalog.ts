/**
 * THE catalog hook (memo dev/142, F3): the one place the Agent Catalog is
 * listed and acted on, shared by the in-canvas drawer and the account-scope
 * page. Each surface keeps only its own view state (the drawer's active tab;
 * the page's search, sort, rail and selection) in a thin adapter over this.
 *
 * Listing + consistency semantics (memo dev/47), now written once:
 * - **Stale-while-revalidate scopes**: each scope keeps its last-known rows;
 *   `loading` is true only for the active scope's FIRST ever fetch, so a tab
 *   change never blanks previously loaded content.
 * - **Race guard**: a per-scope request sequence drops out-of-order responses.
 * - **Refresh after every action**: import/remove/publish/unpublish/install/
 *   uninstall notify the AGENTS palette (one chokepoint) and refresh every
 *   scope the surface uses, so all of its tabs agree immediately.
 * - **Errors keep the cached rows** — a banner over content, never instead.
 * - **Account scope by default**: with no project id the listing is unscoped
 *   (`installedInProject` is not meaningful there); the project actions
 *   resolve their dataflow at click time through `onEnsureProject`, creating
 *   it when it has never been saved (#190, #199).
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { agentsApi } from "./agentsApi";
import { notifyAgentCatalogRefresh } from "./agentEvents";
import type { AgentCard, AgentCatalogFacets } from "./types";

export type AgentCatalogScope = "browse" | "installed";
export type AgentCatalogVerb = "add" | "remove" | "publish" | "unpublish" | "install" | "uninstall";
/** What an action needs of a card: the coordinate, and the name for messages. */
export type AgentCardRef = Pick<AgentCard, "dirName"> & Partial<Pick<AgentCard, "name">>;

export interface UseAgentCatalogOptions {
  /** False while the surface is hidden: nothing is fetched. */
  enabled?: boolean;
  /** The open dataflow, when the surface has one; absent = account scope. */
  projectId?: string | null;
  /** The scope whose rows `cards` and `loading` describe. */
  activeScope?: AgentCatalogScope;
  /** Every scope the surface uses: all are refreshed after an action, and
   *  the inactive ones are fetched once up front (a tab badge is not worth an
   *  error banner, so that prefetch fails silently). */
  scopes?: AgentCatalogScope[];
  /** Creates and saves the dataflow when it has never been persisted, and
   *  answers with its id (`FlowProvider.ensureProjectId`). */
  onEnsureProject?: () => Promise<string | null>;
  /** Told the success message of a project action, once the refresh landed. */
  onSuccess?: (message: string) => void;
  /** How a failed action reads; the default is the error's own message. */
  describeActionError?: (verb: AgentCatalogVerb, card: AgentCardRef, detail: string) => string;
  /** The load error when the failure carries no message. */
  loadErrorFallback?: string;
}

export interface AgentCatalogState {
  /** The active scope's rows (the cache, or nothing yet). */
  cards: AgentCard[];
  cardsByScope: Partial<Record<AgentCatalogScope, AgentCard[]>>;
  facets: AgentCatalogFacets | null;
  loading: boolean;
  busyCoord: string | null;
  error: string | null;
  dismissError: () => void;
  /** Refresh every scope the surface uses; an id names a dataflow the prop
   *  does not carry yet. */
  reload: (idOverride?: string) => Promise<void>;
  importAgent: (card: AgentCardRef) => Promise<void>;
  removeImport: (card: AgentCardRef) => Promise<void>;
  publish: (card: AgentCardRef) => Promise<void>;
  unpublish: (card: AgentCardRef) => Promise<void>;
  install: (card: AgentCardRef) => Promise<void>;
  uninstall: (card: AgentCardRef) => Promise<void>;
}

const DEFAULT_SCOPES: AgentCatalogScope[] = ["browse"];

export function useAgentCatalog(options: UseAgentCatalogOptions = {}): AgentCatalogState {
  const {
    enabled = true,
    projectId = null,
    activeScope = "browse",
    scopes = DEFAULT_SCOPES,
    onEnsureProject,
    onSuccess,
    describeActionError,
    loadErrorFallback = "Failed to load agents",
  } = options;
  const [cardsByScope, setCardsByScope] = useState<Partial<Record<AgentCatalogScope, AgentCard[]>>>({});
  const [facets, setFacets] = useState<AgentCatalogFacets | null>(null);
  const [fetching, setFetching] = useState(enabled);
  const [busyCoord, setBusyCoord] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const seqRef = useRef<Record<AgentCatalogScope, number>>({ browse: 0, installed: 0 });
  const scopesKey = scopes.join(",");

  /** The dataflow this surface just created, before the prop catches up.
   *
   * `projectId` arrives from FlowProvider, so on the render where an install
   * creates the dataflow it is still null. Refetching against null asks for an
   * unscoped listing, every card comes back `installedInProject: false`, and
   * the agent that was just added still offers "Add to project". Reading the
   * id through this ref closes that window; the prop takes over next render.
   */
  const createdProjectIdRef = useRef<string | null>(null);
  const activeProjectId = () => projectId ?? createdProjectIdRef.current;

  // A project switch invalidates every scope's cache: installed state is per-project.
  useEffect(() => {
    if (projectId) createdProjectIdRef.current = null;
    setCardsByScope({});
  }, [projectId]);

  const fetchScope = useCallback(
    async (scope: AgentCatalogScope, idOverride?: string) => {
      const seq = ++seqRef.current[scope];
      const id = idOverride ?? activeProjectId();
      let resp: { agents: AgentCard[]; items?: AgentCard[]; facets?: AgentCatalogFacets };
      if (scope === "browse") {
        resp = await agentsApi.catalog(id ?? undefined);
      } else {
        // No project yet (a dataflow is created on its first save), so there
        // is no lockfile to read. The account's "in all projects" agents
        // belong here: `save_project` seeds them into this dataflow the moment
        // it exists. Once there IS a project its lockfile is the truth again.
        resp = id ? await agentsApi.listProjectAgents(id) : await agentsApi.listImports();
      }
      if (seqRef.current[scope] !== seq) return; // out-of-order response — dropped
      // An unscoped listing cannot know `installedInProject`, so publishing one
      // over a scoped listing silently un-marks every installed agent.
      if (!id && activeProjectId()) return;
      setCardsByScope((prev) => ({ ...prev, [scope]: resp.items ?? resp.agents }));
      if (scope === "browse" && resp.facets !== undefined) setFacets(resp.facets ?? null);
    },
    [projectId],
  );

  const refreshScope = useCallback(
    async (scope: AgentCatalogScope) => {
      setError(null);
      setFetching(true);
      try {
        await fetchScope(scope);
      } catch (e) {
        // Cached rows stay — the banner renders over content, not instead.
        setError((e as Error)?.message ?? loadErrorFallback);
      } finally {
        setFetching(false);
      }
    },
    [fetchScope, loadErrorFallback],
  );

  const reload = useCallback(
    async (idOverride?: string) => {
      setError(null);
      const results = await Promise.allSettled(scopes.map((s) => fetchScope(s, idOverride)));
      const failed = results.find((r): r is PromiseRejectedResult => r.status === "rejected");
      if (failed) {
        const reason = failed.reason;
        setError(reason instanceof Error ? reason.message : "Failed to refresh agents");
      }
    },
    [fetchScope, scopesKey], // scopesKey stands in for the array's identity

  );

  useEffect(() => {
    if (enabled) void refreshScope(activeScope);
  }, [enabled, activeScope, refreshScope]);

  // The inactive scopes a surface uses (a tab badge counts that scope's rows)
  // are fetched once up front, so a count never reads 0 until its tab is
  // clicked. A badge is not worth an error banner; the tab still loads on click.
  useEffect(() => {
    if (!enabled) return;
    for (const scope of scopes) {
      if (scope === activeScope || cardsByScope[scope] !== undefined) continue;
      void fetchScope(scope).catch(() => undefined);
    }
  }, [enabled, activeScope, scopesKey, cardsByScope, fetchScope]); // scopesKey stands in for the array's identity

  /** Run one action, then keep every scope and the palette in agreement. */
  const run = useCallback(
    async (verb: AgentCatalogVerb, card: AgentCardRef, fn: () => Promise<unknown>, successMessage?: string) => {
      setBusyCoord(card.dirName);
      setError(null);
      try {
        // A per-project action answers with the id of the dataflow it acted on,
        // which may be one it had to create; only a string is a dataflow id.
        const result = await fn();
        const actedOn = typeof result === "string" ? result : undefined;
        notifyAgentCatalogRefresh(); // one notify fans out to the palette and every other surface
        await reload(actedOn); // every scope agrees immediately (dev/47)
        // Only on the success path, and only once the refresh has landed, so
        // a toast never contradicts what the cards show.
        if (successMessage && onSuccess) onSuccess(successMessage);
      } catch (e) {
        const detail = (e as Error)?.message;
        setError(describeActionError ? describeActionError(verb, card, detail ?? "unknown error") : detail ?? "Action failed");
      } finally {
        setBusyCoord(null);
      }
    },
    [reload, onSuccess, describeActionError],
  );

  /** The dataflow to act on, creating it if this one has never been saved.
   *  Throws rather than returning null so `run`'s catch surfaces it. */
  const resolveProjectId = useCallback(async (): Promise<string> => {
    const known = activeProjectId();
    if (known) return known;
    const created = onEnsureProject ? await onEnsureProject() : null;
    if (!created) throw new Error("Couldn't save this dataflow, so nothing was added to it.");
    createdProjectIdRef.current = created;
    return created;
  }, [projectId, onEnsureProject]);

  const importAgent = useCallback((card: AgentCardRef) => run("add", card, () => agentsApi.import(card.dirName)), [run]);
  const removeImport = useCallback((card: AgentCardRef) => run("remove", card, () => agentsApi.removeImport(card.dirName)), [run]);
  const publish = useCallback((card: AgentCardRef) => run("publish", card, () => agentsApi.publish(card.dirName)), [run]);
  const unpublish = useCallback((card: AgentCardRef) => run("unpublish", card, () => agentsApi.unpublish(card.dirName)), [run]);
  const install = useCallback(
    (card: AgentCardRef) =>
      run("install", card, async () => {
        const id = await resolveProjectId();
        await agentsApi.installToProject(id, card.dirName);
        return id;
      }, `Added ${card.name ?? card.dirName} to this project.`),
    [run, resolveProjectId],
  );
  const uninstall = useCallback(
    (card: AgentCardRef) =>
      run("uninstall", card, async () => {
        const id = await resolveProjectId();
        await agentsApi.uninstallFromProject(id, card.dirName);
        return id;
      }, `Removed ${card.name ?? card.dirName} from this project.`),
    [run, resolveProjectId],
  );
  const dismissError = useCallback(() => setError(null), []);

  const cards = cardsByScope[activeScope] ?? [];
  // First-ever fetch for the active scope only — cached tabs render instantly.
  const loading = cardsByScope[activeScope] === undefined && fetching;

  return useMemo(
    () => ({ cards, cardsByScope, facets, loading, busyCoord, error, dismissError, reload,
             importAgent, removeImport, publish, unpublish, install, uninstall }),
    [cards, cardsByScope, facets, loading, busyCoord, error, dismissError, reload,
     importAgent, removeImport, publish, unpublish, install, uninstall],
  );
}
