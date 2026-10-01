/**
 * THE node-catalog hook (memo dev/143, F3): the one place the Node Catalog is
 * listed and acted on, shared by the in-canvas drawer and the account-scope
 * page. Each surface keeps only its own view state (the drawer's tab, pin and
 * detail modal; the page's search, sort, filters and selection) in a thin
 * adapter over this. The shape follows `services/agents/useAgentCatalog`.
 *
 * Scope is an option, not a second hook: `{ kind: "project", projectId }` acts
 * on one dataflow's lockfile (install / uninstall) and follows the backend's
 * lockfile on reload; `{ kind: "defaults" }` acts on the account's
 * always-installed set. Everything that touches the node-kind registry or the
 * DOM is injected by the surface (`refreshRegistry`, `onProjectLockfile`,
 * `onInstalledToProject`, `onEnsureProject`, `reloadWindow`, `showToast`), so
 * this layer stays registry-free (memo §3.4 rule 5) and the callers keep the
 * exact behavior they had: the same call order, the same toasts, the same
 * error banners.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { packagesApi } from "./packagesApi";
import { dependencyFailureNotice } from "./packageDependencyNotice";
import { restartNotice } from "./packageRestartCopy";
import type { PackagePayload, ResolveConflict } from "./types";

export type PackageCatalogScope =
  | { kind: "project"; projectId: string | null }
  | { kind: "defaults" };

export interface UsePackageCatalogOptions {
  scope: PackageCatalogScope;
  /** Renders a toast; `kind` defaults to error at the provider, so every success says so. */
  showToast?: (message: string, kind: "success" | "error") => void;
  /**
   * Project scope: saves a dataflow that has never been saved (a dataflow is
   * created on its FIRST SAVE) and answers its id, or `null` when the save was
   * refused; a throw is reported as the action's failure banner, labelled with
   * what the save was for ("Couldn't save dataflow before adding").
   */
  onEnsureProject?: () => Promise<string | null>;
  /** Project scope: captured BEFORE the listing is fetched (the lockfile store's
   *  revision), handed back to `onProjectLockfile` so a local write that landed
   *  during the fetch is never undone by an older lockfile. */
  beforeReload?: () => unknown;
  /** Project scope: the backend's lockfile for this dataflow, fresh on every
   *  reload; the surface applies it to the mirror the palette reads and, when it
   *  changed, refreshes the registry (memo dev/101). */
  onProjectLockfile?: (packages: string[], token: unknown) => Promise<void> | void;
  /** Project scope: keep the lockfile mirror in sync after an install / uninstall. */
  onInstalledToProject?: (packages: string[]) => void;
  /** After a mutation that changed the installed set — the palette re-renders. */
  refreshRegistry?: () => Promise<void>;
  /** After "Reload from catalog": a full page reload is the honest way to run the rebuilt bundle. */
  reloadWindow?: () => void;
  /** A prefix for the console warning that accompanies every action error (the drawer logs; the page does not). */
  logLabel?: string;
}

export interface PackageCatalogState {
  /** The shared catalog's rows (`installed` marks rows the user store holds). */
  catalog: PackagePayload[];
  /** The user store's rows. */
  installed: PackagePayload[];
  installedByDir: Map<string, PackagePayload>;
  catalogByDir: Map<string, PackagePayload>;
  catalogPublishedDirs: Set<string>;
  catalogPublishAllowed: boolean;
  /** Defaults scope: the account's always-installed set; empty in project scope. */
  defaults: Set<string>;
  busy: boolean;
  publishingPackageKey: string | null;
  reloadingPackageKey: string | null;
  cardActionDir: string | null;
  actionError: string | null;
  /** Project scope: the dev/92 restart-honesty line after an install changed shared libraries. */
  restartNoticeText: string | null;
  /** Defaults scope: how many projects the last install patched. */
  lastInstallSummary: string | null;
  installCandidate: PackagePayload | null;
  /** Whether the open review adds the candidate or updates the store copy to it. */
  installMode: "add" | "update";
  conflictReport: ResolveConflict[] | null;
  /** Project scope: the dataflow's id, or the one an auto-save just minted before the prop caught up. */
  effectiveProjectId: string | null;
  /** Project scope: the dataflow's id, saving it first if it has none; `null` (already reported) when the save is refused. */
  ensureProjectId: (failureLabel: string) => Promise<string | null>;
  reload: () => Promise<void>;
  reportActionError: (label: string, err: unknown) => void;
  dismissActionError: () => void;
  dismissInstallSummary: () => void;
  dismissRestartNotice: () => void;
  /** The pre-install conflict probe: opens the install review for *pkg*. */
  probeInstall: (pkg: PackagePayload) => Promise<void>;
  /** The same review for an update: *pkg* is the catalog row the store copy is replaced with. */
  probeUpdate: (pkg: PackagePayload) => Promise<void>;
  /** Install (or update to) the reviewed candidate. */
  confirmInstall: () => Promise<void>;
  cancelInstall: () => void;
  /** Project scope only. */
  uninstallFromProject: (pkg: PackagePayload) => Promise<void>;
  publish: (dirName: string) => Promise<void>;
  unpublish: (target: PackagePayload | string) => Promise<void>;
  reloadFromCatalog: (pkg: PackagePayload) => Promise<void>;
  exportArchive: (pkg: PackagePayload) => Promise<void>;
}

