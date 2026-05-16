import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faDownload, faEye, faEyeSlash, faPenToSquare, faTrashCan } from "@fortawesome/free-solid-svg-icons";
import { Link } from "react-router-dom";
import {
    PackPayload,
    ResolveConflict,
    packsApi,
    refreshPackRegistry,
} from "../../api/packsApi";
import { CatalogPublishPill } from "../../components/packs/CatalogPublishPill";
import { toApiPayload } from "./factoryDraftModel";
import { useNodeFactoryModal } from "../../providers/NodeFactoryModalProvider";
import { draftForkFromInstalledPackPayload, draftFromInstalledPackPayload } from "../../utils/palettePackFactoryDraft";
import {
    FORK_SELECTION_SESSION_PREFIX,
    areForkPaletteParentsRevealedInDock,
    formatForkOfSubtitle,
    partitionPacksByForkFamily,
    referencedForkParentCoordinates,
    resolveForkFamilySelectionKey,
    type ForkFamilyGroup,
} from "../../utils/forkPackLineage";
import styles from "./NodesHub.module.css";

/**
 * Nodes hub — warehouse browse, my packs, and install flow (see
 * ``docs/nodesfactory@docs/frontend.md`` — Nodes Hub).
 *
 * **Catalog** is fixture-backed (``GET /api/packs/catalog``) and returns
 * pack rows plus ``families`` / ``catalogCollisions``. Install from a
 * catalog card calls ``POST /api/packs/catalog/install`` (same validation as
 * sideload, copying committed fixtures server-side). A separate remote
 * pack-registry service is not implemented yet.
 *
 * "My packs" mirrors the warehouse browse layout and lets users
 * uninstall or re-export installed packs.
 */

type Tab = "all" | "data" | "computation" | "vis" | "installed";

const CATEGORY_LABELS: Record<Tab, string> = {
  all: "All packs",
  data: "Data",
  computation: "Computation",
  vis: "Visualisation",
  installed: "Installed",
};

const VIS_CATEGORIES = new Set(["vis_grammar", "vis_simple"]);

const MyPackIconActions = React.memo(function MyPackIconActions({
    pack,
    busy,
    paletteDockBusy,
    onExport,
    onUninstall,
    onPaletteDockToggle,
}: {
    pack: PackPayload;
    busy: boolean;
    /** When this matches ``pack.dirName``, only the dock eye disables (per-row toggle). */
    paletteDockBusy: string | null;
    onExport: (pack: PackPayload) => void | Promise<void>;
    onUninstall: (pack: PackPayload) => void | Promise<void>;
    onPaletteDockToggle: (pack: PackPayload) => void | Promise<void>;
}) {
    const hiddenInDock = pack.paletteDock?.hiddenFromForkPaletteDock === true;
    const dockAwait = paletteDockBusy === pack.dirName;
    return (
        <div className={styles.myPackRowAside}>
            <button
                type="button"
                className={styles.myPackIconBtn}
                onClick={() => void onPaletteDockToggle(pack)}
                title={
                    hiddenInDock
                        ? "Show this pack in the Nodes palette dock"
                        : "Hide this pack from the Nodes palette dock"
                }
                aria-label={
                    hiddenInDock
                        ? `Show ${pack.name} in Nodes palette dock`
                        : `Hide ${pack.name} from Nodes palette dock`
                }
                aria-pressed={!hiddenInDock}
                disabled={busy || dockAwait}
            >
                <FontAwesomeIcon icon={hiddenInDock ? faEye : faEyeSlash} aria-hidden />
            </button>
            <button
                type="button"
                className={styles.myPackIconBtn}
                onClick={() => void onExport(pack)}
                title="Export pack archive"
                aria-label={`Export ${pack.name}`}
                disabled={busy}
            >
                <FontAwesomeIcon icon={faDownload} />
            </button>
            <button
                type="button"
                className={styles.myPackIconBtn}
                onClick={() => void onUninstall(pack)}
                title="Remove pack"
                aria-label={`Remove ${pack.name}`}
                disabled={busy}
            >
                <FontAwesomeIcon icon={faTrashCan} />
            </button>
        </div>
    );
});

