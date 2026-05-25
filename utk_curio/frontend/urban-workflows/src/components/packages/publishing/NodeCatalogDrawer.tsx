import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  PackagePayload,
  ResolveConflict,
  packagesApi,
  refreshPackageRegistry,
} from "../../../api/packagesApi";
import { useFlowContext } from "../../../providers/FlowProvider";
import { setCurrentProjectPackages } from "../../../registry/projectPackagesStore";
import { draftFromInstalledPackagePayload } from "../../../utils/palettePackageFactoryDraft";
import { toApiPayload } from "../../../pages/nodes/factoryDraftModel";
import { InstallPermissionsDialog } from "./InstallPermissionsDialog";
import { DrawerHeader } from "./DrawerHeader";
import { DrawerTabs } from "./DrawerTabs";
import { PackageSearchRow } from "./PackageSearchRow";
import { PackageCard } from "./PackageCard";
import { MyPackagesList } from "./MyPackagesList";
import { EnvNote } from "./EnvNote";
import { DrawerFooter } from "./DrawerFooter";
import { DrawerTab, SortMode } from "./packageTypes";
import { sortPackages, matchesSearch } from "./packageUtils";
import styles from "./NodeCatalogDrawer.module.css";


export interface NodeCatalogDrawerProps {
  /** When true, scrim fades in and the panel slides in from the right. */
  presented: boolean;
  onRequestClose: () => void;
  /** Called once the exit transition finishes (or immediately when motion is reduced). */
  onExitComplete: () => void;
}