const noop = () => undefined;
const resolved = async () => undefined;

/**
 * The pre-install conflict probe both install reviews run (memo dev/143 §3.4
 * rule 2): resolve the would-be set — every installed package plus the
 * candidate — and answer its conflicts. The resolve route reports a real
 * conflict set with a 409 body, so that status is an answer, not a failure;
 * any other error propagates to the caller's own handling.
 */
export async function probeInstallConflicts(dirNames: string[]): Promise<ResolveConflict[]> {
  try {
    const probe = await packagesApi.resolve(dirNames);
    return probe.conflicts;
  } catch (err) {
    const status = (err as { status?: number }).status;
    if (status === 409) {
      return (err as { body?: { conflicts?: ResolveConflict[] } }).body?.conflicts ?? [];
    }
    throw err;
  }
}

export function usePackageCatalog(options: UsePackageCatalogOptions): PackageCatalogState {
  const {
    scope,
    showToast = noop,
    onEnsureProject,
    beforeReload,
    onProjectLockfile,
    onInstalledToProject = noop,
    refreshRegistry = resolved,
    reloadWindow = () => window.location.reload(),
    logLabel,
  } = options;
  const projectId = scope.kind === "project" ? scope.projectId : null;

  const [catalog, setCatalog] = useState<PackagePayload[]>([]);
  const [installed, setInstalled] = useState<PackagePayload[]>([]);
  const [defaults, setDefaults] = useState<Set<string>>(new Set());
  const [catalogPublishAllowed, setCatalogPublishAllowed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [publishingPackageKey, setPublishingPackageKey] = useState<string | null>(null);
  const [reloadingPackageKey, setReloadingPackageKey] = useState<string | null>(null);
  const [cardActionDir, setCardActionDir] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [restartNoticeText, setRestartNoticeText] = useState<string | null>(null);
  const [lastInstallSummary, setLastInstallSummary] = useState<string | null>(null);
  const [installCandidate, setInstallCandidate] = useState<PackagePayload | null>(null);
  const [installMode, setInstallMode] = useState<"add" | "update">("add");
  const [conflictReport, setConflictReport] = useState<ResolveConflict[] | null>(null);
  const installedByDirRef = useRef<Map<string, PackagePayload>>(new Map());
  // When an action auto-saves a brand-new dataflow, the React state update for
  // `projectId` doesn't always make it into `confirmInstall`'s closure before
  // the user clicks Install on the dialog. The freshly created id is stashed
  // here so the confirm handler has a synchronous fallback.
  const savedProjectIdRef = useRef<string | null>(null);

  /** Pulls the friendliest message off an unknown error and surfaces it as a banner. */
  const reportActionError = useCallback((label: string, err: unknown) => {
    const status = (err as { status?: number } | null)?.status;
    const body = (err as { body?: { error?: string } } | null)?.body;
    const message = (err as { message?: string } | null)?.message;
    const detail = body?.error ?? message ?? (status ? `HTTP ${status}` : "unknown error");
    setActionError(`${label}: ${detail}`);
    if (logLabel) console.warn(`[${logLabel}] ${label}:`, err);
  }, [logLabel]);

  const reload = useCallback(async () => {
    if (scope.kind === "project") {
      // The drawer is the canonical "what's installed in THIS project" UI, so
      // also pull the project's lockfile fresh from the backend on every
      // reload — otherwise the surface trusts React state, which can drift
      // from the backend across navigation paths that don't remount
      // ProjectLoader (e.g. installing via /catalog and coming back). The pull
      // is best-effort: 404 / network error just leaves the existing store
      // untouched. The token is captured BEFORE the fetch: if a local write
      // lands while these are in flight, the lockfile that comes back is older
      // than what the store already knows and applying it would undo that write.
      const token = beforeReload?.();
      const [cat, mine, cap, projLock] = await Promise.all([
        packagesApi.catalog(),
        packagesApi.listInstalled(),
        packagesApi.factoryCapabilities(),
        projectId
          ? packagesApi.getProjectPackages(projectId).catch(() => null)
          : Promise.resolve(null),
      ]);
      const storeDirs = new Set(mine.packages.map((p) => p.dirName));
      setCatalog(cat.packages.map((p) => ({ ...p, installed: storeDirs.has(p.dirName) })));
      setInstalled(mine.packages);
      installedByDirRef.current = new Map(mine.packages.map((p) => [p.dirName, p]));
      setCatalogPublishAllowed(cap.catalogPublish);
      if (projLock && Array.isArray(projLock.packages) && onProjectLockfile) {
        await onProjectLockfile(projLock.packages, token);
      }
      return;
    }
    const [cat, mine, cap, defaultsResp] = await Promise.all([
      packagesApi.catalog(),
      packagesApi.listInstalled(),
      packagesApi.factoryCapabilities(),
      packagesApi.getDefaults(),
    ]);
    setCatalog(cat.packages);
    setInstalled(mine.packages);
    installedByDirRef.current = new Map(mine.packages.map((p) => [p.dirName, p]));
    setCatalogPublishAllowed(cap.catalogPublish);
    setDefaults(new Set(defaultsResp.packages));
  }, [scope.kind, projectId, beforeReload, onProjectLockfile]);

  useEffect(() => {
    void reload().catch((err) => reportActionError("Couldn't load catalog", err));
  }, [reload, reportActionError]);

  const installedByDir = useMemo(() => new Map(installed.map((p) => [p.dirName, p])), [installed]);
  const catalogByDir = useMemo(() => new Map(catalog.map((p) => [p.dirName, p])), [catalog]);
  const catalogPublishedDirs = useMemo(() => new Set(catalog.map((p) => p.dirName)), [catalog]);

  /** Project scope: the dataflow's id, saving it first if it does not have one yet. */
  const ensureSavedProjectId = useCallback(
    async (failureLabel: string): Promise<string | null> => {
      if (projectId) {
        savedProjectIdRef.current = projectId;
        return projectId;
      }
      if (!onEnsureProject) return null;
      try {
        const id = await onEnsureProject();
        savedProjectIdRef.current = id;
        return id;
      } catch (err) {
        reportActionError(failureLabel, err);
        return null;
      }
    },
    [projectId, onEnsureProject, reportActionError],
  );

  const openReview = useCallback(
    async (pkg: PackagePayload, mode: "add" | "update") => {
      if (scope.kind === "project" && mode === "add") {
        if ((await ensureSavedProjectId("Couldn't save dataflow before adding")) === null) {
          return;
        }
      }
      setInstallMode(mode);
      setInstallCandidate(pkg);
      try {
        // An update's candidate is already in the store, so it is in `installed`.
        const dirs = installed.map((p) => p.dirName);
        setConflictReport(
          await probeInstallConflicts(mode === "update" ? dirs : [...dirs, pkg.dirName]),
        );
      } catch {
        // A probe that failed for any reason but a conflict report: no review to show.
        setInstallCandidate(null);
      }
    },
    [scope.kind, installed, ensureSavedProjectId],
  );
  const probeInstall = useCallback((pkg: PackagePayload) => openReview(pkg, "add"), [openReview]);
  const probeUpdate = useCallback((pkg: PackagePayload) => openReview(pkg, "update"), [openReview]);

  const confirmInstall = useCallback(async () => {
    if (!installCandidate) return;
    if (installMode === "update") {
      // Lockfiles name only `<id>@<major>`, so replacing the one store copy
      // updates every project that uses it. A plain install of a package
      // already in the store copies nothing (#434).
      setBusy(true);
      setActionError(null);
      setLastInstallSummary(null);
      try {
        const result = await packagesApi.installFromCatalog(installCandidate.dirName, { replace: true });
        if (result.restartRecommended?.libs?.length) {
          setRestartNoticeText(restartNotice(result.restartRecommended));
        }
        await refreshRegistry();
        await reload();
        setInstallCandidate(null);
        setConflictReport(null);
        const lead = `Updated ${installCandidate.name} to ${result.package?.version ?? installCandidate.version}`;
        // A behavior bundle is injected once per page, so the new one runs only after a reload.
        const reloadHint = installCandidate.behaviorScript
          ? " Reload the page to run its new interface."
          : "";
        const notice = dependencyFailureNotice(lead, result);
        if (notice) {
          showToast(notice + reloadHint, "error");
        } else if (scope.kind === "project") {
          showToast(`${lead}.${reloadHint}`, "success");
        } else {
          setLastInstallSummary(reloadHint ? `${lead}.${reloadHint}` : lead);
        }
      } catch (err) {
        reportActionError(`Couldn't update ${installCandidate.name}`, err);
      } finally {
        setBusy(false);
      }
      return;
    }
    if (scope.kind === "project") {
      const effectiveProjectId = projectId ?? savedProjectIdRef.current;
      if (!effectiveProjectId) return;
      setBusy(true);
      setActionError(null);
      try {
        const result = await packagesApi.installToProject(effectiveProjectId, installCandidate.dirName);
        if (result.restartRecommended?.libs?.length) {
          setRestartNoticeText(restartNotice(result.restartRecommended));
        }
        // Keep the lockfile store in sync — palette filter reads this.
        onInstalledToProject(result.packages);
        await refreshRegistry();
        await reload();
        setInstallCandidate(null);
        setConflictReport(null);
        // The package arrived, but one of its libraries cannot be imported. pip
        // treats matching metadata as satisfaction, so a wheel whose native
        // extension is broken installs without complaint and this toast is the
        // last place the failure is still connected to the package that brought
        // it in. After this the user meets it as a node's ImportError.
        const notice = dependencyFailureNotice(`Added ${installCandidate.name}`, result);
        if (notice) {
          showToast(notice, "error");
        } else {
          showToast(`Added ${installCandidate.name} to this project.`, "success");
        }
      } catch (err) {
        reportActionError(`Couldn't add ${installCandidate.name}`, err);
      } finally {
        setBusy(false);
      }
      return;
    }
    setBusy(true);
    setActionError(null);
    setLastInstallSummary(null);
    try {
      const result = await packagesApi.installToDefaults(installCandidate.dirName);
      const succeeded = result.projects.filter((p) => p.ok).length;
      const failed = result.projects.filter((p) => !p.ok);
      const proj = result.projects.length;
      const summary =
        failed.length === 0
          ? `Added ${installCandidate.name} to ${proj} project${proj === 1 ? "" : "s"}` +
            (proj === 0 ? " (no existing projects; will seed into new ones)" : "")
          : `Added to ${succeeded}/${proj} projects; ${failed.length} failed: ${failed.map((f) => f.id).join(", ")}`;
      setLastInstallSummary(summary);
      // The blue summary banner says how many projects were patched, which is
      // not the same question. A library that installed and cannot be imported
      // makes every one of those projects reference a package whose nodes will
      // raise, so it gets the error channel rather than a line in a notice
      // about counts.
      const notice = dependencyFailureNotice(`Added ${installCandidate.name}`, result);
      if (notice) showToast(notice, "error");
      await refreshRegistry();
      await reload();
      setInstallCandidate(null);
      setConflictReport(null);
    } catch (err) {
      reportActionError(`Couldn't add ${installCandidate.name}`, err);
    } finally {
      setBusy(false);
    }
  }, [installCandidate, installMode, scope.kind, projectId, onInstalledToProject, refreshRegistry, reload, reportActionError, showToast]);

  const uninstallFromProject = useCallback(async (pkg: PackagePayload) => {
    if (scope.kind !== "project") return;
    // Removing from a dataflow that has never been saved is a real request, not
    // a no-op: the package is in the palette because the account defaults put it
    // there, and taking it out has to be recorded somewhere. Save first, exactly
    // as adding does.
    const id = await ensureSavedProjectId("Couldn't save dataflow before removing");
    if (!id) return;
    setCardActionDir(pkg.dirName);
    setActionError(null);
    try {
      const result = await packagesApi.uninstallFromProject(id, pkg.dirName);
      onInstalledToProject(result.packages);
      await refreshRegistry();
      await reload();
      // The response says whether the prune actually fired; the UI used to read
      // only `packages` and throw the rest away, so a removal that deleted the
      // package from the account and pip-uninstalled its libraries from the
      // shared interpreter reported the same sentence as one that only edited
      // this dataflow's lockfile.
      const pruned = result.pruned ?? [];
      const fromDefaults = result.removedFromDefaults ?? [];
      const extra = [
        pruned.length ? "and from your account" : "",
        fromDefaults.length ? "and from your defaults" : "",
      ]
        .filter(Boolean)
        .join(" ");
      showToast(
        extra
          ? `Removed ${pkg.name} from this project ${extra}.`
          : `Removed ${pkg.name} from this project.`,
        "success",
      );
    } catch (err) {
      reportActionError(`Couldn't remove ${pkg.name}`, err);
    } finally {
      setCardActionDir(null);
    }
  }, [scope.kind, ensureSavedProjectId, onInstalledToProject, refreshRegistry, reload, reportActionError, showToast]);

  const publish = useCallback(async (dirName: string) => {
    const row = installedByDirRef.current.get(dirName);
    if (!row) return;
    setPublishingPackageKey(dirName);
    setActionError(null);
    try {
      await packagesApi.publishToCatalog(dirName, { replace: true });
      await reload();
      showToast(`Published ${row.name}.`, "success");
    } catch (err) {
      reportActionError(`Couldn't publish ${row.name}`, err);
    } finally {
      setPublishingPackageKey(null);
    }
  }, [reload, reportActionError, showToast]);

  const unpublish = useCallback(async (target: PackagePayload | string) => {
    const dirName = typeof target === "string" ? target : target.dirName;
    const row = typeof target === "string"
      ? installedByDirRef.current.get(dirName) ?? catalogByDir.get(dirName)
      : target;
    const name = row?.name ?? dirName;
    // The drawer keys its card spinner on the dir; the page keys its publish
    // button on it. Both are set, so either surface's affordance reads busy.
    setCardActionDir(dirName);
    setPublishingPackageKey(dirName);
    setActionError(null);
    try {
      await packagesApi.unpublishFromCatalog(dirName);
      await reload();
      showToast(`Unpublished ${name}.`, "success");
    } catch (err) {
      reportActionError(`Couldn't unpublish ${name}`, err);
    } finally {
      setCardActionDir(null);
      setPublishingPackageKey(null);
    }
  }, [catalogByDir, reload, reportActionError, showToast]);

  /**
   * Re-copy a package from the shared catalog over the user's installed copy —
   * the authoring loop for a package you are editing under `packages/`. The page
   * is reloaded afterwards rather than just refreshing the registry:
   * `loadPackageBehaviorScripts` de-dupes injected bundles by package
   * coordinate, so a custom-UI package's rebuilt bundle would be skipped for the
   * rest of the session. A reload is the honest way to guarantee the new
   * behavior code is the one running.
   */
  const reloadFromCatalog = useCallback(async (pkg: PackagePayload) => {
    setReloadingPackageKey(pkg.dirName);
    setActionError(null);
    try {
      await packagesApi.installFromCatalog(pkg.dirName, { replace: true });
      reloadWindow();
    } catch (err) {
      reportActionError(`Couldn't reload ${pkg.name}`, err);
      setReloadingPackageKey(null);
    }
  }, [reloadWindow, reportActionError]);

  /** Export an installed package as a .curio.zip; a download has no other visible failure state. */
  const exportArchive = useCallback(async (pkg: PackagePayload) => {
    try {
      await packagesApi.download(pkg.dirName);
    } catch (err) {
      reportActionError(`Couldn't export ${pkg.dirName}`, err);
    }
  }, [reportActionError]);

  const cancelInstall = useCallback(() => {
    setInstallCandidate(null);
    setConflictReport(null);
  }, []);
  const dismissActionError = useCallback(() => setActionError(null), []);
  const dismissInstallSummary = useCallback(() => setLastInstallSummary(null), []);
  const dismissRestartNotice = useCallback(() => setRestartNoticeText(null), []);

  // Read at render, as the drawer always did: an auto-save that has not
  // re-rendered yet still names the dataflow an import should land in.
  const effectiveProjectId = projectId ?? savedProjectIdRef.current;

  return useMemo(
    () => ({
      catalog, installed, installedByDir, catalogByDir, catalogPublishedDirs, catalogPublishAllowed, defaults,
      busy, publishingPackageKey, reloadingPackageKey, cardActionDir, actionError, restartNoticeText,
      lastInstallSummary, installCandidate, installMode, conflictReport, effectiveProjectId,
      ensureProjectId: ensureSavedProjectId,
      reload, reportActionError, dismissActionError, dismissInstallSummary, dismissRestartNotice,
      probeInstall, probeUpdate, confirmInstall, cancelInstall, uninstallFromProject, publish, unpublish,
      reloadFromCatalog, exportArchive,
    }),
    [catalog, installed, installedByDir, catalogByDir, catalogPublishedDirs, catalogPublishAllowed, defaults,
     busy, publishingPackageKey, reloadingPackageKey, cardActionDir, actionError, restartNoticeText,
     lastInstallSummary, installCandidate, installMode, conflictReport, effectiveProjectId, ensureSavedProjectId,
     reload, reportActionError, dismissActionError, dismissInstallSummary, dismissRestartNotice,
     probeInstall, probeUpdate, confirmInstall, cancelInstall, uninstallFromProject, publish, unpublish,
     reloadFromCatalog, exportArchive],
  );
}

