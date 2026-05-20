import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
    PackPayload,
    ResolveConflict,
    packsApi,
    refreshPackRegistry,
} from "../../api/packsApi";
import { InstallPermissionsDialog } from "../../components/packs/publishing";
import { toApiPayload } from "./factoryDraftModel";
import { useNodeFactoryModal } from "../../providers/NodeFactoryModalProvider";
import {
    draftForkFromInstalledPackPayload,
    draftFromInstalledPackPayload,
} from "../../utils/palettePackFactoryDraft";
import {
    areForkPaletteParentsRevealedInDock,
    partitionInstalledPacksForWarehouseList,
    referencedForkParentCoordinates,
} from "../../utils/forkPackLineage";
import { HubTopBar } from "./HubTopBar";
import { CatalogRail } from "./catalog/CatalogRail";
import { CatalogGrid } from "./catalog/CatalogGrid";
import { matchesTab, Tab } from "./catalog/catalogTypes";
import { MyPacksSidebar } from "./my-packs/MyPacksSidebar";
import styles from "./NodesHub.module.css";

/**
 * Nodes hub — warehouse browse, my packs, and install flow.
 *
 * Sub-component directories:
 *   ./catalog/   — CatalogRail, CatalogGrid, CatalogCard, catalogTypes
 *   ./my-packs/  — MyPacksSidebar and its sub-components
 */
