import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faMagnifyingGlass, faThumbtack, faXmark } from "@fortawesome/free-solid-svg-icons";
import { useNavigate } from "react-router-dom";
import {
  PackPayload,
  ResolveConflict,
  packsApi,
  refreshPackRegistry,
} from "../../api/packsApi";
import { InstallPermissionsDialog } from "./InstallPermissionsDialog";
import styles from "./NodeWarehouseDrawer.module.css";

type DrawerTab = "featured" | "browse" | "installed" | "updates";
type SortMode = "new" | "name";

const CARD_ICON_VARIANTS = [styles.cardIconWarm, styles.cardIconCool, styles.cardIconViolet] as const;

function packInitial(name: string): string {
  const trimmed = name.trim();
  if (!trimmed) return "?";
  const words = trimmed.split(/\s+/);
  if (words.length >= 2) return (words[0]![0]! + words[1]![0]!).toUpperCase();
  return trimmed.slice(0, 2).toUpperCase();
}

function iconVariantForPack(dirName: string): string {
  let hash = 0;
  for (let i = 0; i < dirName.length; i++) hash = (hash + dirName.charCodeAt(i)) % CARD_ICON_VARIANTS.length;
  return CARD_ICON_VARIANTS[hash]!;
}

function primaryCategory(pack: PackPayload): string {
  const cat = pack.kinds[0]?.category;
  if (!cat) return "pack";
  if (cat.startsWith("vis")) return "vis";
  return cat;
}

function sortPacks(packs: PackPayload[], mode: SortMode): PackPayload[] {
  const next = [...packs];
  if (mode === "name") {
    next.sort((a, b) => a.name.localeCompare(b.name, undefined, { sensitivity: "base" }));
    return next;
  }
  next.sort((a, b) => {
    const c = (b.createdAtMs ?? 0) - (a.createdAtMs ?? 0);
    if (c !== 0) return c;
    return a.dirName.localeCompare(b.dirName, undefined, { sensitivity: "base" });
  });
  return next;
}

function matchesSearch(pack: PackPayload, query: string): boolean {
  if (!query.trim()) return true;
  const q = query.trim().toLowerCase();
  return (
    pack.name.toLowerCase().includes(q) ||
    pack.publisher.toLowerCase().includes(q) ||
    pack.description.toLowerCase().includes(q) ||
    pack.packId.toLowerCase().includes(q)
  );
}

export interface NodeWarehouseDrawerProps {
  onRequestClose: () => void;
}

