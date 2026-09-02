import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  PackagePayload,
  ResolveConflict,
  packagesApi,
  refreshPackageRegistry,
} from "../../../api/packagesApi";
import { useFlowContext } from "../../../providers/FlowProvider";
import { BUILTIN_PACKAGE_ID } from "../../../registry/packageKeys";
import { useToastContext } from "../../../providers/ToastProvider";
import {
  applyProjectLockfile,
  setCurrentProjectPackages,
} from "../../../registry/projectPackagesStore";
import { draftFromInstalledPackagePayload } from "../../../utils/palettePackageFactoryDraft";
import { toApiPayload } from "../../../pages/nodes/factoryDraftModel";
import { InstallPermissionsDialog } from "./InstallPermissionsDialog";
import { DrawerHeader } from "./DrawerHeader";
import { DrawerTabs } from "./DrawerTabs";
import { usePackageArchiveImport } from "./usePackageArchiveImport";
import { PackageDetailModal } from "./PackageDetailModal";
import { PackageSearchRow } from "./PackageSearchRow";
import { PackageCard } from "./PackageCard";
import { EnvNote } from "./EnvNote";
import { DrawerFooter } from "./DrawerFooter";
import { DrawerTab, SortMode } from "./packageTypes";
import { sortPackages, matchesSearch } from "./packageUtils";
import { restartNotice } from "../../../services/packageRestartCopy";
import shell from "./CatalogDrawerShell.module.css";
import styles from "./NodeCatalogDrawer.module.css";
import { modalStackDepth } from "../../ModalShell";
import ConfirmDialog from "../../ConfirmDialog";


export interface NodeCatalogDrawerProps {
  /** When true, scrim fades in and the panel slides in from the right. */
  presented: boolean;
  onRequestClose: () => void;
  /** Called once the exit transition finishes (or immediately when motion is reduced). */
  onExitComplete: () => void;
}

const BUILTIN_PACKAGE_DIR = `${BUILTIN_PACKAGE_ID}@1`;

