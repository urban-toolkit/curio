/**
 * Global Node Catalog under /catalog/nodes (see docs/NODE-CATALOG.md), and the
 * Model Catalog under /catalog/models (docs/MODEL-CATALOG.md): the same page
 * over the other kind of package (`packageKind="model"`).
 */
import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { InstallPermissionsDialog } from "../../components/packages/publishing/InstallPermissionsDialog";
import ModalShell from "../../components/ModalShell";
import { isNewerPackageVersion, type PackageKind, type SortMode } from "../../services/packages";
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
import type { CatalogItemKind } from "../../components/catalog/CatalogKindVisuals";
import {
  packageCardActions,
  type CatalogCardActionId,
} from "../../components/catalog/catalogCardActions";
import detailStyles from "../../components/agents/catalog/AgentDetailModal.module.css";

/** What each catalog's page says; everything else is the same page. */
const PAGE_COPY: Record<PackageKind, {
  path: string;
  kind: CatalogItemKind;
  title: string;
  iconTitle: string;
  railLabel: string;
  allLabel: string;
  searchPlaceholder: string;
  sortAriaLabel: string;
  intro: React.ReactNode;
  noneMatch: string;
  notFound: string;
}> = {
  node: {
    path: "/catalog/nodes",
    kind: "package",
    title: "Node Catalog",
    iconTitle: "Node package catalog",
    railLabel: "Filter packages",
    allLabel: "All packages",
    searchPlaceholder: "Search packages…",
    sortAriaLabel: "Sort packages",
    intro: (
      <>
        Node packages in the shared catalog. Adding one here adds it to{" "}
        <strong>all your projects</strong>, present and future; add or remove it for a
        single project from that project&apos;s Node Catalog.
      </>
    ),
    noneMatch: "No packages match the current filters.",
    notFound: "This package is not in your Node Catalog.",
  },
  model: {
    path: "/catalog/models",
    kind: "model",
    title: "Model Catalog",
    iconTitle: "Model Catalog",
    railLabel: "Filter models",
    allLabel: "All models",
    searchPlaceholder: "Search models…",
    sortAriaLabel: "Sort models",
    intro: (
      <>
        Trained models your nodes run, each a package with its weights and the node that runs
        it. Adding one here adds it to <strong>all your projects</strong>; add or remove it for a
        single project from that project&apos;s Model Catalog. Models you download from the{" "}
        <strong>Discovery Catalog</strong> land here too.
      </>
    ),
    noneMatch: "No models match the current filters.",
    notFound: "This model is not in your Model Catalog.",
  },
};

export interface NodeCatalogBrowseProps {
  /** Which catalog this page is: the Node Catalog (`node`, the default) or
   *  the Model Catalog (`model`). */
  packageKind?: PackageKind;
  /** A link to one package (`/catalog/models/<id>`): the page with its
   *  details open. */
  linkedPackageId?: string;
}

export const NodeCatalogBrowse: React.FC<NodeCatalogBrowseProps> = ({
  packageKind = "node",
  linkedPackageId,
}) => {
  const copy = PAGE_COPY[packageKind];
  const navigate = useNavigate();
  const [drawerSlotOpen, setDrawerSlotOpen] = useState(false);
  const {
    search,
    setSearch,
    sort,
    setSort,
    filter,
    setFilter,
    facetFilters,
    facetRows,
    toggleFacet,
    clearFilters,
    setSelectedDirName,
    loaded,
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
    mergedRows,
    filtered,
    selectedPkg,
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
  } = useNodeCatalogBrowse(packageKind);

  // Separate from `selectedDirName`, which drives the side drawer. Wiring both
  // to one setter is what made the Agent page's "View details" a no-op (#189),
  // and it is exactly what the Node card's did: it called `onSelect`, so on a
  // card whose drawer was already open the click changed nothing.
  const [detailDirName, setDetailDirName] = useState<string | null>(null);
  // A link to a package lands where every "View details" does, once the
  // listing has arrived to say whether it is there.
  const [linkMissing, setLinkMissing] = useState(false);
  useEffect(() => {
    if (!linkedPackageId || !loaded) return;
    const linked = mergedRows.find(
      (p) => p.packageId === linkedPackageId || p.dirName === linkedPackageId,
    );
    if (linked) setDetailDirName(linked.dirName);
    else setLinkMissing(true);
  }, [linkedPackageId, loaded, mergedRows]);
  const closeDetails = () => {
    setDetailDirName(null);
    setLinkMissing(false);
    // Back to the plain page, so a reload does not reopen what was closed.
    if (linkedPackageId) navigate(copy.path, { replace: true });
  };

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

  return (
    <div className={[browseStyles.page, drawerSlotOpen ? browseStyles.pageWithDrawer : ""].filter(Boolean).join(" ")}>
      <CatalogRail
        ariaLabel={copy.railLabel}
        all={{
          label: copy.allLabel,
          count: allCount,
          active: filter === "all" && Object.values(facetFilters).every((value) => !value),
          onClick: clearFilters,
        }}
        scope={{
          label: "In all projects",
          count: installedCount,
          active: filter === "installed",
          onClick: () => setFilter(filter === "installed" ? "all" : "installed"),
        }}
        sections={facetRows.map(({ facet, rows }) => ({
          key: facet.key,
          label: facet.label,
          entries: rows.map(([value, count]) => ({
            value,
            label: facet.labelOf(value),
            count,
            active: facetFilters[facet.key] === value,
            onClick: () => toggleFacet(facet.key, value),
            // Keyed like the card strips (`primaryCategory()`).
            ...(facet.dotted ? { dotClassName: browseStyles[`categoryDot_${value}`] ?? "" } : {}),
          })),
        }))}
      />

      <main className={browseStyles.browseMain}>
        <CatalogPageHeader
          kind={copy.kind}
          iconTitle={copy.iconTitle}
          title={copy.title}
          count={filtered.length}
          intro={copy.intro}
          viewTools={
            <select
              className={browseStyles.sortSelect}
              aria-label={copy.sortAriaLabel}
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
            placeholder={copy.searchPlaceholder}
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
          <div className={browseStyles.empty}>{copy.noneMatch}</div>
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
          onClose={closeDetails}
        />
      ) : linkMissing ? (
        <ModalShell
          onClose={closeDetails}
          size="xlarge"
          layer="overlay"
          label={packageKind === "model" ? "Model details" : "Package details"}
        >
          <div className={detailStyles.body}>
            <p className={detailStyles.purpose}>{copy.notFound}</p>
          </div>
        </ModalShell>
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
