/**
 * Global node catalog under /catalog/nodes (see docs/CATALOG.md).
 */
import React from "react";
import { InstallPermissionsDialog } from "../../components/packages/publishing/InstallPermissionsDialog";
import type { SortMode } from "../../components/packages/publishing/packageTypes";
import browseStyles from "./CatalogBrowseLayout.module.css";
import { PackageBrowseCard } from "./PackageBrowseCard";
import { PackageBrowseDrawer } from "./PackageBrowseDrawer";
import { useNodeCatalogBrowse } from "./useNodeCatalogBrowse";

export const NodeCatalogBrowse: React.FC = () => {
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
    updatesCount,
    selectedHasUpdate,
    onInstall,
    confirmInstall,
    onPublish,
    cancelInstall,
  } = useNodeCatalogBrowse();

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
          <div className={browseStyles.viewToggles}>
            <button className={browseStyles.viewToggleActive} type="button" title="Grid view" aria-label="Grid view">
              <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
                <rect x="0" y="0" width="5" height="4" rx="0.5" fill="#555" />
                <rect x="7" y="0" width="5" height="4" rx="0.5" fill="#555" />
                <rect x="0" y="6" width="5" height="4" rx="0.5" fill="#555" />
                <rect x="7" y="6" width="5" height="4" rx="0.5" fill="#555" />
              </svg>
            </button>
            <button className={browseStyles.viewToggleInactive} type="button" title="List view" aria-label="List view">
              <svg width="12" height="10" viewBox="0 0 12 10" fill="none">
                <line x1="0" y1="1" x2="12" y2="1" stroke="#BBBBBB" strokeWidth="1.2" />
                <line x1="0" y1="5" x2="12" y2="5" stroke="#BBBBBB" strokeWidth="1.2" />
                <line x1="0" y1="9" x2="12" y2="9" stroke="#BBBBBB" strokeWidth="1.2" />
              </svg>
            </button>
          </div>
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
      />

      {installCandidate ? (
        <InstallPermissionsDialog
          pkg={installCandidate}
          conflicts={conflictReport ?? []}
          busy={busy}
          onCancel={cancelInstall}
          onConfirm={() => void confirmInstall()}
        />
      ) : null}
    </div>
  );
};

export default NodeCatalogBrowse;