export const NodeCatalogDrawer: React.FC<NodeCatalogDrawerProps> = ({
  presented,
  onRequestClose,
  onExitComplete,
}) => {
  const drawerRef = useRef<HTMLElement>(null);

  // The drawer is *per-project*: Install/Uninstall write to the current
  // project's lockfile (see docs/NODE-CATALOG.md). When projectId is null
  // (user landed on /dataflow/new and hasn't saved yet), Install auto-saves
  // the dataflow first so the user isn't forced to interrupt their flow.
  const { projectId, packages: projectPackages, saveCurrentProject } = useFlowContext();
  const { showToast } = useToastContext();

  const [catalog, setCatalog] = useState<PackagePayload[]>([]);
  const [installed, setInstalled] = useState<PackagePayload[]>([]);
  const [tab, setTab] = useState<DrawerTab>("browse");
  const [detailPkg, setDetailPkg] = useState<PackagePayload | null>(null);
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState<SortMode>("new");
  const [pinned, setPinned] = useState(false);
  const [busy, setBusy] = useState(false);
  const [catalogPublishAllowed, setCatalogPublishAllowed] = useState(false);
  const [publishingPackageKey, setPublishingPackageKey] = useState<string | null>(null);
  const [reloadingPackageKey, setReloadingPackageKey] = useState<string | null>(null);
  const [cardActionDir, setCardActionDir] = useState<string | null>(null);
  const [installCandidate, setInstallCandidate] = useState<PackagePayload | null>(null);
  const [conflictReport, setConflictReport] = useState<ResolveConflict[] | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  // One slot for whichever confirmation is open (#197). The two destructive
  // actions here are mutually exclusive from the user's point of view, and a
  // single slot keeps the "what am I confirming" state next to the copy.
  const [confirmAction, setConfirmAction] = useState<{
    title: string;
    body: string;
    confirmLabel: string;
    run: () => Promise<void>;
  } | null>(null);
  // dev/92 B-2: the restart-honesty line after an install that changed
  // shared Python libraries (backend-declared, never inferred here).
  const [restartNoticeText, setRestartNoticeText] = useState<string | null>(null);
  const installedByDirRef = useRef<Map<string, PackagePayload>>(new Map());
  // When Install auto-saves a brand-new dataflow, the React state update
  // for `projectId` doesn't always make it into `confirmCatalogInstall`'s
  // closure before the user clicks Install on the dialog. Stash the freshly
  // created id here so the confirm handler has a synchronous fallback.
  const savedProjectIdRef = useRef<string | null>(null);

  /** Pulls the friendliest message off an unknown error and surfaces it as a banner. */
  const reportActionError = useCallback((label: string, err: unknown) => {
    const status = (err as { status?: number } | null)?.status;
    const body = (err as { body?: { error?: string } } | null)?.body;
    const message = (err as { message?: string } | null)?.message;
    const detail = body?.error ?? message ?? (status ? `HTTP ${status}` : "unknown error");
    setActionError(`${label}: ${detail}`);
    console.warn(`[NodeCatalogDrawer] ${label}:`, err);
  }, []);

  /** dirNames the current project has declared in its lockfile. Drives the
   * Install vs Uninstall affordance per card. */
  const projectInstalledDirs = useMemo(
    // A dataflow is created on its FIRST SAVE, so before that `projectPackages`
    // is empty and this tab rendered "No packages added to this dataflow yet."
    // - even though the account's defaults (curio.builtin, the examples, uhvi)
    // are seeded into the dataflow the moment it is saved. They ARE in this
    // dataflow, one save away. Its two peers do the same.
    //
    // This used to fetch the defaults itself and swap them in when there was no
    // project, which made the drawer a SECOND source of truth that could
    // disagree with the palette. ``ProjectLoader`` now seeds the unsaved
    // dataflow's scope from the same defaults, so both read the one store and
    // this can just follow the lockfile in every case.
    //
    // The builtin package is added unconditionally, as the palette filter also
    // treats it (``inDataflowScope``). It is in every dataflow by construction
    // -- the backend seeds it and refuses to uninstall it -- so the only state
    // its absence here can represent is "the lockfile has not arrived yet",
    // which used to render an "Add to project" button for something already
    // present and un-removable.
    () => new Set([...projectPackages, BUILTIN_PACKAGE_DIR]),
    [projectPackages],
  );

  /** dirNames in the user store (for the "Installed" tab listing + update detection). */
  const userStoreDirs = useMemo(
    () => new Set(installed.map((p) => p.dirName)),
    [installed],
  );

  const catalogByDir = useMemo(() => new Map(catalog.map((p) => [p.dirName, p])), [catalog]);
  const catalogPublishedDirs = useMemo(() => new Set(catalog.map((p) => p.dirName)), [catalog]);

  const reload = useCallback(async () => {
    // The drawer is the canonical "what's installed in THIS project" UI, so
    // also pull the project's lockfile fresh from the backend on every
    // reload — otherwise we trust React state (`useFlowContext().packages`)
    // which can drift from the backend across navigation paths that don't
    // remount ProjectLoader (e.g. installing via /catalog and coming back).
    // The pull is best-effort: 404 / network error just leaves the existing
    // store untouched.
    const promises: [
      ReturnType<typeof packagesApi.catalog>,
      ReturnType<typeof packagesApi.listInstalled>,
      ReturnType<typeof packagesApi.factoryCapabilities>,
      Promise<{ packages: string[] } | null>,
    ] = [
      packagesApi.catalog(),
      packagesApi.listInstalled(),
      packagesApi.factoryCapabilities(),
      projectId
        ? packagesApi.getProjectPackages(projectId).catch(() => null)
        : Promise.resolve(null),
    ];
    const [cat, mine, cap, projLock] = await Promise.all(promises);
    setCatalog(cat.packages.map((p) => ({ ...p, installed: userStoreDirs.has(p.dirName) })));
    setInstalled(mine.packages);
    installedByDirRef.current = new Map(mine.packages.map((p) => [p.dirName, p]));
    setCatalogPublishAllowed(cap.catalogPublish);
    if (projLock && Array.isArray(projLock.packages)) {
      // memo dev/101: when the backend's lockfile differs from the mirror,
      // the palette/registry must follow — not only the drawer's pill.
      if (applyProjectLockfile(projLock.packages)) {
        await refreshPackageRegistry();
      }
    }
  // userStoreDirs intentionally omitted — it's derived from `installed` which we set here.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  useEffect(() => {
    void reload().catch((err) => {
      reportActionError("Couldn't load catalog", err);
    });
  }, [reload, reportActionError]);

  useEffect(() => {
    if (!presented) return;
    drawerRef.current?.focus();
  }, [presented]);

  const handleDrawerTransitionEnd = useCallback(
    (e: React.TransitionEvent<HTMLElement>) => {
      if (e.target !== drawerRef.current) return;
      if (e.propertyName !== "transform") return;
      if (presented) return;
      onExitComplete();
    },
    [onExitComplete, presented],
  );

  useEffect(() => {
    if (!presented) return;
    const onKey = (ev: KeyboardEvent) => {
      // Defer to any open modal (see ModalShell's stack).
      if (modalStackDepth() > 0) return;
      // ...and to the pin. This used to close a pinned drawer, discarding the
      // pin the user had just set - the Agent drawer already honoured it.
      if (ev.key === "Escape" && !pinned) onRequestClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [presented, pinned, onRequestClose]);

  const filteredCatalog = useMemo(() => {
    return sortPackages(
      catalog.filter((p) => matchesSearch(p, search)),
      sort,
    );
  }, [catalog, search, sort]);

  const filteredInstalled = useMemo(
    // "Installed" in the drawer = installed in THIS project, not in the user store.
    () => installed.filter(
      (p) => projectInstalledDirs.has(p.dirName) && matchesSearch(p, search),
    ),
    [installed, projectInstalledDirs, search],
  );

  /**
   * The dataflow's id, saving it first if it does not have one yet.
   *
   * A dataflow is created on its FIRST SAVE, so every lockfile write from this
   * drawer has to cope with not having an id. Install already auto-saved;
   * Remove and Import bailed on ``if (!projectId) return``, which is why an
   * imported package could not be removed until the dataflow happened to be
   * saved (#220). Mirrors ``useDatasetCatalogDrawer``'s ``ensureProjectId``.
   *
   * Returns ``null`` when the save is refused — guests and shared viewers
   * cannot save — having already reported it, so callers just return.
   */
  const ensureSavedProjectId = useCallback(
    async (failureLabel: string): Promise<string | null> => {
      if (projectId) {
        savedProjectIdRef.current = projectId;
        return projectId;
      }
      try {
        const detail = await saveCurrentProject();
        const id = (detail as { id?: string } | undefined)?.id ?? null;
        savedProjectIdRef.current = id;
        return id;
      } catch (err) {
        reportActionError(failureLabel, err);
        return null;
      }
    },
    [projectId, saveCurrentProject, reportActionError],
  );

  const onInstall = useCallback(
    async (pkg: PackagePayload) => {
      if ((await ensureSavedProjectId("Couldn't save dataflow before adding")) === null) {
        return;
      }
      setInstallCandidate(pkg);
      try {
        const probe = await packagesApi.resolve([
          ...installed.map((p) => p.dirName),
          pkg.dirName,
        ]);
        setConflictReport(probe.conflicts);
      } catch (err) {
        const status = (err as { status?: number }).status;
        if (status === 409) {
          const body = (err as { body?: { conflicts: ResolveConflict[] } }).body;
          setConflictReport(body?.conflicts ?? []);
        } else {
          setInstallCandidate(null);
        }
      }
    },
    [installed, projectId, reportActionError, saveCurrentProject],
  );

  const confirmCatalogInstall = useCallback(async () => {
    const effectiveProjectId = projectId ?? savedProjectIdRef.current;
    if (!installCandidate || !effectiveProjectId) return;
    setBusy(true);
    setActionError(null);
    try {
      const result = await packagesApi.installToProject(
        effectiveProjectId, installCandidate.dirName,
      );
      if (result.restartRecommended?.libs?.length) {
        setRestartNoticeText(restartNotice(result.restartRecommended));
      }
      // Keep the lockfile store in sync — palette filter reads this.
      setCurrentProjectPackages(result.packages);
      await refreshPackageRegistry();
      await reload();
      setInstallCandidate(null);
      setConflictReport(null);
      showToast(`Added ${installCandidate.name} to this dataflow.`, "success");
    } catch (err) {
      reportActionError(`Couldn't add ${installCandidate.name}`, err);
    } finally {
      setBusy(false);
    }
  }, [installCandidate, projectId, reload, reportActionError, showToast]);

  // The shared pathway, which the Node Catalog PAGE header calls too, so the
  // two surfaces cannot drift. `projectId` is the only real difference between
  // them: the drawer runs inside a dataflow and drops the package into its
  // lockfile as well, the page has no dataflow to drop it into.
  const { importArchive } = usePackageArchiveImport({
    // ``savedProjectIdRef`` carries the id minted by an auto-save that has not
    // re-rendered yet, so an import into a previously-unsaved dataflow still
    // names a project to install into.
    projectId: projectId ?? savedProjectIdRef.current,
    reload,
    onError: reportActionError,
    onInstalledToProject: setCurrentProjectPackages,
  });

  const onPickArchive = useCallback(
    async (file: File) => {
      // Save first, so the import lands in THIS dataflow's lockfile and not
      // only in the account store. Importing into an unsaved dataflow used to
      // put the package on every dataflow's palette and none of their
      // lockfiles, which is the "imported packages are not scoped to a project"
      // half of #220.
      if ((await ensureSavedProjectId("Couldn't save dataflow before importing")) === null) {
        return;
      }
      // The drawer's own busy/error chrome; the shared hook owns the call.
      setBusy(true);
      setActionError(null);
      try {
        await importArchive(file);
      } finally {
        setBusy(false);
      }
    },
    [ensureSavedProjectId, importArchive],
  );

  const performUninstall = useCallback(async (pkg: PackagePayload) => {
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
      setCurrentProjectPackages(result.packages);
      await refreshPackageRegistry();
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
          ? `Removed ${pkg.name} from this dataflow ${extra}.`
          : `Removed ${pkg.name} from this dataflow.`,
        "success",
      );
    } catch (err) {
      reportActionError(`Couldn't remove ${pkg.name}`, err);
    } finally {
      setCardActionDir(null);
    }
  }, [ensureSavedProjectId, reload, reportActionError, showToast]);

  const onUninstall = useCallback((pkg: PackagePayload) => {
    // No `projectId` guard: an unsaved dataflow saves itself on confirm (see
    // performUninstall). Guarding here is what hid the action entirely.
    setConfirmAction({
      title: `Remove ${pkg.name}?`,
      // "from this dataflow", matching the button that opens this — the old
      // copy said "from this project" and contradicted it.
      //
      // The second paragraph is the part that was missing entirely. Removal is
      // not dataflow-scoped: `prune_unreferenced_packages` deletes the user's
      // store copy, drops it from defaults, and pip-uninstalls its Python
      // libraries from the interpreter Curio itself runs on — shared by every
      // dataflow and every user of this instance. Whether it fires depends on
      // the other dataflows' lockfiles, so the wording states the condition
      // rather than guessing the outcome.
      body:
        `Remove ${pkg.name} (${pkg.dirName}) from this dataflow?` +
        `\n\nIf no other dataflow uses it, it is also deleted from your account ` +
        `and its Python libraries are uninstalled from the shared environment, ` +
        `which affects every dataflow and everyone using this Curio.`,
      confirmLabel: "Remove",
      run: () => performUninstall(pkg),
    });
  }, [performUninstall]);

  const performUnpublishFromCatalog = useCallback(
    async (pkg: PackagePayload) => {
      setCardActionDir(pkg.dirName);
      setActionError(null);
      try {
        await packagesApi.unpublishFromCatalog(pkg.dirName);
        await reload();
        showToast(`Unpublished ${pkg.name}.`, "success");
      } catch (err) {
        reportActionError(`Couldn't unpublish ${pkg.name}`, err);
      } finally {
        setCardActionDir(null);
      }
    },
    [reload, reportActionError, showToast],
  );

  const onUnpublishFromCatalog = useCallback(
    (pkg: PackagePayload) => {
      setConfirmAction({
        title: `Unpublish ${pkg.name}?`,
        body: `Unpublish ${pkg.name} from the Node Catalog?\n\nThis removes the catalog listing. Copies already added to dataflows are not removed.`,
        confirmLabel: "Unpublish",
        run: () => performUnpublishFromCatalog(pkg),
      });
    },
    [performUnpublishFromCatalog],
  );

  const onPublishToCatalog = useCallback(async (dirName: string) => {
    const row = installedByDirRef.current.get(dirName);
    if (!row) return;
    setPublishingPackageKey(dirName);
    setActionError(null);
    try {
      const draft = draftFromInstalledPackagePayload(row);
      await packagesApi.factoryPublishCatalog({
        ...(toApiPayload(draft) as Record<string, unknown>),
        replace: true,
      });
      await reload();
      showToast(`Published ${row.name}.`, "success");
    } catch (err) {
      reportActionError(`Couldn't publish ${row.name}`, err);
    } finally {
      setPublishingPackageKey(null);
    }
  }, [reload, reportActionError, showToast]);

  /**
   * Re-copy a package from the shared catalog over the user's installed copy.
   *
   * This is the authoring loop for a package you are editing under
   * `packages/`. Install is a no-op once a copy exists in the user store
   * (`_ensure_user_store_install`), so without an explicit reload your edits —
   * including a rebuilt `scripts/behaviors.js` — stay invisible and the only
   * workaround is uninstalling from every project and installing again.
   *
   * The page is reloaded afterwards rather than just refreshing the registry:
   * `loadPackageBehaviorScripts` de-dupes injected bundles by package
   * coordinate, so a custom-UI package's rebuilt bundle would be skipped for
   * the rest of the session. A reload is the honest way to guarantee the new
   * behavior code is the one running.
   */
  const onReloadFromCatalog = useCallback(
    async (pkg: PackagePayload) => {
      setReloadingPackageKey(pkg.dirName);
      setActionError(null);
      try {
        await packagesApi.installFromCatalog(pkg.dirName, { replace: true });
        window.location.reload();
      } catch (err) {
        reportActionError(`Couldn't reload ${pkg.name}`, err);
        setReloadingPackageKey(null);
      }
    },
    [reportActionError],
  );

  // Export an installed package as a .curio.zip. MyPackagesList has always
  // rendered this control when handed a handler, but nothing ever passed one -
  // so the drawer's export affordance was dead code and the palette accordion
  // was the only way out. Same call the palette makes; failures surface as a
  // toast because a download has no other visible failure state.
  const onExportArchive = useCallback(
    async (pkg: PackagePayload) => {
      try {
        await packagesApi.download(pkg.dirName);
      } catch (err) {
        reportActionError(`Couldn't export ${pkg.dirName}`, err);
      }
    },
    [reportActionError],
  );

  return (
    <>
      <div
        className={`${shell.overlayRoot} ${styles.overlayRoot} ${
          presented ? shell.overlayRootPresented : ""
        }`}
        // The drawer stays mounted through its exit slide, and the panel below
        // carries aria-modal="true" - so without this it advertises a modal
        // dialog to assistive tech while sliding away. Its two siblings
        // (DatasetCatalogDrawer, AgentCatalogDrawer) have always had it.
        aria-hidden={!presented}
        data-curio-node-catalog-drawer="true"
      >
        <button
          type="button"
          className={shell.scrim}
          aria-label="Close Node Catalog drawer"
          onClick={() => {
            if (!pinned) onRequestClose();
          }}
        />
        <aside
          ref={drawerRef}
          className={shell.drawer}
          role="dialog"
          aria-modal="true"
          aria-labelledby="node-catalog-drawer-title"
          tabIndex={-1}
          onTransitionEnd={handleDrawerTransitionEnd}
        >
          <DrawerHeader
            pinned={pinned}
            onPinToggle={() => setPinned((v) => !v)}
            onClose={onRequestClose}
          />

          <PackageSearchRow
            search={search}
            sort={sort}
            onSearchChange={setSearch}
            onSortChange={(value) => setSort(value as SortMode)}
          />

          <DrawerTabs
            tab={tab}
            installedCount={projectInstalledDirs.size}
            onChange={setTab}
          />

          <div className={shell.scrollBody}>
            {restartNoticeText ? (
              <div className={styles.noticeBanner} role="status">
                <span className={styles.errorBannerText}>{restartNoticeText}</span>
                <button
                  type="button"
                  className={styles.noticeBannerDismiss}
                  aria-label="Dismiss restart notice"
                  onClick={() => setRestartNoticeText(null)}
                >
                  ×
                </button>
              </div>
            ) : null}
            {actionError ? (
              <div className={shell.errorBanner} role="alert">
                <span className={shell.errorBannerText}>{actionError}</span>
                <button
                  type="button"
                  className={shell.errorBannerDismiss}
                  aria-label="Dismiss error"
                  onClick={() => setActionError(null)}
                >
                  ×
                </button>
              </div>
            ) : null}
            {tab === "installed" ? (
              filteredInstalled.length === 0 ? (
                <div className={shell.empty}>
                  {projectInstalledDirs.size === 0
                    ? "No packages added to this dataflow yet."
                    : "No packages match the current filters."}
                </div>
              ) : (
                /* The SAME card as the Browse tab next door, in the same card
                   list. This tab rendered `MyPackagesList` - a compact
                   dot-and-row list with its own actions - so one drawer showed
                   its two tabs in two visual languages, and neither matched the
                   Data or Agent drawer, which use one card in both of theirs. */
                <div className={shell.cardList}>
                  {filteredInstalled.map((pkg) => (
                    <PackageCard
                      key={pkg.dirName}
                      pkg={pkg}
                      isInstalled
                      hasUpdate={
                        catalogByDir.get(pkg.dirName) != null
                        && catalogByDir.get(pkg.dirName)!.version !== pkg.version
                      }
                      catalogRow={catalogByDir.get(pkg.dirName)}
                      busy={busy}
                      cardActionDir={cardActionDir}
                      onOpenDetails={setDetailPkg}
                      onInstall={(p) => void onInstall(p)}
                      onUninstall={(p) => onUninstall(p)}
                      hasProject={Boolean(projectId)}
                    />
                  ))}
                </div>
              )
            ) : (
              <>
                {filteredCatalog.length === 0 ? (
                  <div className={shell.empty}>No packages match the current filters.</div>
                ) : (
                  <div className={shell.cardList}>
                    {filteredCatalog.map((pkg) => {
                      // "Installed" in the drawer means "in this project's
                      // lockfile" — the user-store presence is irrelevant
                      // for the per-project surface. The one exception is
                      // ``curio.builtin@*``: it ships with every Curio
                      // instance and can't be uninstalled, so it's always
                      // "installed" regardless of what the lockfile says
                      // (which matters for unsaved /dataflow/new dataflows
                      // and for legacy projects saved before the lockfile
                      // contract included it).
                      const isBuiltin = pkg.dirName.startsWith("curio.builtin@");
                      const isInstalled = isBuiltin || projectInstalledDirs.has(pkg.dirName);
                      const catalogRow = catalogByDir.get(pkg.dirName);
                      const userStoreRow = userStoreDirs.has(pkg.dirName)
                        ? installed.find((r) => r.dirName === pkg.dirName)
                        : undefined;
                      const hasUpdate =
                        isInstalled
                        && userStoreRow != null
                        && catalogRow != null
                        && catalogRow.version !== userStoreRow.version;
                      // Author actions (Publish / Unpublish) only make sense
                      // when the user has a local copy — symmetric with the
                      // /catalog page's Publish gating, and avoids inviting
                      // unpublish of someone else's package you don't own.
                      const hasLocalCopy = userStoreRow != null;
                      return (
                        <PackageCard
                          key={pkg.dirName}
                          pkg={pkg}
                          isInstalled={isInstalled}
                          hasUpdate={hasUpdate}
                          catalogRow={catalogRow}
                          busy={busy}
                          cardActionDir={cardActionDir}
                          // No publish/unpublish here: account-level decisions
                          // live in the Node Catalog page's detail drawer.
                          onOpenDetails={setDetailPkg}
                          onInstall={(p) => void onInstall(p)}
                          onUninstall={(p) => onUninstall(p)}
                          hasProject={Boolean(projectId)}
                        />
                      );
                    })}
                  </div>
                )}
              </>
            )}

            <EnvNote />
          </div>

          <DrawerFooter
            busy={busy}
            onSideload={(file) => void onPickArchive(file)}
          />
        </aside>
      </div>

      {/* The card's "View details". The Node Catalog was the only one of the
          three with no detail view anywhere; `PackageDetailModal` is that view,
          and it shows the FULL node list where this drawer caps it. */}
      {detailPkg ? (
        <PackageDetailModal pkg={detailPkg} onClose={() => setDetailPkg(null)} />
      ) : null}

      {installCandidate ? (
        <InstallPermissionsDialog
          pkg={installCandidate}
          conflicts={conflictReport ?? []}
          busy={busy}
          onCancel={() => {
            setInstallCandidate(null);
            setConflictReport(null);
          }}
          onConfirm={() => void confirmCatalogInstall()}
        />
      ) : null}

      {confirmAction ? (
        <ConfirmDialog
          title={confirmAction.title}
          body={confirmAction.body}
          confirmLabel={confirmAction.confirmLabel}
          destructive
          layer="overlay"
          onCancel={() => setConfirmAction(null)}
          onConfirm={() => {
            const { run } = confirmAction;
            setConfirmAction(null);
            void run();
          }}
        />
      ) : null}
    </>
  );
};