export const NodeCatalogDrawer: React.FC<NodeCatalogDrawerProps> = ({
  presented,
  onRequestClose,
  onExitComplete,
}) => {
  const drawerRef = useRef<HTMLElement>(null);

  // The drawer is *per-project*: Install/Uninstall write to the current
  // project's lockfile (see docs/CATALOG.md). When projectId is null
  // (user landed on /dataflow/new and hasn't saved yet), the install
  // affordances are disabled — see `unsavedBanner` below.
  const { projectId, packages: projectPackages } = useFlowContext();

  const [catalog, setCatalog] = useState<PackagePayload[]>([]);
  const [installed, setInstalled] = useState<PackagePayload[]>([]);
  const [tab, setTab] = useState<DrawerTab>("browse");
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState<SortMode>("new");
  const [pinned, setPinned] = useState(false);
  const [busy, setBusy] = useState(false);
  const [catalogPublishAllowed, setCatalogPublishAllowed] = useState(false);
  const [publishingPackageKey, setPublishingPackageKey] = useState<string | null>(null);
  const [cardActionDir, setCardActionDir] = useState<string | null>(null);
  const [installCandidate, setInstallCandidate] = useState<PackagePayload | null>(null);
  const [conflictReport, setConflictReport] = useState<ResolveConflict[] | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const installedByDirRef = useRef<Map<string, PackagePayload>>(new Map());

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
    () => new Set(projectPackages),
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
    const [cat, mine, cap] = await Promise.all([
      packagesApi.catalog(),
      packagesApi.listInstalled(),
      packagesApi.factoryCapabilities(),
    ]);
    setCatalog(cat.packages.map((p) => ({ ...p, installed: userStoreDirs.has(p.dirName) })));
    setInstalled(mine.packages);
    installedByDirRef.current = new Map(mine.packages.map((p) => [p.dirName, p]));
    setCatalogPublishAllowed(cap.catalogPublish);
  // userStoreDirs intentionally omitted — it's derived from `installed` which we set here.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

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
    const onKey = (ev: KeyboardEvent) => {
      if (ev.key === "Escape") onRequestClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onRequestClose]);

  // Update candidates: project packages with a newer version available in the catalog.
  const updateCandidates = useMemo(() => {
    return installed.filter((row) => {
      if (!projectInstalledDirs.has(row.dirName)) return false;
      const catRow = catalogByDir.get(row.dirName);
      return catRow != null && catRow.version !== row.version;
    });
  }, [installed, catalogByDir, projectInstalledDirs]);

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

  const onInstall = useCallback(
    async (pkg: PackagePayload) => {
      if (!projectId) {
        reportActionError(
          "Save the dataflow first",
          new Error("install requires a saved project"),
        );
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
    [installed, projectId, reportActionError],
  );

  const confirmCatalogInstall = useCallback(async () => {
    if (!installCandidate || !projectId) return;
    setBusy(true);
    setActionError(null);
    try {
      const result = await packagesApi.installToProject(
        projectId, installCandidate.dirName,
      );
      // Keep the lockfile store in sync — palette filter reads this.
      setCurrentProjectPackages(result.packages);
      await refreshPackageRegistry();
      await reload();
      setInstallCandidate(null);
      setConflictReport(null);
    } catch (err) {
      reportActionError(`Couldn't install ${installCandidate.name}`, err);
    } finally {
      setBusy(false);
    }
  }, [installCandidate, projectId, reload, reportActionError]);

  const onPickArchive = useCallback(
    async (file: File) => {
      setBusy(true);
      setActionError(null);
      try {
        // Sideload still goes through the user-store install path; if a
        // project is open, drop the new package into its lockfile too so
        // the palette picks it up.
        const result = await packagesApi.uploadArchive(file, file.name);
        if (projectId) {
          const projResult = await packagesApi.installToProject(
            projectId, result.package.dirName,
          );
          setCurrentProjectPackages(projResult.packages);
        }
        await refreshPackageRegistry();
        await reload();
      } catch (err) {
        reportActionError(`Couldn't import ${file.name}`, err);
      } finally {
        setBusy(false);
      }
    },
    [projectId, reload, reportActionError],
  );

  const onUninstall = useCallback(async (pkg: PackagePayload) => {
    if (!projectId) return;
    if (!window.confirm(`Remove ${pkg.name} (${pkg.dirName}) from this project?`)) return;
    setCardActionDir(pkg.dirName);
    setActionError(null);
    try {
      const result = await packagesApi.uninstallFromProject(projectId, pkg.dirName);
      setCurrentProjectPackages(result.packages);
      await refreshPackageRegistry();
      await reload();
    } catch (err) {
      reportActionError(`Couldn't uninstall ${pkg.name}`, err);
    } finally {
      setCardActionDir(null);
    }
  }, [projectId, reload, reportActionError]);

  const onUnpublishFromCatalog = useCallback(
    async (pkg: PackagePayload) => {
      if (
        !window.confirm(
          `Unpublish ${pkg.name} (${pkg.dirName}) from the dev catalog?\n\nThis removes the entry under packages/. Installed copies in projects are not removed.`,
        )
      ) {
        return;
      }
      setCardActionDir(pkg.dirName);
      setActionError(null);
      try {
        await packagesApi.unpublishFromCatalog(pkg.dirName);
        await reload();
      } catch (err) {
        reportActionError(`Couldn't unpublish ${pkg.name}`, err);
      } finally {
        setCardActionDir(null);
      }
    },
    [reload, reportActionError],
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
    } catch (err) {
      reportActionError(`Couldn't publish ${row.name}`, err);
    } finally {
      setPublishingPackageKey(null);
    }
  }, [reload, reportActionError]);

  const myPackagesListProps = {
    installed: filteredInstalled,
    catalogByDir,
    catalogPublishedDirs,
    catalogPublishAllowed,
    publishingPackageKey,
    busy,
    onUninstall: (p: PackagePayload) => void onUninstall(p),
    onPublishToCatalog: (d: string) => void onPublishToCatalog(d),
  };

  const tabLabel: Record<DrawerTab, string> = {
    featured: "Browse",  // legacy: collapsed Featured into Browse
    browse: "Browse",
    installed: "Installed",
    updates: "Installed",  // legacy: Updates badge shows on Installed
  };

  const unsavedBanner = !projectId ? (
    <div className={styles.errorBanner} role="status">
      <span className={styles.errorBannerText}>
        Save this dataflow first to install packages into it.
      </span>
    </div>
  ) : null;

  return (
    <>
      <div
        className={`${styles.overlayRoot} ${presented ? styles.overlayRootPresented : ""}`}
        data-curio-node-catalog-drawer="true"
      >
        <button
          type="button"
          className={styles.scrim}
          aria-label="Close node catalog drawer"
          onClick={() => {
            if (!pinned) onRequestClose();
          }}
        />
        <aside
          ref={drawerRef}
          className={styles.drawer}
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
            onSortChange={setSort}
          />

          <DrawerTabs
            tab={tab === "featured" || tab === "updates" ? "browse" : tab}
            installedCount={projectInstalledDirs.size}
            updateCount={updateCandidates.length}
            onChange={setTab}
          />

          <div className={styles.scrollBody}>
            {unsavedBanner}
            {actionError ? (
              <div className={styles.errorBanner} role="alert">
                <span className={styles.errorBannerText}>{actionError}</span>
                <button
                  type="button"
                  className={styles.errorBannerDismiss}
                  aria-label="Dismiss error"
                  onClick={() => setActionError(null)}
                >
                  ×
                </button>
              </div>
            ) : null}
            {tab === "installed" ? (
              filteredInstalled.length === 0 ? (
                <div className={styles.empty}>
                  {projectInstalledDirs.size === 0
                    ? "No packages installed in this project yet."
                    : "No packages match the current filter."}
                </div>
              ) : (
                <MyPackagesList {...myPackagesListProps} />
              )
            ) : (
              <>
                <p className={styles.sectionLabel}>{tabLabel[tab]}</p>

                {filteredCatalog.length === 0 ? (
                  <div className={styles.empty}>No packages match the current filter.</div>
                ) : (
                  <div className={styles.cardList}>
                    {filteredCatalog.map((pkg) => {
                      // "Installed" in the drawer means "in this project's
                      // lockfile" — the user-store presence is irrelevant
                      // for the per-project surface.
                      const isInstalled = projectInstalledDirs.has(pkg.dirName);
                      const catalogRow = catalogByDir.get(pkg.dirName);
                      const userStoreRow = isInstalled
                        ? installed.find((r) => r.dirName === pkg.dirName)
                        : undefined;
                      const hasUpdate =
                        isInstalled
                        && userStoreRow != null
                        && catalogRow != null
                        && catalogRow.version !== userStoreRow.version;
                      return (
                        <PackageCard
                          key={pkg.dirName}
                          pkg={pkg}
                          isInstalled={isInstalled}
                          hasUpdate={hasUpdate}
                          catalogRow={catalogRow}
                          busy={busy}
                          cardActionDir={cardActionDir}
                          catalogPublishAllowed={catalogPublishAllowed}
                          onInstall={(p) => void onInstall(p)}
                          onUninstall={projectId ? (p) => void onUninstall(p) : undefined}
                          onUnpublish={(p) => void onUnpublishFromCatalog(p)}
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
    </>
  );
};