export const NodeWarehouseDrawer: React.FC<NodeWarehouseDrawerProps> = ({ onRequestClose }) => {
  const navigate = useNavigate();
  const drawerRef = useRef<HTMLElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [catalog, setCatalog] = useState<PackPayload[]>([]);
  const [installed, setInstalled] = useState<PackPayload[]>([]);
  const [tab, setTab] = useState<DrawerTab>("featured");
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState<SortMode>("new");
  const [pinned, setPinned] = useState(false);
  const [busy, setBusy] = useState(false);
  const [installCandidate, setInstallCandidate] = useState<PackPayload | null>(null);
  const [conflictReport, setConflictReport] = useState<ResolveConflict[] | null>(null);

  const installedDirs = useMemo(() => new Set(installed.map((p) => p.dirName)), [installed]);
  const catalogByDir = useMemo(() => new Map(catalog.map((p) => [p.dirName, p])), [catalog]);

  const reload = useCallback(async () => {
    const [cat, mine] = await Promise.all([packsApi.catalog(), packsApi.listInstalled()]);
    const installedSet = new Set(mine.packs.map((p) => p.dirName));
    setCatalog(cat.packs.map((p) => ({ ...p, installed: installedSet.has(p.dirName) })));
    setInstalled(mine.packs);
  }, []);

  useEffect(() => {
    void reload().catch(() => {
      /* drawer stays usable with empty lists */
    });
  }, [reload]);

  useEffect(() => {
    drawerRef.current?.focus();
  }, []);

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

  const renderPackCard = (pack: PackPayload) => {
    const isInstalled = installedDirs.has(pack.dirName);
    const catalogRow = catalogByDir.get(pack.dirName);
    const hasUpdate = isInstalled && catalogRow != null && catalogRow.version !== pack.version;

    return (
      <article key={pack.dirName} className={styles.card}>
        <div className={`${styles.cardIcon} ${iconVariantForPack(pack.dirName)}`}>
          {packInitial(pack.name)}
        </div>
        <div className={styles.cardBody}>
          <h3 className={styles.cardTitle}>{pack.name}</h3>
          <p className={styles.cardMeta}>
            {pack.publisher || pack.packId} · v{pack.version}
            {pack.license ? ` · ${pack.license}` : ""}
          </p>
          <div className={styles.tagRow}>
            <span className={styles.tag}>
              {pack.kinds.length} node{pack.kinds.length === 1 ? "" : "s"}
            </span>
            <span className={styles.tag}>{primaryCategory(pack)}</span>
            {hasUpdate && catalogRow ? (
              <span className={`${styles.tag} ${styles.tagUpdate}`}>
                Update to {catalogRow.version}
              </span>
            ) : null}
          </div>
        </div>
        <div className={styles.cardAction}>
          {isInstalled ? (
            hasUpdate ? (
              <button
                type="button"
                className={`${styles.btnInstall} ${styles.btnInstallAccent}`}
                disabled={busy}
                onClick={() => void onInstallFromCatalog(catalogRow ?? pack)}
              >
                Update
              </button>
            ) : (
              <span className={styles.btnInstalled}>Installed</span>
            )
          ) : (
            <button
              type="button"
              className={styles.btnInstall}
              disabled={busy}
              onClick={() => void onInstallFromCatalog(pack)}
            >
              Install
            </button>
          )}
        </div>
      </article>
    );
  };

  return (
    <>
      <div className={styles.overlayRoot} data-curio-node-warehouse-drawer="true">
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
        >
          <header className={styles.topBar}>
            <button
              type="button"
              className={`${styles.iconBtn} ${pinned ? styles.iconBtnActive : ""}`}
              aria-label={pinned ? "Unpin drawer" : "Pin drawer open"}
              aria-pressed={pinned}
              title={pinned ? "Unpin drawer" : "Pin drawer (scrim won't close)"}
              onClick={() => setPinned((v) => !v)}
            >
              <FontAwesomeIcon icon={faThumbtack} aria-hidden />
            </button>
            <h2 id="node-warehouse-drawer-title" className={styles.drawerTitle}>
              Node warehouse
            </h2>
            <button
              type="button"
              className={styles.iconBtn}
              aria-label="Close node warehouse drawer"
              onClick={onRequestClose}
            >
              <FontAwesomeIcon icon={faXmark} aria-hidden />
            </button>
          </header>

          <div className={styles.subtitleBlock}>
            <p className={styles.subtitle}>Discover and install nodes that extend Curio.</p>
            <span className={styles.compatPill}>
              <span className={styles.compatDot} aria-hidden />
              Compatible with this Curio workspace
            </span>
          </div>

          <div className={styles.searchRow}>
            <div className={styles.searchWrap}>
              <FontAwesomeIcon icon={faMagnifyingGlass} className={styles.searchIcon} aria-hidden />
              <input
                className={styles.searchInput}
                type="search"
                placeholder="Search packs, authors, keywords..."
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </div>
            <select
              className={styles.sortSelect}
              value={sort}
              aria-label="Sort packs"
              onChange={(e) => setSort(e.target.value as SortMode)}
            >
              <option value="new">Sort: New</option>
              <option value="name">Sort: Name</option>
            </select>
          </div>

          <nav className={styles.tabs} aria-label="Warehouse sections">
            <button
              type="button"
              className={`${styles.tab} ${tab === "featured" ? styles.tabActive : ""}`}
              onClick={() => setTab("featured")}
            >
              Featured
            </button>
            <button
              type="button"
              className={`${styles.tab} ${tab === "browse" ? styles.tabActive : ""}`}
              onClick={() => setTab("browse")}
            >
              Browse all
            </button>
            <button
              type="button"
              className={`${styles.tab} ${tab === "installed" ? styles.tabActive : ""}`}
              onClick={() => setTab("installed")}
            >
              Installed
              {installed.length > 0 ? (
                <span className={`${styles.tabBadge} ${styles.tabBadgeDark}`}>{installed.length}</span>
              ) : null}
            </button>
            <button
              type="button"
              className={`${styles.tab} ${tab === "updates" ? styles.tabActive : ""} ${
                updateCandidates.length === 0 ? styles.tabMuted : ""
              }`}
              onClick={() => setTab("updates")}
            >
              Updates
              {updateCandidates.length > 0 ? (
                <span className={`${styles.tabBadge} ${styles.tabBadgeAccent}`}>
                  {updateCandidates.length}
                </span>
              ) : null}
            </button>
          </nav>

          <div className={styles.scrollBody}>
            {tab === "featured" ? (
              <p className={styles.sectionLabel}>Featured</p>
            ) : tab === "browse" ? (
              <p className={styles.sectionLabel}>Browse all</p>
            ) : tab === "installed" ? (
              <p className={styles.sectionLabel}>Installed</p>
            ) : (
              <p className={styles.sectionLabel}>Updates</p>
            )}

            {displayPacks.length === 0 ? (
              <div className={styles.empty}>No packs match the current filter.</div>
            ) : (
              <div className={styles.cardList}>{displayPacks.map(renderPackCard)}</div>
            )}

            {tab === "featured" && installed.length > 0 ? (
              <>
                <p className={styles.sectionLabel}>
                  Your packs · {installed.length} installed
                </p>
                <div className={styles.installedList}>
                  {installed.slice(0, 4).map((pack) => {
                    const catRow = catalogByDir.get(pack.dirName);
                    const hasUpdate = catRow != null && catRow.version !== pack.version;
                    return (
                      <div key={pack.dirName} className={styles.installedRow}>
                        <span className={styles.installedDot} aria-hidden />
                        <span className={styles.installedName}>{pack.name}</span>
                        <span className={styles.installedMeta}>
                          v{pack.version}
                          {hasUpdate ? " · update available" : ` · ${pack.kinds.length} nodes`}
                        </span>
                      </div>
                    );
                  })}
                </div>
              </>
            ) : null}

            <div className={styles.envNote}>
              <span className={styles.envIcon} aria-hidden>
                i
              </span>
              <div>
                <p className={styles.envTitle}>Shared project environment</p>
                <p className={styles.envText}>
                  Pack python deps install into this project&apos;s sandbox interpreter;
                  conflicting versions fail at install.
                </p>
              </div>
            </div>
          </div>

          <footer className={styles.footer}>
            <input
              ref={fileInputRef}
              type="file"
              accept=".curio-nodepack,application/zip"
              hidden
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) void onPickArchive(file);
                if (fileInputRef.current) fileInputRef.current.value = "";
              }}
            />
            <button
              type="button"
              className={styles.footerGhost}
              disabled={busy}
              onClick={() => fileInputRef.current?.click()}
            >
              Sideload .curio-nodepack
            </button>
            <button
              type="button"
              className={styles.footerPrimary}
              onClick={() => {
                onRequestClose();
                navigate("/nodes");
              }}
            >
              Open full warehouse
            </button>
          </footer>
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