const NodesHub: React.FC = () => {
  const [catalog, setCatalog] = useState<PackPayload[]>([]);
  const [installed, setInstalled] = useState<PackPayload[]>([]);
  const [tab, setTab] = useState<Tab>("all");
  const [search, setSearch] = useState("");
  const [toast, setToast] = useState<{ kind: "ok" | "err"; msg: string } | null>(null);
  const [installCandidate, setInstallCandidate] = useState<PackPayload | null>(null);
  const [conflictReport, setConflictReport] = useState<ResolveConflict[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [forkParentsPaletteBusy, setForkParentsPaletteBusy] = useState(false);
  const [paletteDockDirBusy, setPaletteDockDirBusy] = useState<string | null>(null);
  const [catalogPublishAllowed, setCatalogPublishAllowed] = useState(true);
  const [publishingPackKey, setPublishingPackKey] = useState<string | null>(null);
  const installedByDirRef = useRef<Map<string, PackPayload>>(new Map());
  const { openNodeFactory } = useNodeFactoryModal();

  // ── Derived sets ─────────────────────────────────────────────────────────

  const installedDirs = useMemo(
    () => new Set(installed.map((p) => p.dirName)),
    [installed],
  );

  const catalogPublishedDirs = useMemo(
    () => new Set(catalog.map((p) => p.dirName)),
    [catalog],
  );

  // ── Data loading ─────────────────────────────────────────────────────────

  const reload = useCallback(async () => {
    try {
      const [cat, mine, cap] = await Promise.all([
        packsApi.catalog(),
        packsApi.listInstalled(),
        packsApi.factoryCapabilities(),
      ]);
      // Merge the live "installed" flag in case catalog and installed listings
      // drift (e.g. a sideloaded pack not present in the catalog fixture set).
      const installedSet = new Set(mine.packs.map((p) => p.dirName));
      setCatalog(cat.packs.map((p) => ({ ...p, installed: installedSet.has(p.dirName) })));
      setInstalled(mine.packs);
      installedByDirRef.current = new Map(mine.packs.map((p) => [p.dirName, p]));
      setCatalogPublishAllowed(cap.catalogPublish);
    } catch (err) {
      console.error("Failed to load packs:", err);
      setToast({ kind: "err", msg: `Failed to load packs: ${(err as Error).message}` });
    }
  }, []);

  useEffect(() => { void reload(); }, [reload]);

  // Auto-dismiss toast after 4 s
  useEffect(() => {
    if (!toast) return;
    const id = window.setTimeout(() => setToast(null), 4000);
    return () => window.clearTimeout(id);
  }, [toast]);

  // ── My Packs derived state ────────────────────────────────────────────────

  const hubRailInstalledOrdered = useMemo(
    () => partitionInstalledPacksForWarehouseList(installed),
    [installed],
  );

  const installedForkParentCoords = useMemo(
    () => referencedForkParentCoordinates(installed),
    [installed],
  );

  const forkParentsRevealedInDockPalette = useMemo(
    () => areForkPaletteParentsRevealedInDock(installed),
    [installed],
  );

  // ── Actions ───────────────────────────────────────────────────────────────

  const onPickArchive = useCallback(async (file: File) => {
    setBusy(true);
    try {
      await packsApi.uploadArchive(file, file.name);
      await refreshPackRegistry();
      await reload();
      setToast({ kind: "ok", msg: `Installed ${file.name}` });
    } catch (err) {
      setToast({ kind: "err", msg: `Install failed: ${(err as Error).message}` });
    } finally {
      setBusy(false);
    }
  }, [reload]);

  const onUninstall = useCallback(async (pack: PackPayload) => {
    if (!window.confirm(`Uninstall ${pack.name} (${pack.dirName})?`)) return;
    setBusy(true);
    try {
      try {
        await packsApi.uninstall(pack.dirName);
      } catch (err) {
        // Swallow 404 — pack already gone (race condition / HMR reload).
        const status = (err as { status?: number }).status;
        if (status !== 404) throw err;
      }
      await refreshPackRegistry();
      await reload();
      setToast({ kind: "ok", msg: `Uninstalled ${pack.name}` });
    } catch (err) {
      setToast({ kind: "err", msg: `Uninstall failed: ${(err as Error).message}` });
    } finally {
      setBusy(false);
    }
  }, [reload]);

  const onExport = useCallback(async (pack: PackPayload) => {
    try {
      await packsApi.download(pack.dirName);
    } catch (err) {
      setToast({ kind: "err", msg: `Export failed: ${(err as Error).message}` });
    }
  }, []);

  const onTogglePackPaletteDock = useCallback(async (pack: PackPayload) => {
    const hiddenNow = pack.paletteDock?.hiddenFromForkPaletteDock === true;
    const nextHiddenInDock = !hiddenNow;
    setPaletteDockDirBusy(pack.dirName);
    try {
      await packsApi.packPaletteDockVisible(pack.dirName, !nextHiddenInDock);
      await refreshPackRegistry();
      await reload();
      setToast({
        kind: "ok",
        msg: nextHiddenInDock
          ? `"${pack.name}" is hidden from the Nodes palette dock.`
          : `"${pack.name}" is shown in the Nodes palette dock.`,
      });
    } catch (err) {
      setToast({ kind: "err", msg: (err as Error).message });
    } finally {
      setPaletteDockDirBusy(null);
    }
  }, [reload]);

  const onPublishToCatalog = useCallback(async (dirName: string) => {
    const row = installedByDirRef.current.get(dirName);
    if (!row) {
      setToast({ kind: "err", msg: "Pack metadata not available." });
      return;
    }
    setPublishingPackKey(dirName);
    try {
      const draft = draftFromInstalledPackPayload(row);
      await packsApi.factoryPublishCatalog({
        ...(toApiPayload(draft) as Record<string, unknown>),
        replace: true,
      });
      await reload();
      setToast({ kind: "ok", msg: `Published ${dirName} to dev catalog fixtures.` });
    } catch (err) {
      setToast({ kind: "err", msg: (err as Error).message });
    } finally {
      setPublishingPackKey(null);
    }
  }, [reload]);

  const onToggleForkSourcesInDockPalette = useCallback(async () => {
    if (!installedForkParentCoords.size) return;
    const nextVisible = !forkParentsRevealedInDockPalette;
    setForkParentsPaletteBusy(true);
    try {
      await packsApi.forkParentsPaletteDockVisibility(nextVisible);
      await refreshPackRegistry();
      await reload();
      setToast({
        kind: "ok",
        msg: nextVisible
          ? "Fork source packs are shown in the Nodes palette again."
          : "Fork source packs are hidden from the Nodes palette.",
      });
    } catch (err) {
      setToast({ kind: "err", msg: (err as Error).message });
    } finally {
      setForkParentsPaletteBusy(false);
    }
  }, [installedForkParentCoords.size, forkParentsRevealedInDockPalette, reload]);

  /** Opens the install-permissions dialog after resolving dep conflicts. */
  const onInstallFromCatalog = useCallback(async (pack: PackPayload) => {
    setInstallCandidate(pack);
    try {
      const probe = await packsApi.resolve([
        ...installed.map((p) => p.dirName),
        pack.dirName,
      ]);
      setConflictReport(probe.conflicts);
    } catch (err) {
      const status = (err as { status?: number }).status;
      if (status === 409) {
        const body = (err as { body?: { conflicts: ResolveConflict[] } }).body;
        setConflictReport(body?.conflicts ?? []);
      } else {
        setToast({ kind: "err", msg: `Resolve failed: ${(err as Error).message}` });
        setInstallCandidate(null);
      }
    }
  }, [installed]);

  const confirmCatalogInstall = useCallback(async () => {
    if (!installCandidate) return;
    setBusy(true);
    try {
      await packsApi.installFromCatalog(installCandidate.dirName);
      await refreshPackRegistry();
      await reload();
      setToast({ kind: "ok", msg: `Installed ${installCandidate.name} ${installCandidate.version}` });
      setInstallCandidate(null);
      setConflictReport(null);
    } catch (err) {
      setToast({ kind: "err", msg: `Install failed: ${(err as Error).message}` });
    } finally {
      setBusy(false);
    }
  }, [installCandidate, reload]);

  const onOpenForkInFactory = useCallback((pack: PackPayload) => {
    openNodeFactory({
      draft: draftForkFromInstalledPackPayload(pack),
      forkInstallNotice: true,
      onInstallSuccess: () => { void reload(); },
    });
  }, [openNodeFactory, reload]);

  // ── Filtered catalog list ────────────────────────────────────────────────

  const filteredPacks = useMemo(() => {
    const q = search.trim().toLowerCase();
    return catalog.filter((p) => {
      if (!matchesTab(p, tab)) return false;
      if (!q) return true;
      return (
        p.name.toLowerCase().includes(q) ||
        p.publisher.toLowerCase().includes(q) ||
        p.description.toLowerCase().includes(q)
      );
    });
  }, [catalog, tab, search]);

  // ── Render ───────────────────────────────────────────────────────────────

  return (
    <div className={styles.shell}>
      <HubTopBar
        busy={busy}
        onSideload={(file) => void onPickArchive(file)}
        onCreateNew={() => openNodeFactory({ blank: true })}
      />

      <div className={styles.body}>
        <CatalogRail tab={tab} onChange={setTab} />

        <CatalogGrid
          packs={filteredPacks}
          search={search}
          onSearchChange={setSearch}
          installedDirs={installedDirs}
          busy={busy}
          onInstall={(p) => void onInstallFromCatalog(p)}
          onUninstall={onUninstall}
        />

        <MyPacksSidebar
          installed={installed}
          hubRailInstalledOrdered={hubRailInstalledOrdered}
          busy={busy}
          forkParentsPaletteBusy={forkParentsPaletteBusy}
          paletteDockDirBusy={paletteDockDirBusy}
          installedForkParentCoordsSize={installedForkParentCoords.size}
          forkParentsRevealedInDockPalette={forkParentsRevealedInDockPalette}
          catalogPublishedDirs={catalogPublishedDirs}
          catalogPublishAllowed={catalogPublishAllowed}
          publishingPackKey={publishingPackKey}
          onToggleForkSourcesInDockPalette={() => void onToggleForkSourcesInDockPalette()}
          onExport={onExport}
          onUninstall={onUninstall}
          onPaletteDockToggle={onTogglePackPaletteDock}
          onPublishToCatalog={onPublishToCatalog}
          onOpenForkInFactory={onOpenForkInFactory}
        />
      </div>

      {installCandidate && (
        <InstallPermissionsDialog
          pack={installCandidate}
          conflicts={conflictReport ?? []}
          busy={busy}
          onCancel={() => { setInstallCandidate(null); setConflictReport(null); }}
          onConfirm={confirmCatalogInstall}
        />
      )}

      {toast && (
        <div className={toast.kind === "ok" ? styles.toast : styles.toastError}>
          {toast.msg}
        </div>
      )}
    </div>
  );
};

export default NodesHub;
