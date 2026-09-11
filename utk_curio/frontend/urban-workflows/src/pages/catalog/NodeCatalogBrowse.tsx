/**
 * Global Node Catalog under /catalog/nodes (see docs/NODE-CATALOG.md).
 */
import React, { useState } from "react";
import { InstallPermissionsDialog } from "../../components/packages/publishing/InstallPermissionsDialog";
import type { SortMode } from "../../components/packages/publishing/packageTypes";
import { CatalogKindIcon } from "../../components/catalog/CatalogKindVisuals";
import browseStyles from "./CatalogBrowseLayout.module.css";
import { PackageBrowseCard } from "./PackageBrowseCard";
import { PackageBrowseDrawer } from "./PackageBrowseDrawer";
import { useNodeCatalogBrowse } from "./useNodeCatalogBrowse";
import { CatalogHeaderImport } from "./CatalogHeaderImport";
import { PackageDetailModal } from "../../components/packages/publishing/PackageDetailModal";

export const NodeCatalogBrowse: React.FC = () => {
  const [drawerSlotOpen, setDrawerSlotOpen] = useState(false);
  const {
    search,
    setSearch,
    sort,
    setSort,
    filter,
    setFilter,
    categoryFilter,
    setCategoryFilter,
    setSelectedDirName,
    busy,
    actionError,
    catalogPublishAllowed,
    publishingPackageKey,
    installCandidate,
    conflictReport,
    lastInstallSummary,
    dismissInstallSummary,
    dismissActionError,
    installedByDir,
    catalogByDir,
    catalogPublishedDirs,
    defaults,
    filtered,
    selectedPkg,
    sortedCategories,
    quickCategories,
    allCount,
    installedCount,
    selectedHasUpdate,
    onInstall,
    importing,
    onImportArchive,
    confirmInstall,
    onPublish,
    onUnpublish,
    cancelInstall,
  } = useNodeCatalogBrowse();

  // Separate from `selectedDirName`, which drives the side drawer. Wiring both
  // to one setter is what made the Agent page's "View details" a no-op (#189),
  // and it is exactly what the Node card's did: it called `onSelect`, so on a
  // card whose drawer was already open the click changed nothing.
  const [detailDirName, setDetailDirName] = useState<string | null>(null);
  const detailPkg = detailDirName
    ? (filtered.find((p) => p.dirName === detailDirName) ?? null)
    : null;

  return (
    <div className={[browseStyles.page, drawerSlotOpen ? browseStyles.pageWithDrawer : ""].filter(Boolean).join(" ")}>
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
          <span>In all projects</span>
          <span className={browseStyles.railCount}>{installedCount}</span>
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
          <p className={browseStyles.crumb}>Node Catalog</p>
          <div className={browseStyles.titleRow}>
            <CatalogKindIcon kind="package" size="md" title="Node package catalog" />
            <h1>Node Catalog</h1>
            <span className={browseStyles.titleCount}>{filtered.length}</span>
          </div>
          <p className={browseStyles.pageIntro}>
            Node packages in the shared catalog. Adding one here adds it to{" "}
            <strong>all your projects</strong>, present and future; add or remove it for a
            single project from that project&apos;s Node Catalog.
          </p>
          <div className={browseStyles.headerTools}>
            <input
              className={browseStyles.hubSearch}
              type="search"
              placeholder="Search packages…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
            {/* The drawer has had this in its footer all along; the page had no
                import at all. Same position the Projects page uses. */}
            <CatalogHeaderImport
              label="Import package"
              accept=".curio.zip,.zip,application/zip"
              busy={importing}
              onPick={(file) => void onImportArchive(file)}
              title="Import a .curio.zip package archive"
            />
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
            In all projects
          </button>
          {quickCategories.map((cat) => {
            const dotSlug = cat.toLowerCase().replace(/[^a-z0-9-]/g, "");
            const dotClass =
              (browseStyles as Record<string, string>)[`chipDot_${dotSlug}`] ??
              browseStyles.chipDotDefault;
            return (
              <button
                key={cat}
                className={`${browseStyles.chip} ${categoryFilter === cat ? browseStyles.chipActive : ""}`}
                type="button"
                onClick={() => setCategoryFilter((prev) => (prev === cat ? "" : cat))}
              >
                <span className={`${browseStyles.chipDot} ${dotClass}`} />
                {cat}
              </button>
            );
          })}
          <span className={browseStyles.filterSpacer} />
          <select
            className={browseStyles.sortSelect}
            value={sort}
            onChange={(e) => setSort(e.target.value as SortMode)}
          >
            <option value="new">Sort: Newest</option>
            <option value="name">Sort: Name</option>
          </select>
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
            <button
              type="button"
              style={{ background: "none", border: "none", cursor: "pointer", fontSize: 18 }}
              onClick={dismissInstallSummary}
            >
              ×
            </button>
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
            <button
              type="button"
              style={{ background: "none", border: "none", cursor: "pointer", fontSize: 18 }}
              onClick={dismissActionError}
            >
              ×
            </button>
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
                isInstalledGlobally &&
                userStoreRow != null &&
                catalogRow != null &&
                catalogRow.version !== userStoreRow.version;
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
                  onSelect={() => setSelectedDirName(pkg.dirName)}
                  onViewDetails={() => setDetailDirName(pkg.dirName)}
                />
              );
            })}
          </section>
        )}
      </main>

      <PackageBrowseDrawer
        pkg={selectedPkg}
        isInstalled={selectedPkg != null && defaults.has(selectedPkg.dirName)}
        hasUpdate={selectedHasUpdate}
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
        onUnpublish={
          selectedPkg != null && installedByDir.get(selectedPkg.dirName) != null
            ? onUnpublish
            : undefined
        }
        onViewDetails={(p) => setDetailDirName(p.dirName)}
        onClose={() => setSelectedDirName(null)}
        onLayoutChange={setDrawerSlotOpen}
      />

      {detailPkg ? (
        <PackageDetailModal
          pkg={detailPkg}
          inAllProjects={defaults.has(detailPkg.dirName)}
          isPublished={catalogPublishedDirs.has(detailPkg.dirName)}
          onClose={() => setDetailDirName(null)}
        />
      ) : null}

      {installCandidate ? (
        <InstallPermissionsDialog
          pkg={installCandidate}
          conflicts={conflictReport ?? []}
          busy={busy}
          onCancel={cancelInstall}
          onConfirm={() => void confirmInstall()}
          confirmLabel="Add to all projects"
        />
      ) : null}
    </div>
  );
};

export default NodeCatalogBrowse;
