/**
 * Global node catalog under /catalog/nodes (see docs/CATALOG.md).
 * Same install/publish semantics as the former CatalogPage; layout matches Data Catalog browse.
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  PackagePayload,
  ResolveConflict,
  packagesApi,
  refreshPackageRegistry,
} from "../../api/packagesApi";
import { InstallPermissionsDialog } from "../../components/packages/publishing/InstallPermissionsDialog";
import {
  matchesSearch,
  primaryCategory,
  sortPackages,
} from "../../components/packages/publishing/packageUtils";
import { SortMode } from "../../components/packages/publishing/packageTypes";
import { draftFromInstalledPackagePayload } from "../../utils/palettePackageFactoryDraft";
import { toApiPayload } from "../nodes/factoryDraftModel";
import browseStyles from "./CatalogBrowseLayout.module.css";
import { PackageBrowseCard } from "./PackageBrowseCard";
import { PackageBrowseDrawer } from "./PackageBrowseDrawer";

type FilterTab = "all" | "installed" | "updates";

export const NodeCatalogBrowse: React.FC = () => {
  const [catalog, setCatalog] = useState<PackagePayload[]>([]);
  const [installed, setInstalled] = useState<PackagePayload[]>([]);
  const [defaults, setDefaults] = useState<Set<string>>(new Set());
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState<SortMode>("new");
  const [filter, setFilter] = useState<FilterTab>("all");
  const [categoryFilter, setCategoryFilter] = useState<string>("");
  const [selectedDirName, setSelectedDirName] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [catalogPublishAllowed, setCatalogPublishAllowed] = useState(false);
  const [publishingPackageKey, setPublishingPackageKey] = useState<string | null>(null);
  const [installCandidate, setInstallCandidate] = useState<PackagePayload | null>(null);
  const [conflictReport, setConflictReport] = useState<ResolveConflict[] | null>(null);
  const [lastInstallSummary, setLastInstallSummary] = useState<string | null>(null);

  const reportError = useCallback((label: string, err: unknown) => {
    const status = (err as { status?: number } | null)?.status;
    const body = (err as { body?: { error?: string } } | null)?.body;
    const message = (err as { message?: string } | null)?.message;
    const detail = body?.error ?? message ?? (status ? `HTTP ${status}` : "unknown error");
    setActionError(`${label}: ${detail}`);
  }, []);

  const reload = useCallback(async () => {
    const [cat, mine, cap, defaultsResp] = await Promise.all([
      packagesApi.catalog(),
      packagesApi.listInstalled(),
      packagesApi.factoryCapabilities(),
      packagesApi.getDefaults(),
    ]);
    setCatalog(cat.packages);
    setInstalled(mine.packages);
    setCatalogPublishAllowed(cap.catalogPublish);
    setDefaults(new Set(defaultsResp.packages));
  }, []);

  useEffect(() => {
    void reload().catch((err) => reportError("Couldn't load catalog", err));
  }, [reload, reportError]);

  const installedByDir = useMemo(
    () => new Map(installed.map((p) => [p.dirName, p])),
    [installed],
  );
  const catalogByDir = useMemo(() => new Map(catalog.map((p) => [p.dirName, p])), [catalog]);
  const catalogPublishedDirs = useMemo(() => new Set(catalog.map((p) => p.dirName)), [catalog]);

  const updateCandidates = useMemo(() => {
    return installed.filter((row) => {
      const catRow = catalogByDir.get(row.dirName);
      return catRow != null && catRow.version !== row.version;
    });
  }, [installed, catalogByDir]);
  const updateCandidateDirs = useMemo(
    () => new Set(updateCandidates.map((p) => p.dirName)),
    [updateCandidates],
  );

  const mergedRows = useMemo(() => {
    const out = new Map<string, PackagePayload>();
    for (const row of installed) out.set(row.dirName, row);
    for (const row of catalog) out.set(row.dirName, row);
    return Array.from(out.values());
  }, [catalog, installed]);

  const bySearch = useMemo(
    () => mergedRows.filter((p) => matchesSearch(p, search)),
    [mergedRows, search],
  );

  const categoryFacetBase = useMemo(() => {
    let b = bySearch;
    if (filter === "installed") {
      b = b.filter((p) => defaults.has(p.dirName));
    } else if (filter === "updates") {
      b = b.filter((p) => updateCandidateDirs.has(p.dirName));
    }
    return b;
  }, [bySearch, filter, defaults, updateCandidateDirs]);

  const categoryCounts = useMemo(() => {
    const m = new Map<string, number>();
    for (const p of categoryFacetBase) {
      const c = primaryCategory(p);
      m.set(c, (m.get(c) ?? 0) + 1);
    }
    return m;
  }, [categoryFacetBase]);

  const sortedCategories = useMemo(
    () => Array.from(categoryCounts.entries()).sort((a, b) => b[1] - a[1]),
    [categoryCounts],
  );

  const quickCategories = useMemo(() => sortedCategories.slice(0, 3).map(([k]) => k), [sortedCategories]);

  const filtered = useMemo(() => {
    let base = categoryFacetBase;
    if (categoryFilter) {
      base = base.filter((p) => primaryCategory(p) === categoryFilter);
    }
    return sortPackages(base, sort);
  }, [categoryFacetBase, categoryFilter, sort]);

  useEffect(() => {
    if (filtered.length === 0) {
      setSelectedDirName(null);
      return;
    }
    if (selectedDirName == null || !filtered.some((p) => p.dirName === selectedDirName)) {
      setSelectedDirName(filtered[0]!.dirName);
    }
  }, [filtered, selectedDirName]);

  const selectedPkg = useMemo(
    () => filtered.find((p) => p.dirName === selectedDirName) ?? filtered[0] ?? null,
    [filtered, selectedDirName],
  );

  const onInstall = useCallback(async (pkg: PackagePayload) => {
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
  }, [installed]);

  const confirmInstall = useCallback(async () => {
    if (!installCandidate) return;
    setBusy(true);
    setActionError(null);
    setLastInstallSummary(null);
    try {
      const result = await packagesApi.installToDefaults(installCandidate.dirName);
      const succeeded = result.projects.filter((p) => p.ok).length;
      const failed = result.projects.filter((p) => !p.ok);
      const proj = result.projects.length;
      const summary = failed.length === 0
        ? `Installed ${installCandidate.name} for ${proj} project${proj === 1 ? "" : "s"}` +
          (proj === 0 ? " (no existing projects; will seed into new ones)" : "")
        : `Installed for ${succeeded}/${proj} projects; ${failed.length} failed: ${failed.map((f) => f.id).join(", ")}`;
      setLastInstallSummary(summary);
      await refreshPackageRegistry();
      await reload();
      setInstallCandidate(null);
      setConflictReport(null);
    } catch (err) {
      reportError(`Couldn't install ${installCandidate.name}`, err);
    } finally {
      setBusy(false);
    }
  }, [installCandidate, reload, reportError]);

  const onPublish = useCallback(async (dirName: string) => {
    const row = installedByDir.get(dirName);
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
      reportError(`Couldn't publish ${row.name}`, err);
    } finally {
      setPublishingPackageKey(null);
    }
  }, [installedByDir, reload, reportError]);

  const allCount = bySearch.length;
  const installedCount = bySearch.filter((p) => defaults.has(p.dirName)).length;
  const updatesCount = bySearch.filter((p) => updateCandidateDirs.has(p.dirName)).length;

  return (
    <div className={browseStyles.page}>
      <aside className={browseStyles.categoryRail}>
        <p className={browseStyles.railLabel}>By status</p>
        <button
          className={`${browseStyles.railButton} ${filter === "all" ? browseStyles.railButtonActive : ""}`}
          type="button"
          onClick={() => setFilter("all")}
        >
          <span>All packages</span>
          <span className={browseStyles.railCountBadge}>{allCount}</span>
        </button>
        <button
          className={`${browseStyles.railButton} ${filter === "installed" ? browseStyles.railButtonActive : ""}`}
          type="button"
          onClick={() => setFilter("installed")}
        >
          <span>In defaults</span>
          <span className={browseStyles.railCount}>{installedCount}</span>
        </button>
        <button
          className={`${browseStyles.railButton} ${filter === "updates" ? browseStyles.railButtonActive : ""}`}
          type="button"
          onClick={() => setFilter("updates")}
        >
          <span>Updates</span>
          <span className={browseStyles.railCount}>{updatesCount}</span>
        </button>

        <div className={browseStyles.railDivider} />
        <p className={browseStyles.railLabel}>By category</p>
        <button
          className={`${browseStyles.railButton} ${categoryFilter === "" ? browseStyles.railButtonActive : ""}`}
          type="button"
          onClick={() => setCategoryFilter("")}
        >
          <span>All categories</span>
        </button>
        {sortedCategories.map(([cat, count]) => (
          <button
            key={cat}
            className={`${browseStyles.railButton} ${categoryFilter === cat ? browseStyles.railButtonActive : ""}`}
            type="button"
            onClick={() => setCategoryFilter((prev) => (prev === cat ? "" : cat))}
          >
            <span>{cat}</span>
            <span className={browseStyles.railCount}>{count}</span>
          </button>
        ))}
      </aside>

      <main className={browseStyles.browseMain}>
        <section className={browseStyles.browseHeader}>
          <p className={browseStyles.crumb}>Node catalog</p>
          <div className={browseStyles.titleRow}>
            <h1>Node catalog</h1>
            <span className={browseStyles.titleCount}>{filtered.length}</span>
          </div>
          <p style={{ margin: "0 0 12px", fontSize: 13, color: "#6B6B76", maxWidth: 720 }}>
            Install packages for <strong>all your projects</strong>, present and future.
            Removing a package from a single project can be done in that project&apos;s node catalog.
          </p>
          <div className={browseStyles.headerTools}>
            <span className={browseStyles.hubStatusChip}>
              <span className={browseStyles.hubStatusDot} />
              Global defaults
            </span>
            <input
              className={browseStyles.hubSearch}
              type="search"
              placeholder="Search packages…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
            <select
              className={browseStyles.sortSelect}
              value={sort}
              onChange={(e) => setSort(e.target.value as SortMode)}
              style={{ border: "1px solid #E5E5E5", borderRadius: 8, padding: "6px 10px", background: "#fff" }}
            >
              <option value="new">Sort: Newest</option>
              <option value="name">Sort: Name</option>
            </select>
          </div>
        </section>

        <div className={browseStyles.filterBar}>
          <button
            className={`${browseStyles.chip} ${filter === "all" ? browseStyles.chipActive : ""}`}
            type="button"
            onClick={() => setFilter("all")}
          >
            All
          </button>
          <button
            className={`${browseStyles.chip} ${filter === "installed" ? browseStyles.chipActive : ""}`}
            type="button"
            onClick={() => setFilter("installed")}
          >
            In defaults
          </button>
          <button
            className={`${browseStyles.chip} ${filter === "updates" ? browseStyles.chipActive : ""}`}
            type="button"
            onClick={() => setFilter("updates")}
          >
            Updates
          </button>
          {quickCategories.map((cat) => (
            <button
              key={cat}
              className={`${browseStyles.chip} ${categoryFilter === cat ? browseStyles.chipActive : ""}`}
              type="button"
              onClick={() => setCategoryFilter((prev) => (prev === cat ? "" : cat))}
            >
              {cat}
            </button>
          ))}
          <span className={browseStyles.filterSpacer} />
        </div>

        {lastInstallSummary ? (
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              background: "#E7F1FF",
              color: "#1E1F23",
              border: "1px solid #B4D2FA",
              borderRadius: 6,
              padding: "10px 14px",
              margin: "12px 24px 0",
              fontSize: 13,
            }}
          >
            {lastInstallSummary}
            <button type="button" style={{ background: "none", border: "none", cursor: "pointer", fontSize: 18 }} onClick={() => setLastInstallSummary(null)}>×</button>
          </div>
        ) : null}

        {actionError ? (
          <div
            role="alert"
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              background: "#FFE3DA",
              color: "#7B2D14",
              border: "1px solid #F2A48A",
              borderRadius: 6,
              padding: "10px 14px",
              margin: "12px 24px 0",
              fontSize: 13,
            }}
          >
            {actionError}
            <button type="button" style={{ background: "none", border: "none", cursor: "pointer", fontSize: 18 }} onClick={() => setActionError(null)}>×</button>
          </div>
        ) : null}

        {filtered.length === 0 ? (
          <div className={browseStyles.empty}>No packages match the current filters.</div>
        ) : (
          <section className={browseStyles.cardGrid}>
            {filtered.map((pkg) => {
              const userStoreRow = installedByDir.get(pkg.dirName);
              const isInstalledGlobally = defaults.has(pkg.dirName);
              const catalogRow = catalogByDir.get(pkg.dirName);
              const hasUpdate =
                isInstalledGlobally
                && userStoreRow != null
                && catalogRow != null
                && catalogRow.version !== userStoreRow.version;
              const isPublished = catalogPublishedDirs.has(pkg.dirName);
              const showPublish = userStoreRow != null;
              return (
                <PackageBrowseCard
                  key={pkg.dirName}
                  pkg={pkg}
                  selected={selectedPkg?.dirName === pkg.dirName}
                  isInstalled={isInstalledGlobally}
                  hasUpdate={hasUpdate}
                  catalogRow={catalogRow}
                  busy={busy}
                  catalogPublishAllowed={catalogPublishAllowed}
                  isPublished={isPublished}
                  publishingDir={publishingPackageKey}
                  showPublish={showPublish}
                  onSelect={() => setSelectedDirName(pkg.dirName)}
                  onInstall={(p) => void onInstall(p)}
                  onPublish={showPublish ? onPublish : undefined}
                />
              );
            })}
          </section>
        )}
      </main>

      <PackageBrowseDrawer
        pkg={selectedPkg}
        isInstalled={selectedPkg != null && defaults.has(selectedPkg.dirName)}
        hasUpdate={
          selectedPkg != null
          && defaults.has(selectedPkg.dirName)
          && installedByDir.get(selectedPkg.dirName) != null
          && catalogByDir.get(selectedPkg.dirName) != null
          && catalogByDir.get(selectedPkg.dirName)!.version !== installedByDir.get(selectedPkg.dirName)!.version
        }
        catalogRow={selectedPkg ? catalogByDir.get(selectedPkg.dirName) : undefined}
        busy={busy}
        catalogPublishAllowed={catalogPublishAllowed}
        isPublished={selectedPkg ? catalogPublishedDirs.has(selectedPkg.dirName) : false}
        publishingDir={publishingPackageKey}
        showPublish={selectedPkg != null && installedByDir.get(selectedPkg.dirName) != null}
        onInstall={(p) => void onInstall(p)}
        onPublish={
          selectedPkg != null && installedByDir.get(selectedPkg.dirName) != null
            ? onPublish
            : undefined
        }
      />

      {installCandidate ? (
        <InstallPermissionsDialog
          pkg={installCandidate}
          conflicts={conflictReport ?? []}
          busy={busy}
          onCancel={() => {
            setInstallCandidate(null);
            setConflictReport(null);
          }}
          onConfirm={() => void confirmInstall()}
        />
      ) : null}
    </div>
  );
};

export default NodeCatalogBrowse;
