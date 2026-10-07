import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { DrawerHeader } from "../../packages/publishing/DrawerHeader";
import { PackageSearchRow } from "../../packages/publishing/PackageSearchRow";
import shell from "../../packages/publishing/CatalogDrawerShell.module.css";
import { useDrawerDragThrough } from "../../packages/publishing/useDrawerDragThrough";
import { modalStackDepth } from "../../ModalShell";
import { useDatasetDetails } from "../../datasets/catalog/datasetDetailsContext";
import { useModelCatalogDrawer } from "../../../providers/modelCatalog";
import {
  isStorageSource,
  partialFailureMessage,
  scanningMessage,
  useDiscoveryCatalog,
  useDiscoverySearch,
} from "../../../services/discoveryCatalog";
import { DISCOVERY_SORT_OPTIONS, type DiscoverySortMode } from "../../../pages/discovery/discoveryBrowseConstants";
import { DiscoveryFederatedRows } from "../../../pages/discovery/DiscoveryFederatedRows";
import { DiscoverySourceBody } from "../../../pages/discovery/DiscoverySourceDetail";
import { DiscoverySourceCard } from "../../../pages/discovery/DiscoverySourceCard";
import { DiscoverySourceDetailModal } from "../../../pages/discovery/DiscoverySourceDetailModal";
import { useDiscoveryAcquisition } from "../../../pages/discovery/useDiscoveryAcquisition";
import browseStyles from "../../../pages/catalog/CatalogBrowseLayout.module.css";
import styles from "./DiscoveryCatalogDrawer.module.css";

export interface DiscoveryCatalogDrawerProps {
  presented: boolean;
  onRequestClose: () => void;
  onExitComplete: () => void;
}

/**
 * The Discovery Catalog on the canvas: every source this deployment can
 * reach, searched all at once or opened one at a time, without leaving the
 * dataflow.
 *
 * Built like the Model drawer (the same shell, header and search row, Escape
 * and pin rules), from the Discovery page's own parts: the source cards, the
 * federated rows and a source's body are the components `/catalog/discovery`
 * renders, with the query and the open source held here instead of in the URL.
 * What is added lands in the Data or Model Catalog, as it does from the page.
 */
