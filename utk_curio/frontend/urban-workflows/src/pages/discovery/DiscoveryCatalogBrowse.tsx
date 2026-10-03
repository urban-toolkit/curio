import React, { useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import { CardContextMenu } from "../../components/catalog/CardContextMenu";
import { CatalogPageHeader } from "../catalog/CatalogPageHeader";
import { CatalogRail } from "../catalog/CatalogRail";
import {
  discoverySourceCardActions,
  type CatalogCardActionId,
} from "../../components/catalog/catalogCardActions";
import { useDatasetDetails } from "../../components/datasets/catalog/datasetDetailsContext";
import {
  isStorageSource,
  partialFailureMessage,
  scanningMessage,
  isLinkSource,
  unsearchableReason,
  useDiscoveryCatalog,
  useDiscoverySearch,
  type DiscoveryAuthMode,
  type DiscoveryProviderType,
  type DiscoverySourceRow,
} from "../../services/discoveryCatalog";
import { AUTH_FILTERS, PROVIDER_FILTERS } from "./discoveryBrowseConstants";
import { DiscoverySourceCard } from "./DiscoverySourceCard";
import { DiscoveryFederatedRows } from "./DiscoveryFederatedRows";
import { DiscoveryCatalogBrowseDrawer } from "./DiscoveryCatalogBrowseDrawer";
import { DiscoverySourceDetailModal } from "./DiscoverySourceDetailModal";
import { useDiscoveryAcquisition } from "./useDiscoveryAcquisition";
import browseStyles from "../catalog/CatalogBrowseLayout.module.css";
import resultStyles from "./DiscoveryCatalogBrowse.module.css";

type SortMode = "name" | "provider";

/**
 * The account-scope Discovery Catalog under `/catalog/discovery`.
 *
 * The fourth peer of `/catalog/nodes`, `/catalog/data` and `/catalog/agents`:
 * same three-column grid from `CatalogBrowseLayout.module.css`, same rail
 * (`CatalogRail`), same header (`CatalogPageHeader`: kind icon + h1 + count,
 * then search), same card grid, same right-hand detail drawer.
 *
 * What differs is the UNIT. The other three list things you can put on a
 * canvas; this lists *portals*, and the datasets inside one are discovered
 * live on its own page. So a card's action is "browse", not "add" - nothing
 * here is installed, and a source is not droppable.
 *
 * Every route this page calls is served from disk, so it renders in full on a
 * deployment with no outbound network at all.
 */
export const DiscoveryCatalogBrowse: React.FC = () => {
  const navigate = useNavigate();
  // The query lives in the URL so a federated search is linkable and survives
  // a reload - the same reason the source page does it.
  const [params, setParams] = useSearchParams();
  const search = params.get("q") ?? "";
  const setSearch = (next: string) => {
    const updated = new URLSearchParams(params);
    if (next) updated.set("q", next);
    else updated.delete("q");
    setParams(updated, { replace: true });
  };
  const [provider, setProvider] = useState<DiscoveryProviderType | "">("");
  const [auth, setAuth] = useState<DiscoveryAuthMode | "">("");
  const [sort, setSort] = useState<SortMode>("name");
  // The peers' tri-state: undefined follows the first card, so the drawer is
  // open on arrival as it is on the other three pages; null is the user having
  // closed it.
  const [selectedDir, setSelectedDir] = useState<string | null | undefined>(undefined);
  // Its own state, not `selectedDir`: the card click drives the drawer and
  // "View details" opens the modal. Sharing one setter is the bug (#189) that
  // made the Agent page's "View details" a no-op on an already-selected card.
  const [detailDir, setDetailDir] = useState<string | null>(null);
  const [contextMenu, setContextMenu] = useState<{
    x: number;
    y: number;
    source: DiscoverySourceRow;
  } | null>(null);
  const [drawerSlotOpen, setDrawerSlotOpen] = useState(false);
  // A downloaded resource opens in the Data Catalog's details modal, over this
  // page, rather than sending you to the dataset's own route.
  const { openDatasetDetails } = useDatasetDetails();

  // The roster is always loaded: the rail counts and the source names shown
  // beside federated rows both come from it, and it is disk-backed and cheap.
  // It is NOT filtered by the search box - that text is a question for the
  // portals, not for the roster.
  const { data, loading, error, reload } = useDiscoveryCatalog({ provider, auth });

  // Two modes in one page, switched by whether the search box has anything in
  // it. Idle lists the portals; a query fans out across them, narrowed by the
  // rail's filters as the cards are, so every row's source is on the page.
  const searching = search.trim().length > 0;
  const results = useDiscoverySearch({ q: searching ? search : "", provider, auth });
  const viewModel = (modelId: string) => navigate(`/catalog/models/${encodeURIComponent(modelId)}`);
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

  const selected = useMemo(() => {
    // A federated search replaces the cards, so there is no card for the
    // drawer to describe until the search box is cleared.
    if (searching || selectedDir === null) return null;
    if (selectedDir !== undefined) {
      return sources.find((s) => s.dirName === selectedDir) ?? sources[0] ?? null;
    }
    return sources[0] ?? null;
  }, [searching, sources, selectedDir]);
  const detailSource = useMemo(
    () => (detailDir ? sources.find((s) => s.dirName === detailDir) ?? null : null),
    [sources, detailDir]
  );

  const sourcesById = useMemo(
    () => new Map(data.sources.map((s) => [s.sourceId, s])),
    [data.sources]
  );
  const partialFailure = useMemo(
    () =>
      partialFailureMessage(
        results.data.sources,
        (id) => sourcesById.get(id)?.name ?? ""
      ),
    [results.data.sources, sourcesById]
  );
  const stillScanning = useMemo(
    () => scanningMessage(results.data.sources, (id) => sourcesById.get(id)?.name ?? ""),
    [results.data.sources, sourcesById]
  );

  const openSource = (source: DiscoverySourceRow) =>
    navigate(`/catalog/discovery/${encodeURIComponent(source.dirName)}`);

  const runSourceAction = (id: CatalogCardActionId, source: DiscoverySourceRow) => {
    switch (id) {
      case "browse-datasets":
      case "add-by-link":
        openSource(source);
        return;
      case "view-details":
        setDetailDir(source.dirName);
        return;
      // A source is never added to or removed from anything.
      default:
        return;
    }
  };

  const providerCounts = data.facets.provider ?? {};
  const authCounts = data.facets.auth ?? {};
  const total = Object.values(providerCounts).reduce((a, b) => a + b, 0);

  return (
    <div
      className={[browseStyles.page, drawerSlotOpen ? browseStyles.pageWithDrawer : ""]
        .filter(Boolean)
        .join(" ")}
    >
      <CatalogRail
        ariaLabel="Filter portals"
        all={{
          label: "All portals",
          count: total,
          active: provider === "" && auth === "",
          onClick: () => {
            setProvider("");
            setAuth("");
          },
        }}
        sections={[
          {
            key: "provider",
            label: "By provider",
            entries: PROVIDER_FILTERS.map(({ value, label }) => ({
              value,
              label,
              count: providerCounts[value] ?? 0,
              active: provider === value,
              onClick: () => setProvider((prev) => (prev === value ? "" : value)),
            })),
          },
          {
            key: "access",
            label: "By access",
            entries: AUTH_FILTERS.map(({ value, label }) => ({
              value,
              label,
              count: authCounts[value] ?? 0,
              active: auth === value,
              onClick: () => setAuth((prev) => (prev === value ? "" : value)),
            })),
          },
        ]}
      />

      <main className={browseStyles.browseMain}>
        <CatalogPageHeader
          kind="source"
          iconTitle="Discovery Catalog"
          title="Discovery Catalog"
          count={searching ? results.data.resources.length : sources.length}
          intro={
            <>
              Data portals and storage this deployment can reach. Type to search{" "}
              <strong>all of them at once</strong>, or open one to browse it. What you
              download lands in your <strong>Data Catalog</strong> and behaves like any
              other dataset.
            </>
          }
          viewTools={
            <select
              className={browseStyles.sortSelect}
              aria-label="Sort portals"
              value={sort}
              onChange={(e) => setSort(e.target.value as SortMode)}
            >
              <option value="name">Sort: Name</option>
              <option value="provider">Sort: Provider</option>
            </select>
          }
        >
          <input
            className={browseStyles.hubSearch}
            type="search"
            placeholder="Search every portal…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            aria-label="Search every portal"
          />
        </CatalogPageHeader>

        {error ? (
          <div className={browseStyles.browseBanner} role="alert">
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

        {partialFailure ? (
          <div className={browseStyles.browseBanner} role="status">
            <span>{partialFailure}</span>
          </div>
        ) : null}
        {searching && stillScanning ? (
          <div className={browseStyles.browseBanner} role="status">
            <span>{stillScanning}</span>
          </div>
        ) : null}

        {searching ? (
          /* Federated results replace the card grid. Each row is tagged with
             the portal it came from, because on this page that is not implied. */
          <div
            className={[
              browseStyles.cardGrid,
              resultStyles.resultList,
              results.loading ? browseStyles.cardGridRefreshing : "",
            ]
              .filter(Boolean)
              .join(" ")}
          >
            <DiscoveryFederatedRows
              resources={results.data.resources}
              sourcesById={sourcesById}
              acquisition={acquisition}
              onViewDataset={(id) => openDatasetDetails(id)}
              onViewModel={viewModel}
            />
            {!results.loading && results.searched && results.data.resources.length === 0 ? (
              <div className={browseStyles.empty}>
                No portal returned anything for “{search}”.
              </div>
            ) : null}
          </div>
        ) : !loading && sources.length === 0 ? (
          <div className={browseStyles.empty}>
            {provider || auth
              ? "No portal matches those filters."
              : "This deployment has no Discovery Catalog sources configured."}
          </div>
        ) : (
          <div
            className={[browseStyles.cardGrid, loading ? browseStyles.cardGridRefreshing : ""]
              .filter(Boolean)
              .join(" ")}
          >
            {sources.map((source) => (
              <DiscoverySourceCard
                key={source.dirName}
                source={source}
                selected={selected?.dirName === source.dirName}
                onSelect={() => setSelectedDir(source.dirName)}
                onBrowse={() => openSource(source)}
                onViewDetails={() => setDetailDir(source.dirName)}
                onContextMenu={(e) => {
                  e.preventDefault();
                  // Select first, as the peer pages do: the menu acts on this
                  // source, so the drawer should not describe another one.
                  setSelectedDir(source.dirName);
                  setContextMenu({ x: e.clientX, y: e.clientY, source });
                }}
              />
            ))}
          </div>
        )}
      </main>

      <DiscoveryCatalogBrowseDrawer
        source={selected}
        onBrowse={openSource}
        onViewDetails={(source) => setDetailDir(source.dirName)}
        onClose={() => setSelectedDir(null)}
        onLayoutChange={setDrawerSlotOpen}
      />

      {contextMenu ? (
        <CardContextMenu
          x={contextMenu.x}
          y={contextMenu.y}
          ariaLabel="Source actions"
          items={discoverySourceCardActions({
            browsable: unsearchableReason(contextMenu.source) == null,
            byLink: isLinkSource(contextMenu.source),
          })}
          onSelect={(id) => runSourceAction(id as CatalogCardActionId, contextMenu.source)}
          onDismiss={() => setContextMenu(null)}
        />
      ) : null}

      {detailSource ? (
        <DiscoverySourceDetailModal
          source={detailSource}
          onBrowse={openSource}
          onClose={() => setDetailDir(null)}
        />
      ) : null}

    </div>
  );
};

export default DiscoveryCatalogBrowse;