const HubInstalledForkRailGroup = React.memo(function HubInstalledForkRailGroup({
    family,
    manualForkDirByRoot,
    setManualForkDirByRoot,
    busy,
    paletteDockBusy,
    onExport,
    onUninstall,
    onPaletteDockToggle,
    catalogPublishedDirs,
    catalogPublishAllowed,
    publishingPackKey,
    onPublishToCatalog,
    onOpenForkInFactory,
}: {
    family: ForkFamilyGroup<PackPayload>;
    manualForkDirByRoot: Record<string, string>;
    setManualForkDirByRoot: React.Dispatch<React.SetStateAction<Record<string, string>>>;
    busy: boolean;
    paletteDockBusy: string | null;
    onExport: (pack: PackPayload) => void | Promise<void>;
    onUninstall: (pack: PackPayload) => void | Promise<void>;
    onPaletteDockToggle: (pack: PackPayload) => void | Promise<void>;
    catalogPublishedDirs: ReadonlySet<string>;
    catalogPublishAllowed: boolean;
    publishingPackKey: string | null;
    onPublishToCatalog: (dirName: string) => void;
    onOpenForkInFactory: (pack: PackPayload) => void;
}) {
    const manualPick = manualForkDirByRoot[family.rootKey];
    const resolverMembers = useMemo(
        () => family.members.map((m) => ({ key: m.dirName })),
        [family.members],
    );

    const resolvedDir = useMemo(
        () => resolveForkFamilySelectionKey(family.rootKey, resolverMembers, "", manualPick),
        [family.rootKey, resolverMembers, manualPick],
    );

    useEffect(() => {
        try {
            sessionStorage.setItem(FORK_SELECTION_SESSION_PREFIX + family.rootKey, resolvedDir);
        } catch {
            /* noop */
        }
    }, [family.rootKey, resolvedDir]);

    const selectedPack = useMemo(
        () => family.members.find((p) => p.dirName === resolvedDir) ?? family.members[0]!,
        [family.members, resolvedDir],
    );

    const onForkSelectChange = useCallback(
        (e: React.ChangeEvent<HTMLSelectElement>) => {
            const next = e.target.value;
            setManualForkDirByRoot((prev) => ({ ...prev, [family.rootKey]: next }));
            try {
                sessionStorage.setItem(FORK_SELECTION_SESSION_PREFIX + family.rootKey, next);
            } catch {
                /* noop */
            }
        },
        [family.rootKey, setManualForkDirByRoot],
    );

    return (
        <section className={styles.hubForkFamily} aria-labelledby={`fork-rail-head-${family.rootKey}`}>
            <div className={styles.hubForkFamilyToolbar}>
                <div>
                    <div id={`fork-rail-head-${family.rootKey}`} className={styles.hubForkRailTitleRow}>
                        <button
                            type="button"
                            className={styles.hubPackFactoryTitleBtn}
                            title="Fork in Node Factory (new install; source unchanged)"
                            onClick={() => onOpenForkInFactory(selectedPack)}
                        >
                            {selectedPack.name}
                        </button>
                        <button
                            type="button"
                            className={styles.myPackIconBtn}
                            title="Fork in Node Factory"
                            aria-label={`Fork ${selectedPack.name} in Node Factory`}
                            disabled={busy}
                            onClick={() => onOpenForkInFactory(selectedPack)}
                        >
                            <FontAwesomeIcon icon={faPenToSquare} />
                        </button>
                    </div>
                    <p className={styles.hubForkFamilyRailMeta}>
                        Family root {family.rootKey} · {family.members.length} forks
                    </p>
                </div>
            </div>
            <label className={styles.hubForkFamilySelectLabel}>
                Fork
                <select
                    className={styles.hubForkFamilySelect}
                    value={resolvedDir}
                    aria-label={`Select fork for family ${family.rootKey}`}
                    onChange={onForkSelectChange}
                >
                    {family.members.map((m) => (
                        <option key={m.dirName} value={m.dirName}>
                            {m.name} ({m.packId} · v{m.version})
                        </option>
                    ))}
                </select>
            </label>
            <div role="list">
                {family.members.map((pack) => (
                    <div
                        key={pack.dirName}
                        role="listitem"
                        className={`${styles.myPackRow} ${
                            pack.dirName === resolvedDir ? styles.myPackRowHighlight : ""
                        }`}
                    >
                        <div>
                            <div className={styles.myPackTitleBlock}>
                                <div className={styles.myPackNameRow}>
                                    <button
                                        type="button"
                                        className={styles.myPackFactoryNameBtn}
                                        title="Fork in Node Factory (new install; source unchanged)"
                                        onClick={() => onOpenForkInFactory(pack)}
                                    >
                                        {pack.name}
                                    </button>
                                    <button
                                        type="button"
                                        className={styles.myPackIconBtn}
                                        title="Fork in Node Factory"
                                        aria-label={`Fork ${pack.name} in Node Factory`}
                                        disabled={busy}
                                        onClick={() => onOpenForkInFactory(pack)}
                                    >
                                        <FontAwesomeIcon icon={faPenToSquare} />
                                    </button>
                                </div>
                                <CatalogPublishPill
                                    variant="hub"
                                    dirName={pack.dirName}
                                    published={catalogPublishedDirs.has(pack.dirName)}
                                    allowPublish={catalogPublishAllowed}
                                    busy={publishingPackKey === pack.dirName}
                                    onPublish={onPublishToCatalog}
                                />
                            </div>
                            <span className={styles.myPackVersion}>
                                {pack.packId} · v{pack.version}
                            </span>
                            {pack.lineage?.forkedFrom ? (
                                <p className={styles.hubForkOfLine}>{formatForkOfSubtitle(pack.lineage).text}</p>
                            ) : null}
                        </div>
                        <MyPackIconActions
                                pack={pack}
                                busy={busy}
                                paletteDockBusy={paletteDockBusy}
                                onExport={onExport}
                                onUninstall={onUninstall}
                                onPaletteDockToggle={onPaletteDockToggle}
                            />
                    </div>
                ))}
            </div>
        </section>
    );
});