export const DiscoveryCatalogDrawer: React.FC<DiscoveryCatalogDrawerProps> = ({
  presented,
  onRequestClose,
  onExitComplete,
}) => {
  const drawerRef = useRef<HTMLElement>(null);
  const dragThrough = useDrawerDragThrough();
  const [pinned, setPinned] = useState(false);
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState<DiscoverySortMode>("name");
  // The source open in the drawer, and the query asked of it.
  const [sourceDir, setSourceDir] = useState<string | null>(null);
  const [sourceQuery, setSourceQuery] = useState("");
  const [detailDir, setDetailDir] = useState<string | null>(null);
  const { openDatasetDetails } = useDatasetDetails();
  const { openModelCatalogDrawer } = useModelCatalogDrawer();

  // A model lands in the Model Catalog, which is a drawer of its own here.
  const viewModel = useCallback(() => {
    onRequestClose();
    openModelCatalogDrawer();
  }, [onRequestClose, openModelCatalogDrawer]);

  const { data, loading, error, reload } = useDiscoveryCatalog();
  const searching = search.trim().length > 0;
  const results = useDiscoverySearch({ q: searching ? search : "" });
  const acquisition = useDiscoveryAcquisition({
    isStorage: (job) => data.sources.some((s) => s.dirName === job.sourceId && isStorageSource(s)),
    onViewModel: viewModel,
  });

  const sources = useMemo(() => {
    const rows = [...data.sources];
    if (sort === "provider") {
      rows.sort((a, b) => a.provider.localeCompare(b.provider) || a.name.localeCompare(b.name));
    }
    return rows;
  }, [data.sources, sort]);
  const sourcesById = useMemo(() => new Map(data.sources.map((s) => [s.sourceId, s])), [data.sources]);
  const detailSource = useMemo(
    () => (detailDir ? sources.find((s) => s.dirName === detailDir) ?? null : null),
    [sources, detailDir],
  );
  const partialFailure = useMemo(
    () => partialFailureMessage(results.data.sources, (id) => sourcesById.get(id)?.name ?? ""),
    [results.data.sources, sourcesById],
  );
  const stillScanning = useMemo(
    () => scanningMessage(results.data.sources, (id) => sourcesById.get(id)?.name ?? ""),
    [results.data.sources, sourcesById],
  );

  const openSource = (dirName: string) => {
    setSourceDir(dirName);
    setSourceQuery("");
  };

  // Escape dismisses this drawer, as it does its peers: a modal on top (a
  // source's details, a dataset's) owns Escape while it is open, and a pinned
  // drawer is being deliberately kept open.
  useEffect(() => {
    if (!presented) return;
    const onKey = (ev: KeyboardEvent) => {
      if (modalStackDepth() > 0) return;
      if (ev.key === "Escape" && !pinned) onRequestClose?.();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [presented, pinned, onRequestClose]);

  const handleDrawerTransitionEnd = useCallback(
    (e: React.TransitionEvent<HTMLElement>) => {
      if (e.target !== drawerRef.current || e.propertyName !== "transform" || presented) return;
      onExitComplete();
    },
    [onExitComplete, presented],
  );

  return (
    <>
      <div
        className={`${shell.overlayRoot} ${styles.overlayRoot} ${
          presented ? shell.overlayRootPresented : ""
        }`}
        data-curio-discovery-catalog-drawer="true"
        aria-hidden={!presented}
        {...dragThrough}
      >
        <button
          type="button"
          className={shell.scrim}
          aria-label="Close discovery catalog"
          onClick={() => {
            if (!pinned) onRequestClose();
          }}
        />
        <aside
          ref={drawerRef}
          className={shell.drawer}
          role="dialog"
          aria-modal="true"
          aria-labelledby="discovery-catalog-title"
          tabIndex={-1}
          onTransitionEnd={handleDrawerTransitionEnd}
        >
          <DrawerHeader
            pinned={pinned}
            onPinToggle={() => setPinned((v) => !v)}
            onClose={onRequestClose}
            kind="source"
            title="Discovery Catalog"
            titleId="discovery-catalog-title"
            subtitle="Search data portals and storage; what you add lands in your Data or Model Catalog."
            closeAriaLabel="Close Discovery Catalog drawer"
          />

          {sourceDir ? (
            <main className={shell.scrollBody}>
              <DiscoverySourceBody
                sourceDir={sourceDir}
                q={sourceQuery}
                onQueryChange={setSourceQuery}
                onAllPortals={() => setSourceDir(null)}
                onViewModel={viewModel}
                className={styles.sourceBody}
              />
            </main>
          ) : (
            <>
              <PackageSearchRow
                search={search}
                sort={sort}
                onSearchChange={setSearch}
                onSortChange={setSort}
                placeholder="Search every portal…"
                sortAriaLabel="Sort sources"
                sortOptions={DISCOVERY_SORT_OPTIONS}
              />
              <main className={shell.scrollBody}>
                {error ? (
                  <div className={`${browseStyles.browseBanner} ${styles.banner}`} role="alert">
                    <span>{error}</span>
                    <button
                      type="button"
                      className={browseStyles.browseBannerDismiss}
                      aria-label="Retry"
                      onClick={reload}
                    >
                      ↻
                    </button>
                  </div>
                ) : null}
                {searching && partialFailure ? (
                  <div className={`${browseStyles.browseBanner} ${styles.banner}`} role="status">
                    <span>{partialFailure}</span>
                  </div>
                ) : null}
                {searching && stillScanning ? (
                  <div className={`${browseStyles.browseBanner} ${styles.banner}`} role="status">
                    <span>{stillScanning}</span>
                  </div>
                ) : null}
                {searching ? (
                  <div className={shell.cardList}>
                    <DiscoveryFederatedRows
                      resources={results.data.resources}
                      sourcesById={sourcesById}
                      acquisition={acquisition}
                      onViewDataset={(id) => openDatasetDetails(id)}
                      onViewModel={viewModel}
                    />
                    {!results.loading && results.searched && results.data.resources.length === 0 ? (
                      <div className={shell.empty}>No portal returned anything for “{search}”.</div>
                    ) : null}
                  </div>
                ) : (
                  <>
                    {loading && sources.length === 0 ? (
                      <div className={shell.empty} aria-busy="true">
                        Loading sources…
                      </div>
                    ) : null}
                    {!loading && !error && sources.length === 0 ? (
                      <div className={shell.empty}>
                        This deployment has no Discovery Catalog sources configured.
                      </div>
                    ) : null}
                    <div className={shell.cardList}>
                      {sources.map((source) => (
                        <DiscoverySourceCard
                          key={source.dirName}
                          source={source}
                          selected={false}
                          onSelect={() => openSource(source.dirName)}
                          onBrowse={() => openSource(source.dirName)}
                          onViewDetails={() => setDetailDir(source.dirName)}
                        />
                      ))}
                    </div>
                  </>
                )}
              </main>
            </>
          )}
        </aside>
      </div>

      {detailSource ? (
        <DiscoverySourceDetailModal
          source={detailSource}
          onBrowse={(source) => {
            setDetailDir(null);
            openSource(source.dirName);
          }}
          onClose={() => setDetailDir(null)}
        />
      ) : null}
    </>
  );
};

export default DiscoveryCatalogDrawer;
