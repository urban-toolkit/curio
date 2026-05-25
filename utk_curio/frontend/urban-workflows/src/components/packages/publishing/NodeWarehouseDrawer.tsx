import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  PackagePayload,
  ResolveConflict,
  packagesApi,
  refreshPackageRegistry,
} from "../../../api/packagesApi";
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
import styles from "./NodeWarehouseDrawer.module.css";


export interface NodeWarehouseDrawerProps {
  /** When true, scrim fades in and the panel slides in from the right. */
  presented: boolean;
  onRequestClose: () => void;
  /** Called once the exit transition finishes (or immediately when motion is reduced). */
  onExitComplete: () => void;
}

export const NodeWarehouseDrawer: React.FC<NodeWarehouseDrawerProps> = ({
  presented,
  onRequestClose,
  onExitComplete,
}) => {
  const drawerRef = useRef<HTMLElement>(null);

  const [catalog, setCatalog] = useState<PackagePayload[]>([]);
  const [installed, setInstalled] = useState<PackagePayload[]>([]);
  const [tab, setTab] = useState<DrawerTab>("featured");
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
    console.warn(`[NodeWarehouseDrawer] ${label}:`, err);
  }, []);

  const installedDirs = useMemo(() => new Set(installed.map((p) => p.dirName)), [installed]);
  const catalogByDir = useMemo(() => new Map(catalog.map((p) => [p.dirName, p])), [catalog]);
  const catalogPublishedDirs = useMemo(() => new Set(catalog.map((p) => p.dirName)), [catalog]);

  const reload = useCallback(async () => {
    const [cat, mine, cap] = await Promise.all([
      packagesApi.catalog(),
      packagesApi.listInstalled(),
      packagesApi.factoryCapabilities(),
    ]);
    const installedSet = new Set(mine.packages.map((p) => p.dirName));
    setCatalog(cat.packages.map((p) => ({ ...p, installed: installedSet.has(p.dirName) })));
    setInstalled(mine.packages);
    installedByDirRef.current = new Map(mine.packages.map((p) => [p.dirName, p]));
    setCatalogPublishAllowed(cap.catalogPublish);
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

  const updateCandidates = useMemo(() => {
    return installed.filter((row) => {
      const catRow = catalogByDir.get(row.dirName);
      return catRow != null && catRow.version !== row.version;
    });
  }, [installed, catalogByDir]);

  const filteredCatalog = useMemo(() => {
    const base = sortPackages(
      catalog.filter((p) => matchesSearch(p, search)),
      sort,
    );
    if (tab === "installed") {
      return base.filter((p) => installedDirs.has(p.dirName));
    }
    if (tab === "updates") {
      const updateDirs = new Set(updateCandidates.map((p) => p.dirName));
      return base.filter((p) => updateDirs.has(p.dirName));
    }
    return base;
  }, [catalog, search, sort, tab, installedDirs, updateCandidates]);

  const filteredInstalled = useMemo(
    () => installed.filter((p) => matchesSearch(p, search)),
    [installed, search],
  );

  const featuredPacks = useMemo(
    () => sortPackages(catalog, "new").slice(0, 3),
    [catalog],
  );

  const displayPacks = tab === "featured" ? featuredPacks : filteredCatalog;

  const onInstallFromCatalog = useCallback(
    async (pkg: PackagePayload) => {
      setInstallCandidate(pkg);
      try {
        const probe = await packagesApi.resolve([...installed.map((p) => p.dirName), pkg.dirName]);
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
    [installed],
  );

  const confirmCatalogInstall = useCallback(async () => {
    if (!installCandidate) return;
    setBusy(true);
    setActionError(null);
    try {
      await packagesApi.installFromCatalog(installCandidate.dirName);
      await refreshPackageRegistry();
      await reload();
      setInstallCandidate(null);
      setConflictReport(null);
    } catch (err) {
      reportActionError(`Couldn't install ${installCandidate.name}`, err);
    } finally {
      setBusy(false);
    }
  }, [installCandidate, reload, reportActionError]);

  const onPickArchive = useCallback(
    async (file: File) => {
      setBusy(true);
      setActionError(null);
      try {
        await packagesApi.uploadArchive(file, file.name);
        await refreshPackageRegistry();
        await reload();
      } catch (err) {
        reportActionError(`Couldn't import ${file.name}`, err);
      } finally {
        setBusy(false);
      }
    },
    [reload, reportActionError],
  );

  const onUninstall = useCallback(async (pkg: PackagePayload) => {
    if (!window.confirm(`Uninstall ${pkg.name} (${pkg.dirName}) from this dataflow?`)) return;
    setCardActionDir(pkg.dirName);
    setActionError(null);
    try {
      try {
        await packagesApi.uninstall(pkg.dirName);
      } catch (err) {
        const status = (err as { status?: number }).status;
        if (status !== 404) throw err;
      }
      await refreshPackageRegistry();
      await reload();
    } catch (err) {
      reportActionError(`Couldn't uninstall ${pkg.name}`, err);
    } finally {
      setCardActionDir(null);
    }
  }, [reload, reportActionError]);

  const onUnpublishFromCatalog = useCallback(
    async (pkg: PackagePayload) => {
      if (
        !window.confirm(
          `Unpublish ${pkg.name} (${pkg.dirName}) from the dev catalog?\n\nThis removes the entry under packages/. Installed copies in dataflows are not removed.`,
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

  const onExport = useCallback(async (pkg: PackagePayload) => {
    try {
      await packagesApi.download(pkg.dirName);
    } catch (err) {
      reportActionError(`Couldn't export ${pkg.name}`, err);
    }
  }, [reportActionError]);

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
    installed: tab === "installed" ? filteredInstalled : installed,
    catalogByDir,
    catalogPublishedDirs,
    catalogPublishAllowed,
    publishingPackageKey,
    busy,
    onUninstall: (p: PackagePayload) => void onUninstall(p),
    onExport: (p: PackagePayload) => void onExport(p),
    onPublishToCatalog: (d: string) => void onPublishToCatalog(d),
  };

  const tabLabel: Record<DrawerTab, string> = {
    featured: "Featured",
    browse: "Browse all",
    installed: "Installed",
    updates: "Updates",
  };

  return (
    <>
      <div
        className={`${styles.overlayRoot} ${presented ? styles.overlayRootPresented : ""}`}
        data-curio-node-warehouse-drawer="true"
      >
        <button
          type="button"
          className={styles.scrim}
          aria-label="Close node warehouse drawer"
          onClick={() => {
            if (!pinned) onRequestClose();
          }}
        />
        <aside
          ref={drawerRef}
          className={styles.drawer}
          role="dialog"
          aria-modal="true"
          aria-labelledby="node-warehouse-drawer-title"
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
            tab={tab}
            installedCount={installed.length}
            updateCount={updateCandidates.length}
            onChange={setTab}
          />

          <div className={styles.scrollBody}>
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
                <div className={styles.empty}>No packages match the current filter.</div>
              ) : (
                <MyPackagesList {...myPackagesListProps} />
              )
            ) : (
              <>
                <p className={styles.sectionLabel}>{tabLabel[tab]}</p>

                {displayPacks.length === 0 ? (
                  <div className={styles.empty}>No packages match the current filter.</div>
                ) : (
                  <div className={styles.cardList}>
                    {displayPacks.map((pkg) => {
                      const isInstalled = installedDirs.has(pkg.dirName);
                      const catalogRow = catalogByDir.get(pkg.dirName);
                      const hasUpdate =
                        isInstalled && catalogRow != null && catalogRow.version !== pkg.version;
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
                          onInstall={(p) => void onInstallFromCatalog(p)}
                          onUninstall={(p) => void onUninstall(p)}
                          onUnpublish={(p) => void onUnpublishFromCatalog(p)}
                        />
                      );
                    })}
                  </div>
                )}

                {tab === "featured" ? <MyPackagesList {...myPackagesListProps} /> : null}
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
