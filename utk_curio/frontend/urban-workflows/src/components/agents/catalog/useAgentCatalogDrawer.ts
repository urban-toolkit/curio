import { useCallback, useMemo, useState } from "react";
import { useAgentCatalog, type AgentCard, type AgentCatalogScope } from "../../../services/agents";
import { useToastContext } from "../../../providers/ToastProvider";

/**
 * The Agent Catalog drawer's view of THE catalog hook (memo dev/142, F3): it
 * keeps only the drawer's own state — the active tab — and hands
 * `useAgentCatalog` the drawer's scopes, its project, its "create the dataflow
 * on the click" callback and its success toast. The listing semantics (memo
 * dev/47: stale-while-revalidate tabs, the race guard, all-scope refresh after
 * an action, errors over content) live in that hook, once.
 *
 * "imports" is gone. It listed the account's imported definitions inside a
 * PER-DATAFLOW drawer, which put an account-level scope in a place that is
 * about one project - and it was the surface reporting built-ins like
 * "Dataflow builder" and "Connection builder" as the user's own imports.
 *
 * Adding from this drawer goes straight to the open project. The account-level
 * decision ("Add to all projects") lives on the Agent Catalog PAGE, which is
 * the surface that has no project and can only speak about the account. Two
 * scopes, matching the Node drawer exactly. Publishing is not among its
 * actions: it belongs to the account, so it lives on /catalog/agents (#305)
 * and this drawer never offered it.
 */
export type AgentScope = AgentCatalogScope;

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
  const onSuccess = useCallback((message: string) => showToast(message, "success"), [showToast]);
  const catalog = useAgentCatalog({
    enabled: presented,
    projectId,
    activeScope: scope,
    scopes: ALL_SCOPES,
    onEnsureProject,
    onSuccess,
  });

  /** How many agents this dataflow has, for the "In project" tab badge.
   *  Read off the project scope's own cached rows rather than the visible list,
   *  so the badge says the same thing whichever tab you are looking at. */
  const installedCount = (catalog.cardsByScope.installed ?? []).length;

  return useMemo(
    () => ({
      scope,
      setScope,
      cards: catalog.cards,
      loading: catalog.loading,
      busyCoord: catalog.busyCoord,
      error: catalog.error,
      installedCount,
      reload: () => catalog.reload(),
      importAgent: (coord) => catalog.importAgent({ dirName: coord }),
      removeImport: (coord) => catalog.removeImport({ dirName: coord }),
      install: catalog.install,
      uninstall: catalog.uninstall,
    }),
    [scope, catalog, installedCount],
  );
}
