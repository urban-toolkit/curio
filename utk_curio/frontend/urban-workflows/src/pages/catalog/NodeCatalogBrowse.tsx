/**
 * Global Node Catalog under /catalog/nodes (see docs/NODE-CATALOG.md).
 */
import React, { useState } from "react";
import { InstallPermissionsDialog } from "../../components/packages/publishing/InstallPermissionsDialog";
import { isNewerPackageVersion, type SortMode } from "../../services/packages";
import browseStyles from "./CatalogBrowseLayout.module.css";
import { PackageBrowseCard } from "./PackageBrowseCard";
import { PackageBrowseDrawer } from "./PackageBrowseDrawer";
import { useNodeCatalogBrowse } from "./useNodeCatalogBrowse";
import { CatalogHeaderImport } from "./CatalogHeaderImport";
import { CatalogPageHeader } from "./CatalogPageHeader";
import { CatalogRail } from "./CatalogRail";
import { PackageDetailModal } from "../../components/packages/publishing/PackageDetailModal";
import type { PackagePayload } from "../../services/packages";
import { CardContextMenu } from "../../components/catalog/CardContextMenu";
import {
  packageCardActions,
  type CatalogCardActionId,
} from "../../components/catalog/catalogCardActions";

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
    installMode,
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
    allCount,
    installedCount,
    selectedHasUpdate,
    onInstall,
    onUpdate,
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

  // Right-click. The card reports the event, the grid owns the menu - the same
  // division the projects page has used all along (#285). `hasUpdate` rides in
  // the state because it is computed per row in the grid below.
  const [contextMenu, setContextMenu] = useState<{
    x: number;
    y: number;
    pkg: PackagePayload;
    isInstalled: boolean;
    hasUpdate: boolean;
    catalogRow: PackagePayload | undefined;
  } | null>(null);

  const runPackageAction = (
    id: CatalogCardActionId,
    menu: { pkg: PackagePayload; catalogRow: PackagePayload | undefined },
  ) => {
    switch (id) {
      case "add-to-all-projects":
        void onInstall(menu.pkg);
        return;
      case "update-all-projects":
        // The catalog's row, so the review and the toast name the version the
        // store copy is replaced with. Same fallback the drawer's button uses.
        void onUpdate(menu.catalogRow ?? menu.pkg);
        return;
      case "view-details":
        setDetailDirName(menu.pkg.dirName);
        return;
      // A package's defaults entry is dropped from the drawer, not from here:
      // the browse card has never offered it.
      case "remove-from-all-projects":
        return;
    }
  };
  // The card's own row while it is listed, then the unfiltered lists, as the
  // Agent page does: the modal outlives a filter change.
  const detailPkg = detailDirName
    ? (filtered.find((p) => p.dirName === detailDirName) ??
        installedByDir.get(detailDirName) ??
        catalogByDir.get(detailDirName) ??
        null)
    : null;

  // The counts come from the rows on screen, so a search can take the selected
  // category's count to zero; it stays on the rail so it can be cleared.
  const categoryRows: [string, number][] =
    categoryFilter && !sortedCategories.some(([cat]) => cat === categoryFilter)
      ? [...sortedCategories, [categoryFilter, 0]]
      : sortedCategories;

  return (
    <div className={[browseStyles.page, drawerSlotOpen ? browseStyles.pageWithDrawer : ""].filter(Boolean).join(" ")}>
      <CatalogRail
        ariaLabel="Filter packages"
        all={{
          label: "All packages",
          count: allCount,
          active: filter === "all" && categoryFilter === "",
          onClick: () => {
            setFilter("all");
            setCategoryFilter("");
          },
        }}
        scope={{
          label: "In all projects",
          count: installedCount,
          active: filter === "installed",
          onClick: () => setFilter(filter === "installed" ? "all" : "installed"),
        }}
        sections={[
          {
            key: "category",
            label: "By category",
            entries: categoryRows.map(([cat, count]) => ({
              value: cat,
              label: cat,
              count,
              active: categoryFilter === cat,
              onClick: () => setCategoryFilter((prev) => (prev === cat ? "" : cat)),
              // Keyed like the card strips (`primaryCategory()`).
              dotClassName: browseStyles[`categoryDot_${cat}`] ?? "",
            })),
          },
        ]}
      />

      <main className={browseStyles.browseMain}>
        <CatalogPageHeader
          kind="package"
          iconTitle="Node package catalog"
          title="Node Catalog"
          count={filtered.length}
          intro={
            <>
              Node packages in the shared catalog. Adding one here adds it to{" "}
              <strong>all your projects</strong>, present and future; add or remove it for a
              single project from that project&apos;s Node Catalog.
            </>
          }
          viewTools={
            <select
              className={browseStyles.sortSelect}
              aria-label="Sort packages"
              value={sort}
              onChange={(e) => setSort(e.target.value as SortMode)}
            >
              <option value="new">Sort: Newest</option>
              <option value="name">Sort: Name</option>
            </select>
          }
        >
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
        </CatalogPageHeader>

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
                isNewerPackageVersion(catalogRow.version, userStoreRow.version);
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
                  onContextMenu={(e) => {
                    e.preventDefault();
                    // Select first: the menu acts on this package, so the
                    // drawer beside it should not still describe another one.
                    setSelectedDirName(pkg.dirName);
                    setContextMenu({
                      x: e.clientX,
                      y: e.clientY,
                      pkg,
                      isInstalled: isInstalledGlobally,
                      hasUpdate,
                      catalogRow,
                    });
                  }}
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
        onUpdate={(p) => void onUpdate(p)}
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

      {contextMenu ? (
        <CardContextMenu
          x={contextMenu.x}
          y={contextMenu.y}
          ariaLabel="Package actions"
          items={packageCardActions({
            isInstalled: contextMenu.isInstalled,
            hasUpdate: contextMenu.hasUpdate,
          })}
          onSelect={(id) => runPackageAction(id as CatalogCardActionId, contextMenu)}
          onDismiss={() => setContextMenu(null)}
        />
      ) : null}

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
          confirmLabel={installMode === "update" ? "Update all projects" : "Add to all projects"}
          busyLabel={installMode === "update" ? "Updating…" : undefined}
        />
      ) : null}
    </div>
  );
};

export default NodeCatalogBrowse;