function matchesTab(pack: PackPayload, tab: Tab): boolean {
  if (tab === "all") return true;
  if (tab === "installed") return !!pack.installed;
  if (tab === "vis") return pack.kinds.some((k) => VIS_CATEGORIES.has(k.category));
  return pack.kinds.some((k) => k.category === tab);
}

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
  const fileInputRef = useRef<HTMLInputElement>(null);
  const installedByDirRef = useRef<Map<string, PackPayload>>(new Map());
  const { openNodeFactory } = useNodeFactoryModal();

  const installedDirs = useMemo(
    () => new Set(installed.map((p) => p.dirName)),
    [installed],
  );

  const catalogPublishedDirs = useMemo(
    () => new Set(catalog.map((p) => p.dirName)),
    [catalog],
  );

  const [hubForkManualByRoot, setHubForkManualByRoot] = useState<Record<string, string>>({});

  const reload = useCallback(async () => {
    try {
      const [cat, mine, cap] = await Promise.all([
        packsApi.catalog(),
        packsApi.listInstalled(),
        packsApi.factoryCapabilities(),
      ]);
      // Merge the live "installed" flag in case catalog and installed
      // listings drift (e.g., a sideloaded pack that's not in the
      // catalog fixture set).
      const installedSet = new Set(mine.packs.map((p) => p.dirName));
      setCatalog(
        cat.packs.map((p) => ({ ...p, installed: installedSet.has(p.dirName) })),
      );
      setInstalled(mine.packs);
      installedByDirRef.current = new Map(mine.packs.map((p) => [p.dirName, p]));
      setCatalogPublishAllowed(cap.catalogPublish);
    } catch (err) {
      console.error("Failed to load packs:", err);
      setToast({ kind: "err", msg: `Failed to load packs: ${(err as Error).message}` });
    }
  }, []);

  const installedPartition = useMemo(() => partitionPacksByForkFamily(installed), [installed]);

  const installedForkParentCoords = useMemo(
    () => referencedForkParentCoordinates(installed),
    [installed],
  );

  const forkParentsRevealedInDockPalette = useMemo(
    () => areForkPaletteParentsRevealedInDock(installed),
    [installed],
  );

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
  }, [
    installedForkParentCoords.size,
    forkParentsRevealedInDockPalette,
    reload,
  ]);

  const railSingletonsSorted = useMemo(
    () =>
      [...installedPartition.singletons].sort((a, b) =>
        a.name.localeCompare(b.name, undefined, { sensitivity: "base" }),
      ),
    [installedPartition.singletons],
  );

  const onOpenForkInFactory = useCallback(
    (pack: PackPayload) => {
      openNodeFactory({
        draft: draftForkFromInstalledPackPayload(pack),
        forkInstallNotice: true,
        onInstallSuccess: () => {
          void reload();
        },
      });
    },
    [openNodeFactory, reload],
  );

  useEffect(() => {
    void reload();
  }, [reload]);

  useEffect(() => {
    if (!toast) return;
    const id = window.setTimeout(() => setToast(null), 4000);
    return () => window.clearTimeout(id);
  }, [toast]);

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
        // The backend returns 404 when the pack has already been
        // removed (race with another tab, a previous Werkzeug reload
        // mid-request, etc.). The user's intent — "this pack should be
        // gone" — is already satisfied, so swallow the 404 and let the
        // reload below confirm the state. Any other error is real.
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

  const onTogglePackPaletteDock = useCallback(
    async (pack: PackPayload) => {
      const hiddenNow = pack.paletteDock?.hiddenFromForkPaletteDock === true;
      const visibleInDock = !hiddenNow;
      setPaletteDockDirBusy(pack.dirName);
      try {
        await packsApi.packPaletteDockVisible(pack.dirName, visibleInDock);
        await refreshPackRegistry();
        await reload();
        setToast({
          kind: "ok",
          msg: visibleInDock
            ? `"${pack.name}" is shown in the Nodes palette dock.`
            : `"${pack.name}" is hidden from the Nodes palette dock.`,
        });
      } catch (err) {
        setToast({ kind: "err", msg: (err as Error).message });
      } finally {
        setPaletteDockDirBusy(null);
      }
    },
    [reload],
  );

  const onPublishToCatalog = useCallback(
    async (dirName: string) => {
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
        setToast({
          kind: "ok",
          msg: `Published ${dirName} to dev catalog fixtures.`,
        });
      } catch (err) {
        setToast({ kind: "err", msg: (err as Error).message });
      } finally {
        setPublishingPackKey(null);
      }
    },
    [reload],
  );

  /**
   * Run ``POST /api/packs/resolve`` with the candidate so the install
   * dialog can show Python/JS dependency conflicts before install.
   * Actual install uses ``packsApi.installFromCatalog(dirName)``.
   */
  const onInstallFromCatalog = useCallback(async (pack: PackPayload) => {
    // Resolve permissions/deps first so the user sees the install
    // dialog with the same conflict surface the warehouse-api-ui
    // mockup shows.
    setInstallCandidate(pack);
    try {
      // Resolve against the user's currently-installed packs +
      // the candidate. We don't actually persist the lockfile here —
      // that happens when the user clicks "Install".
      const probe = await packsApi.resolve([
        ...installed.map((p) => p.dirName),
        pack.dirName,
      ]);
      setConflictReport(probe.conflicts);
    } catch (err) {
      // 409 -> conflicts in the body; we already surface conflicts
      // via the response shape, so a thrown error here means a
      // server-side problem we should report verbatim.
      const status = (err as { status?: number }).status;
      if (status === 409) {
        const body = (err as { body?: { conflicts: ResolveConflict[] } }).body;
        setConflictReport(body?.conflicts ?? []);
      } else {
        setToast({
          kind: "err",
          msg: `Resolve failed: ${(err as Error).message}`,
        });
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
      setToast({
        kind: "ok",
        msg: `Installed ${installCandidate.name} ${installCandidate.version}`,
      });
      setInstallCandidate(null);
      setConflictReport(null);
    } catch (err) {
      setToast({ kind: "err", msg: `Install failed: ${(err as Error).message}` });
    } finally {
      setBusy(false);
    }
  }, [installCandidate, reload]);

  const filtered = catalog.filter((p) => {
    if (!matchesTab(p, tab)) return false;
    if (!search.trim()) return true;
    const q = search.trim().toLowerCase();
    return (
      p.name.toLowerCase().includes(q) ||
      p.publisher.toLowerCase().includes(q) ||
      p.description.toLowerCase().includes(q)
    );
  });

  return (
    <div className={styles.shell}>
      <div className={styles.topBar}>
        <Link to="/projects" className={styles.backLink}>
          ← Projects
        </Link>
        <h1 className={styles.title}>Nodes warehouse</h1>
        <input
          ref={fileInputRef}
          type="file"
          accept=".curio-nodepack,application/zip"
          style={{ display: "none" }}
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) void onPickArchive(file);
            if (fileInputRef.current) fileInputRef.current.value = "";
          }}
        />
        <button
          className={styles.ghostButton}
          onClick={() => fileInputRef.current?.click()}
          disabled={busy}
        >
          Sideload .curio-nodepack
        </button>
        <button
          className={styles.actionButton}
          type="button"
          onClick={() => openNodeFactory({ blank: true })}
        >
          Create new pack
        </button>
      </div>

      <div className={styles.body}>
        <aside className={styles.rail} aria-label="Category filter">
          <h2 className={styles.railTitle}>Browse</h2>
          {(Object.keys(CATEGORY_LABELS) as Tab[]).map((t) => (
            <button
              key={t}
              className={
                t === tab ? styles.railItemActive : styles.railItem
              }
              onClick={() => setTab(t)}
            >
              {CATEGORY_LABELS[t]}
            </button>
          ))}
        </aside>

        <main className={styles.main}>
          <div className={styles.searchRow}>
            <input
              className={styles.search}
              placeholder="Search packs by name, publisher, or description"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>
          <div className={styles.catalogScroll}>
            {filtered.length === 0 ? (
              <div className={styles.empty}>
                No packs match the current filter.
              </div>
            ) : (
              <div className={styles.grid}>
                {filtered.map((pack) => (
                  <article key={pack.dirName} className={styles.card}>
                  <div className={styles.cardHeader}>
                    <div>
                      <h3 className={styles.packName}>{pack.name}</h3>
                      <span className={styles.publisher}>
                        {pack.publisher || pack.packId}
                      </span>
                    </div>
                    <div className={styles.cardHeaderAside}>
                      {installedDirs.has(pack.dirName) ? (
                        <span className={styles.installedTag}>Installed</span>
                      ) : (
                        <span className={styles.tag}>v{pack.version}</span>
                      )}
                      {(pack.channel ?? "stable") !== "stable" ? (
                        <span
                          className={styles.channelChip}
                          title={`Release channel: ${pack.channel}`}
                        >
                          {pack.channel}
                        </span>
                      ) : null}
                    </div>
                  </div>
                  <p className={styles.description}>
                    {pack.description || "No description."}
                  </p>
                  {pack.lineage ? (
                    <p className={styles.catalogForkLine} title={formatForkOfSubtitle(pack.lineage).title}>
                      {formatForkOfSubtitle(pack.lineage).text}
                    </p>
                  ) : null}
                  <div className={styles.kinds}>
                    {pack.kinds.slice(0, 4).map((k) => (
                      <span key={k.kindId} className={styles.kindChip}>
                        {k.label}
                      </span>
                    ))}
                  </div>
                  <div className={styles.versionRow}>
                    <span className={styles.publisher}>
                      {pack.kinds.length} node{pack.kinds.length === 1 ? "" : "s"}
                    </span>
                    {installedDirs.has(pack.dirName) ? (
                      <button
                        className={styles.ghostButton}
                        onClick={() => onUninstall(pack)}
                        disabled={busy}
                      >
                        Uninstall
                      </button>
                    ) : (
                      <button
                        className={styles.actionButton}
                        onClick={() => onInstallFromCatalog(pack)}
                        disabled={busy}
                      >
                        Install
                      </button>
                    )}
                  </div>
                </article>
              ))}
              </div>
            )}
          </div>
        </main>

        <aside className={styles.myPacks} aria-label="Your installed packs">
          <div className={styles.myPacksHeaderRow}>
            <h2 id="hub-my-packs-heading" className={styles.myPacksTitle}>
              My packs
            </h2>
            {installed.length > 0 && installedForkParentCoords.size > 0 ? (
              <button
                type="button"
                className={styles.myPacksDockToggleBtn}
                onClick={() => void onToggleForkSourcesInDockPalette()}
                disabled={busy || forkParentsPaletteBusy || paletteDockDirBusy != null}
                title={
                  forkParentsRevealedInDockPalette
                    ? "Hide fork source packs from the Nodes palette dock"
                    : "Show fork source packs in the Nodes palette dock"
                }
                aria-label={
                  forkParentsRevealedInDockPalette
                    ? "Hide fork source packs from Nodes palette dock"
                    : "Show fork source packs in Nodes palette dock"
                }
                aria-pressed={forkParentsRevealedInDockPalette}
              >
                <FontAwesomeIcon
                  icon={forkParentsRevealedInDockPalette ? faEyeSlash : faEye}
                  aria-hidden
                />
              </button>
            ) : null}
          </div>
          {installed.length === 0 ? (
            <div className={styles.empty}>You haven't installed any packs yet.</div>
          ) : (
            <>
              {railSingletonsSorted.map((pack) => (
                <div key={pack.dirName} className={styles.myPackRow}>
                  <div>
                    <div className={styles.myPackTitleBlock}>
                      <div className={styles.myPackNameRow}>
                        <button
                          type="button"
                          className={styles.myPackFactoryNameBtn}
                          title="Fork in Node Factory (new install; source unchanged)"
                          onClick={() => onOpenForkInFactory(pack)}
                        >
                          {pack.name}
                        </button>
                        <button
                          type="button"
                          className={styles.myPackIconBtn}
                          title="Fork in Node Factory"
                          aria-label={`Fork ${pack.name} in Node Factory`}
                          disabled={busy}
                          onClick={() => onOpenForkInFactory(pack)}
                        >
                          <FontAwesomeIcon icon={faPenToSquare} />
                        </button>
                      </div>
                      <CatalogPublishPill
                        variant="hub"
                        dirName={pack.dirName}
                        published={catalogPublishedDirs.has(pack.dirName)}
                        allowPublish={catalogPublishAllowed}
                        busy={publishingPackKey === pack.dirName}
                        onPublish={onPublishToCatalog}
                      />
                    </div>
                    <span className={styles.myPackVersion}>
                      {pack.packId} · v{pack.version}
                    </span>
                    {pack.lineage ? (
                      <p className={styles.hubForkOfLine}>{formatForkOfSubtitle(pack.lineage).text}</p>
                    ) : null}
                  </div>
                  <MyPackIconActions
                      pack={pack}
                      busy={busy}
                      paletteDockBusy={paletteDockDirBusy}
                      onExport={onExport}
                      onUninstall={onUninstall}
                      onPaletteDockToggle={onTogglePackPaletteDock}
                  />
                </div>
              ))}
              {installedPartition.families.map((family) => (
                <HubInstalledForkRailGroup
                  key={family.rootKey}
                  family={family}
                  manualForkDirByRoot={hubForkManualByRoot}
                  setManualForkDirByRoot={setHubForkManualByRoot}
                  busy={busy}
                  paletteDockBusy={paletteDockDirBusy}
                  onExport={onExport}
                  onUninstall={onUninstall}
                  onPaletteDockToggle={onTogglePackPaletteDock}
                  catalogPublishedDirs={catalogPublishedDirs}
                  catalogPublishAllowed={catalogPublishAllowed}
                  publishingPackKey={publishingPackKey}
                  onPublishToCatalog={onPublishToCatalog}
                  onOpenForkInFactory={onOpenForkInFactory}
                />
              ))}
            </>
          )}
        </aside>
      </div>

      {installCandidate && (
        <InstallDialog
          pack={installCandidate}
          conflicts={conflictReport ?? []}
          busy={busy}
          onCancel={() => {
            setInstallCandidate(null);
            setConflictReport(null);
          }}
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

/* -------------------------------------------------------------------- */
/* Install permissions modal (figma_mockups/02_install_permissions.svg)  */
/* -------------------------------------------------------------------- */

interface InstallDialogProps {
  pack: PackPayload;
  conflicts: ResolveConflict[];
  busy: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}

const InstallDialog: React.FC<InstallDialogProps> = ({
  pack, conflicts, busy, onCancel, onConfirm,
}) => {
  const hasConflicts = conflicts.length > 0;
  const pythonDeps = Object.entries(pack.dependencies.python);
  const jsDeps = Object.entries(pack.dependencies.js);
  return (
    <div className={styles.modalBackdrop} role="dialog" aria-modal="true">
      <div className={styles.modal}>
        <h2 className={styles.modalTitle}>Install "{pack.name}"</h2>
        <p className={styles.modalSubtitle}>
          {pack.publisher} · v{pack.version}
        </p>

        {pack.permissions.length > 0 && (
          <>
            <p className={styles.depsTitle}>Permissions requested</p>
            <ul className={styles.permList}>
              {pack.permissions.map((perm) => (
                <li key={perm} className={styles.permItem}>
                  <span className={styles.permIcon}>●</span>
                  {perm}
                </li>
              ))}
            </ul>
          </>
        )}

        {(pythonDeps.length > 0 || jsDeps.length > 0) && (
          <div className={styles.depsBox}>
            <p className={styles.depsTitle}>Dependencies</p>
            {pythonDeps.map(([pkg, range]) => (
              <div key={`py:${pkg}`} className={styles.depRow}>
                <code>python · {pkg}</code>
                <code>{range}</code>
              </div>
            ))}
            {jsDeps.map(([pkg, range]) => (
              <div key={`js:${pkg}`} className={styles.depRow}>
                <code>js · {pkg}</code>
                <code>{range}</code>
              </div>
            ))}
          </div>
        )}

        {hasConflicts && (
          <div className={styles.conflictsBox}>
            <p className={styles.conflictTitle}>
              Dependency conflicts with installed packs
            </p>
            {conflicts.map((c) => (
              <div key={c.package}>
                <p>
                  <strong>{c.package}</strong>
                </p>
                <ul style={{ margin: "4px 0", paddingLeft: 18 }}>
                  {c.ranges.map((r) => (
                    <li key={r.packDir}>
                      <code>{r.packDir}</code>: <code>{r.range}</code>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
            <p style={{ fontSize: "0.8125rem", marginTop: 8 }}>
              Uninstall one of the conflicting packs before installing this one.
            </p>
          </div>
        )}

        <div className={styles.modalFooter}>
          <button className={styles.ghostButton} onClick={onCancel} disabled={busy}>
            Cancel
          </button>
          <button
            className={styles.actionButton}
            onClick={onConfirm}
            disabled={busy || hasConflicts}
          >
            {busy ? "Installing…" : "Install"}
          </button>
        </div>
      </div>
    </div>
  );
};

export default NodesHub;
