import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  PackPayload,
  ResolveConflict,
  packsApi,
  refreshPackRegistry,
} from "../../../api/packsApi";
import { draftFromInstalledPackPayload } from "../../../utils/palettePackFactoryDraft";
import { toApiPayload } from "../../../pages/nodes/factoryDraftModel";
import { InstallPermissionsDialog } from "./InstallPermissionsDialog";
import { DrawerHeader } from "./DrawerHeader";
import { DrawerTabs } from "./DrawerTabs";
import { PackSearchRow } from "./PackSearchRow";
import { PackCard } from "./PackCard";
import { MyPacksList } from "./MyPacksList";
import { EnvNote } from "./EnvNote";
import { DrawerFooter } from "./DrawerFooter";
import { DrawerTab, SortMode } from "./packTypes";
import { sortPacks, matchesSearch } from "./packUtils";
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
  const navigate = useNavigate();
  const drawerRef = useRef<HTMLElement>(null);

  const [catalog, setCatalog] = useState<PackPayload[]>([]);
  const [installed, setInstalled] = useState<PackPayload[]>([]);
  const [tab, setTab] = useState<DrawerTab>("featured");
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState<SortMode>("new");
  const [pinned, setPinned] = useState(false);
  const [busy, setBusy] = useState(false);
  const [paletteDockDirBusy, setPaletteDockDirBusy] = useState<string | null>(null);
  const [catalogPublishAllowed, setCatalogPublishAllowed] = useState(false);
  const [publishingPackKey, setPublishingPackKey] = useState<string | null>(null);
  const [cardActionDir, setCardActionDir] = useState<string | null>(null);
  const [installCandidate, setInstallCandidate] = useState<PackPayload | null>(null);
  const [conflictReport, setConflictReport] = useState<ResolveConflict[] | null>(null);
  const installedByDirRef = useRef<Map<string, PackPayload>>(new Map());

  const installedDirs = useMemo(() => new Set(installed.map((p) => p.dirName)), [installed]);
  const catalogByDir = useMemo(() => new Map(catalog.map((p) => [p.dirName, p])), [catalog]);
  const catalogPublishedDirs = useMemo(() => new Set(catalog.map((p) => p.dirName)), [catalog]);

  const reload = useCallback(async () => {
    const [cat, mine, cap] = await Promise.all([
      packsApi.catalog(),
      packsApi.listInstalled(),
      packsApi.factoryCapabilities(),
    ]);
    const installedSet = new Set(mine.packs.map((p) => p.dirName));
    setCatalog(cat.packs.map((p) => ({ ...p, installed: installedSet.has(p.dirName) })));
    setInstalled(mine.packs);
    installedByDirRef.current = new Map(mine.packs.map((p) => [p.dirName, p]));
    setCatalogPublishAllowed(cap.catalogPublish);
  }, []);

  useEffect(() => {
    void reload().catch(() => {
      /* drawer stays usable with empty lists */
    });
  }, [reload]);

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
    const base = sortPacks(
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
    () => sortPacks(catalog, "new").slice(0, 3),
    [catalog],
  );

  const displayPacks = tab === "featured" ? featuredPacks : filteredCatalog;

  const onInstallFromCatalog = useCallback(
    async (pack: PackPayload) => {
      setInstallCandidate(pack);
      try {
        const probe = await packsApi.resolve([...installed.map((p) => p.dirName), pack.dirName]);
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
    try {
      await packsApi.installFromCatalog(installCandidate.dirName);
      await refreshPackRegistry();
      await reload();
      setInstallCandidate(null);
      setConflictReport(null);
    } finally {
      setBusy(false);
    }
  }, [installCandidate, reload]);

  const onPickArchive = useCallback(
    async (file: File) => {
      setBusy(true);
      try {
        await packsApi.uploadArchive(file, file.name);
        await refreshPackRegistry();
        await reload();
      } finally {
        setBusy(false);
      }
    },
    [reload],
  );

  const onUninstall = useCallback(async (pack: PackPayload) => {
    if (!window.confirm(`Uninstall ${pack.name} (${pack.dirName}) from this workspace?`)) return;
    setCardActionDir(pack.dirName);
    try {
      try {
        await packsApi.uninstall(pack.dirName);
      } catch (err) {
        const status = (err as { status?: number }).status;
        if (status !== 404) throw err;
      }
      await refreshPackRegistry();
      await reload();
    } finally {
      setCardActionDir(null);
    }
  }, [reload]);

  const onUnpublishFromCatalog = useCallback(
    async (pack: PackPayload) => {
      if (
        !window.confirm(
          `Unpublish ${pack.name} (${pack.dirName}) from the dev catalog?\n\nThis removes the fixture under fixtures/packs. Installed copies in workspaces are not removed.`,
        )
      ) {
        return;
      }
      setCardActionDir(pack.dirName);
      try {
        await packsApi.unpublishFromCatalog(pack.dirName);
        await reload();
      } finally {
        setCardActionDir(null);
      }
    },
    [reload],
  );

  const onExport = useCallback(async (pack: PackPayload) => {
    await packsApi.download(pack.dirName);
  }, []);

  const onTogglePaletteDock = useCallback(async (pack: PackPayload) => {
    const nextHidden = !(pack.paletteDock?.hiddenFromForkPaletteDock === true);
    setPaletteDockDirBusy(pack.dirName);
    try {
      await packsApi.packPaletteDockVisible(pack.dirName, !nextHidden);
      await refreshPackRegistry();
      await reload();
    } finally {
      setPaletteDockDirBusy(null);
    }
  }, [reload]);

  const onPublishToCatalog = useCallback(async (dirName: string) => {
    const row = installedByDirRef.current.get(dirName);
    if (!row) return;
    setPublishingPackKey(dirName);
    try {
      const draft = draftFromInstalledPackPayload(row);
      await packsApi.factoryPublishCatalog({
        ...(toApiPayload(draft) as Record<string, unknown>),
        replace: true,
      });
      await reload();
    } finally {
      setPublishingPackKey(null);
    }
  }, [reload]);

  const myPacksListProps = {
    installed: tab === "installed" ? filteredInstalled : installed,
    catalogByDir,
    catalogPublishedDirs,
    catalogPublishAllowed,
    publishingPackKey,
    paletteDockDirBusy,
    busy,
    onUninstall: (p: PackPayload) => void onUninstall(p),
    onExport: (p: PackPayload) => void onExport(p),
    onPaletteDockToggle: (p: PackPayload) => void onTogglePaletteDock(p),
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

          <PackSearchRow
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
            {tab === "installed" ? (
              filteredInstalled.length === 0 ? (
                <div className={styles.empty}>No packs match the current filter.</div>
              ) : (
                <MyPacksList {...myPacksListProps} />
              )
            ) : (
              <>
                <p className={styles.sectionLabel}>{tabLabel[tab]}</p>

                {displayPacks.length === 0 ? (
                  <div className={styles.empty}>No packs match the current filter.</div>
                ) : (
                  <div className={styles.cardList}>
                    {displayPacks.map((pack) => {
                      const isInstalled = installedDirs.has(pack.dirName);
                      const catalogRow = catalogByDir.get(pack.dirName);
                      const hasUpdate =
                        isInstalled && catalogRow != null && catalogRow.version !== pack.version;
                      return (
                        <PackCard
                          key={pack.dirName}
                          pack={pack}
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

                {tab === "featured" ? <MyPacksList {...myPacksListProps} /> : null}
              </>
            )}

            <EnvNote />
          </div>

          {/* <DrawerFooter
            busy={busy}
            onSideload={(file) => void onPickArchive(file)}
            onOpenWarehouse={() => {
              onRequestClose();
              navigate("/nodes");
            }}
          /> */}
        </aside>
      </div>

      {installCandidate ? (
        <InstallPermissionsDialog
          pack={installCandidate}
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
