import React, { useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import { CatalogKindIcon } from "../../components/catalog/CatalogKindVisuals";
import { CardContextMenu } from "../../components/catalog/CardContextMenu";
import {
  lakeSourceCardActions,
  type CatalogCardActionId,
} from "../../components/catalog/catalogCardActions";
import { DatasetDetailModal } from "../../components/datasets/catalog/DatasetDetailModal";
import {
  acquireKey,
  notifyDatasetCatalogRefresh,
  partialFailureMessage,
  unsearchableReason,
  useLakeAcquire,
  useLakeCatalog,
  useLakeSearch,
  type LakeAuthMode,
  type LakeProviderType,
  type LakeSourceRow,
} from "../../services/dataLakeCatalog";
import { AUTH_FILTERS, PROVIDER_FILTERS } from "./dataLakeBrowseConstants";
import { DataLakeSourceCard } from "./DataLakeSourceCard";
import { DataLakeResourceRow } from "./DataLakeResourceRow";
import { DataLakeCatalogBrowseDrawer } from "./DataLakeCatalogBrowseDrawer";
import { DataLakeSourceDetailModal } from "./DataLakeSourceDetailModal";
import browseStyles from "../catalog/CatalogBrowseLayout.module.css";
import resultStyles from "./DataLakeCatalogBrowse.module.css";

type SortMode = "name" | "provider";

/**
 * The account-scope Data Lake Catalog under `/catalog/lakes`.
 *
 * The fourth peer of `/catalog/nodes`, `/catalog/data` and `/catalog/agents`:
 * same three-column grid from `CatalogBrowseLayout.module.css`, same header
 * anatomy (crumb, kind icon + h1 + count, intro, search), same filter bar, same
 * card grid, same right-hand detail drawer.
 *
 * What differs is the UNIT. The other three list things you can put on a
 * canvas; this lists *portals*, and the datasets inside one are discovered
 * live on its own page. So a card's action is "browse", not "add" - nothing
 * here is installed, and a source is not droppable.
 *
 * Every route this page calls is served from disk, so it renders in full on a
 * deployment with no outbound network at all.
 */
export const DataLakeCatalogBrowse: React.FC = () => {
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
  const [provider, setProvider] = useState<LakeProviderType | "">("");
  const [auth, setAuth] = useState<LakeAuthMode | "">("");
  const [sort, setSort] = useState<SortMode>("name");
  const [selectedDir, setSelectedDir] = useState<string | null>(null);
  // Its own state, not `selectedDir`: the card click drives the drawer and
  // "View details" opens the modal. Sharing one setter is the bug (#189) that
  // made the Agent page's "View details" a no-op on an already-selected card.
  const [detailDir, setDetailDir] = useState<string | null>(null);
  const [contextMenu, setContextMenu] = useState<{
    x: number;
    y: number;
    source: LakeSourceRow;
  } | null>(null);
  const [drawerSlotOpen, setDrawerSlotOpen] = useState(false);
  // A downloaded resource opens in the Data Catalog's details modal, over this
  // page, rather than sending you to the dataset's own route.
  const [detailDatasetId, setDetailDatasetId] = useState<string | null>(null);

  // The roster is always loaded: the rail counts and the source names shown
  // beside federated rows both come from it, and it is disk-backed and cheap.
  // It is NOT filtered by the search box - that text is a question for the
  // portals, not for the roster.
  const { data, loading, error, reload } = useLakeCatalog({ provider, auth });

  // Two modes in one page, switched by whether the search box has anything in
  // it. Idle lists the portals; a query fans out across them.
  const searching = search.trim().length > 0;
  const results = useLakeSearch({ q: searching ? search : "", provider });
  const acquisition = useLakeAcquire(() => notifyDatasetCatalogRefresh());

  const sources = useMemo(() => {
    const rows = [...data.sources];
    if (sort === "provider") {
      rows.sort((a, b) => a.provider.localeCompare(b.provider) || a.name.localeCompare(b.name));
    }
    return rows;
  }, [data.sources, sort]);

  const selected = useMemo(
    () => sources.find((s) => s.dirName === selectedDir) ?? null,
    [sources, selectedDir]
  );
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

  const openSource = (source: LakeSourceRow) =>
    navigate(`/catalog/lakes/${encodeURIComponent(source.dirName)}`);

  const runSourceAction = (id: CatalogCardActionId, source: LakeSourceRow) => {
    switch (id) {
      case "browse-datasets":
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
      <aside className={browseStyles.categoryRail}>
        <p className={browseStyles.railLabel}>By provider</p>
        <button
          className={`${browseStyles.railButton} ${provider === "" ? browseStyles.railButtonActive : ""}`}
          type="button"
          onClick={() => setProvider("")}
        >
          <span>All portals</span>
          <span className={browseStyles.railCountBadge}>{total}</span>
        </button>
        {PROVIDER_FILTERS.map(({ value, label }) => (
          <button
            key={value}
            className={`${browseStyles.railButton} ${provider === value ? browseStyles.railButtonActive : ""}`}
            type="button"
            onClick={() => setProvider((prev) => (prev === value ? "" : value))}
          >
            <span>{label}</span>
            <span className={browseStyles.railCount}>{providerCounts[value] ?? 0}</span>
          </button>
        ))}

        <div className={browseStyles.railDivider} />
        <p className={browseStyles.railLabel}>By access</p>
        {AUTH_FILTERS.map(({ value, label }) => (
          <button
            key={value}
            className={`${browseStyles.railButton} ${auth === value ? browseStyles.railButtonActive : ""}`}
            type="button"
            onClick={() => setAuth((prev) => (prev === value ? "" : value))}
          >
            <span>{label}</span>
            <span className={browseStyles.railCount}>{authCounts[value] ?? 0}</span>
          </button>
        ))}
      </aside>

      <main className={browseStyles.browseMain}>
        <section className={browseStyles.browseHeader}>
          <p className={browseStyles.crumb}>Data Lake Catalog</p>
          <div className={browseStyles.titleRow}>
            <CatalogKindIcon kind="lake" size="md" title="Data lake catalog" />
            <h1>Data Lake Catalog</h1>
            <span className={browseStyles.titleCount}>
              {searching ? results.data.resources.length : sources.length}
            </span>
          </div>
          <p className={browseStyles.pageIntro}>
            Data portals and lakes this deployment can reach. Type to search{" "}
            <strong>all of them at once</strong>, or open one to browse it. What you
            download lands in your <strong>Data Catalog</strong> and behaves like any
            other dataset.
          </p>
          <div className={browseStyles.headerTools}>
            <input
              className={browseStyles.hubSearch}
              type="search"
              placeholder="Search every portal…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              aria-label="Search every portal"
            />
          </div>
        </section>

        <div className={browseStyles.filterBar}>
          <button
            className={`${browseStyles.chip} ${provider === "" && auth === "" ? browseStyles.chipActive : ""}`}
            type="button"
            onClick={() => {
              setProvider("");
              setAuth("");
            }}
          >
            All
          </button>
          {PROVIDER_FILTERS.map(({ value, label }) => (
            <button
              key={value}
              className={`${browseStyles.chip} ${provider === value ? browseStyles.chipActive : ""}`}
              type="button"
              onClick={() => setProvider((prev) => (prev === value ? "" : value))}
            >
              {/* One dot colour for every portal: on this page every card IS a
                  portal, so a per-provider hue would carry no information. See
                  --curio-kind-lake-fg. */}
              <span className={`${browseStyles.chipDot} ${browseStyles.chipDotDefault}`} />
              {label}
            </button>
          ))}
          <span className={browseStyles.filterSpacer} />
          <select
            className={browseStyles.sortSelect}
            value={sort}
            onChange={(e) => setSort(e.target.value as SortMode)}
          >
            <option value="name">Sort: Name</option>
            <option value="provider">Sort: Provider</option>
          </select>
        </div>

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
            {results.data.resources.map((resource) => (
              <DataLakeResourceRow
                key={`${resource.sourceId}:${resource.resourceId}`}
                resource={resource}
                showSource
                iconUrl={sourcesById.get(resource.sourceId)?.iconUrl ?? null}
                job={
                  acquisition.jobs[
                    acquireKey(
                      sourcesById.get(resource.sourceId)?.dirName ?? resource.sourceId,
                      resource.resourceId
                    )
                  ]
                }
                onViewDataset={setDetailDatasetId}
                onDownload={(r, fmt) => {
                  // A federated row carries the source ID; the API wants the
                  // versioned dirName, which only the roster knows.
                  const dir = sourcesById.get(r.sourceId)?.dirName;
                  // ``title``: see DataLakeSourceDetail - without it the
                  // dataset is named after the remote file, not the resource.
                  if (dir)
                    void acquisition.start(dir, r.resourceId, {
                      format: fmt,
                      title: r.name,
                    });
                }}
                onCancel={(r) => {
                  const dir = sourcesById.get(r.sourceId)?.dirName;
                  if (dir) acquisition.cancel(dir, r.resourceId);
                }}
                onDismiss={(r) => {
                  const dir = sourcesById.get(r.sourceId)?.dirName;
                  if (dir) acquisition.dismiss(dir, r.resourceId);
                }}
              />
            ))}
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
              : "This deployment has no data lake sources configured."}
          </div>
        ) : (
          <div
            className={[browseStyles.cardGrid, loading ? browseStyles.cardGridRefreshing : ""]
              .filter(Boolean)
              .join(" ")}
          >
            {sources.map((source) => (
              <DataLakeSourceCard
                key={source.dirName}
                source={source}
                selected={selectedDir === source.dirName}
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

      <DataLakeCatalogBrowseDrawer
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
          ariaLabel="Data lake actions"
          items={lakeSourceCardActions({
            browsable: unsearchableReason(contextMenu.source) == null,
          })}
          onSelect={(id) => runSourceAction(id as CatalogCardActionId, contextMenu.source)}
          onDismiss={() => setContextMenu(null)}
        />
      ) : null}

      {detailSource ? (
        <DataLakeSourceDetailModal
          source={detailSource}
          onBrowse={openSource}
          onClose={() => setDetailDir(null)}
        />
      ) : null}

      {detailDatasetId ? (
        <DatasetDetailModal
          datasetId={detailDatasetId}
          onClose={() => setDetailDatasetId(null)}
        />
      ) : null}
    </div>
  );
};

export default DataLakeCatalogBrowse;
