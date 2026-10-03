import React from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";

import { CatalogDetailHeader } from "../../components/catalog/CatalogDetailHeader";
import { useDatasetDetails } from "../../components/datasets/catalog/datasetDetailsContext";
import {
  DISCOVERY_AUTH_LABEL,
  DISCOVERY_CATALOG_REFRESH_EVENT,
  DISCOVERY_PROVIDER_LABEL,
  acquireKey,
  discoveryCatalogApi,
  declaredResourceFor,
  downloadBody,
  isLinkSource,
  isServiceSource,
  isStorageSource,
  unsearchableReason,
  useDiscoverySearch,
  useStorageListing,
  type DiscoverySourceRow,
} from "../../services/discoveryCatalog";
import { DiscoveryLinkForm } from "./DiscoveryLinkForm";
import { DiscoveryResourceRow } from "./DiscoveryResourceRow";
import { DiscoverySourceIcon } from "./DiscoverySourceIcon";
import { useDiscoveryAcquisition } from "./useDiscoveryAcquisition";
import styles from "../catalog/CatalogBrowseLayout.module.css";
import detailStyles from "./DiscoverySourceDetail.module.css";

/**
 * One portal, at `/catalog/discovery/:sourceDir`. **This is where datasets are
 * listed.**
 *
 * The browse page lists sources because a manifest describes a portal; the
 * datasets inside one are discovered live, here. The query lives in the URL so
 * a search is linkable and survives a reload.
 *
 * A storage source (a folder, a bucket, a Hugging Face repo) lists the
 * resources its manifest declares, as its last scan found them. Rescan walks
 * it again.
 */
export const DiscoverySourceDetail: React.FC = () => {
  const navigate = useNavigate();
  const { sourceDir = "" } = useParams<{ sourceDir: string }>();
  const [params, setParams] = useSearchParams();

  const setQuery = (next: string) => {
    const updated = new URLSearchParams(params);
    if (next) updated.set("q", next);
    else updated.delete("q");
    setParams(updated, { replace: true });
  };

  return (
    <DiscoverySourceBody
      sourceDir={sourceDir ? decodeURIComponent(sourceDir) : ""}
      q={params.get("q") ?? ""}
      onQueryChange={setQuery}
      onAllPortals={() => navigate("/catalog/discovery")}
      onViewModel={(modelId) => navigate(`/catalog/models/${encodeURIComponent(modelId)}`)}
    />
  );
};

export interface DiscoverySourceBodyProps {
  /** The source's versioned directory name, `<id>@<major>`. */
  sourceDir: string;
  q: string;
  onQueryChange: (q: string) => void;
  /** Back to every source. */
  onAllPortals: () => void;
  onViewModel: (modelId: string) => void;
  className?: string;
}

/**
 * Everything one source shows, with its query and its way back handed in:
 * the page above keeps them in the URL, the canvas drawer in its own state.
 */
export const DiscoverySourceBody: React.FC<DiscoverySourceBodyProps> = ({
  sourceDir: decoded,
  q,
  onQueryChange: setQuery,
  onAllPortals,
  onViewModel: viewModel,
  className = styles.detailPage,
}) => {
  const [source, setSource] = React.useState<DiscoverySourceRow | null>(null);
  const [loadError, setLoadError] = React.useState<string | null>(null);
  const { openDatasetDetails } = useDatasetDetails();
  // Read again when the roster changes, such as a key saved in API Settings:
  // whether the source can be searched depends on it.
  const [nonce, setNonce] = React.useState(0);

  React.useEffect(() => {
    const reload = () => setNonce((n) => n + 1);
    window.addEventListener(DISCOVERY_CATALOG_REFRESH_EVENT, reload);
    return () => window.removeEventListener(DISCOVERY_CATALOG_REFRESH_EVENT, reload);
  }, []);

  React.useEffect(() => {
    let cancelled = false;
    setLoadError(null);
    discoveryCatalogApi
      .getSource(decoded)
      .then((row) => !cancelled && setSource(row))
      .catch((err: Error) =>
        !cancelled && setLoadError(err.message || "That portal could not be loaded.")
      );
    return () => {
      cancelled = true;
    };
  }, [decoded, nonce]);

  const storage = source ? isStorageSource(source) : false;
  const acquisition = useDiscoveryAcquisition({ isStorage: () => storage, onViewModel: viewModel });

  const blocked = source ? unsearchableReason(source) : null;
  const portalSearch = useDiscoverySearch({
    // Not searched at all while the source is still loading or cannot be
    // searched: asking a portal a question we know it will refuse is a request
    // spent for nothing.
    sourceDir: source && !blocked && !storage ? decoded : undefined,
    q: source && !blocked && !storage ? q : "",
  });
  const listing = useStorageListing(source && !blocked && storage ? decoded : undefined, q);
  const search = storage ? listing : portalSearch;
  const leg = search.data.sources[0];

  if (loadError) {
    return (
      <div className={className}>
        <div className={styles.error}>{loadError}</div>
      </div>
    );
  }
  if (!source) {
    return (
      <div className={className}>
        <div className={styles.empty}>Loading…</div>
      </div>
    );
  }

  return (
    <div className={className}>
      <CatalogDetailHeader
        kind="source"
        title={source.name}
        subtitle={
          <>
            {source.publisher || "Unknown publisher"} ·{" "}
            {DISCOVERY_PROVIDER_LABEL[source.provider] ?? source.provider} ·{" "}
            {DISCOVERY_AUTH_LABEL[source.auth.mode] ?? source.auth.mode}
          </>
        }
        actions={
          <button
            type="button"
            className={styles.publishButton}
            onClick={onAllPortals}
          >
            All portals
          </button>
        }
      >
        <div className={detailStyles.identity}>
          <DiscoverySourceIcon iconUrl={source.iconUrl} name={source.name} size="lg" />
          <div className={detailStyles.identityText}>
            {source.description ? (
              <p className={detailStyles.blurb}>{source.description}</p>
            ) : null}
            {source.homepage ? (
              <a
                className={detailStyles.homepage}
                href={source.homepage}
                target="_blank"
                rel="noreferrer noopener"
              >
                {new URL(source.homepage).host} ↗
              </a>
            ) : null}
          </div>
        </div>
      </CatalogDetailHeader>

      {isLinkSource(source) ? (
        <DiscoveryLinkForm
          source={source}
          acquisition={acquisition}
          onViewDataset={(id) => openDatasetDetails(id)}
        />
      ) : blocked ? (
        <div className={styles.empty}>{blocked}</div>
      ) : (
        <>
          <div className={styles.filterBar}>
            <input
              className={styles.hubSearch}
              type="search"
              placeholder={`Search ${source.name}…`}
              value={q}
              onChange={(e) => setQuery(e.target.value)}
              aria-label={`Search ${source.name}`}
            />
            <span className={styles.filterSpacer} />
            {search.data.totalHint != null ? (
              <span className={detailStyles.count}>
                {search.data.totalHint.toLocaleString()} datasets
              </span>
            ) : null}
            {storage && search.searched && !listing.scanning ? (
              <span className={detailStyles.count}>
                {search.data.resources.length.toLocaleString()}{" "}
                {search.data.resources.length === 1 ? "resource" : "resources"}
              </span>
            ) : null}
            {storage ? (
              <button
                type="button"
                className={detailStyles.rescan}
                disabled={listing.scanning}
                onClick={listing.rescan}
                title="Walk the source again for files added or removed since its last scan"
              >
                {listing.scanning ? "Scanning…" : "Rescan"}
              </button>
            ) : null}
          </div>

          {search.error ? (
            <div className={styles.browseBanner} role="alert">
              <span>{search.error}</span>
            </div>
          ) : null}
          {storage && leg?.status === "failed" ? (
            <div className={styles.browseBanner} role="alert">
              <span>{leg.detail || `${source.name} could not be scanned.`}</span>
            </div>
          ) : null}
          {storage && listing.scanning ? (
            <div className={styles.browseBanner} role="status">
              <span>Scanning {source.name}…</span>
            </div>
          ) : null}
          {storage && !listing.scanning && (search.data.unmatched ?? 0) > 0 ? (
            <p className={detailStyles.unmatched}>
              {search.data.unmatched!.toLocaleString()}{" "}
              {search.data.unmatched === 1 ? "file matches" : "files match"} no resource in this
              source's manifest.
            </p>
          ) : null}
          {storage && search.data.truncated ? (
            <p className={detailStyles.unmatched}>
              This source holds more files than its manifest's limit; only the first ones are
              listed.
            </p>
          ) : null}

          <div className={detailStyles.results}>
            {search.data.resources.map((resource) => (
              <DiscoveryResourceRow
                key={`${resource.sourceId}:${resource.resourceId}`}
                resource={resource}
                iconUrl={source.iconUrl}
                job={acquisition.jobs[acquireKey(decoded, resource.resourceId)]}
                onViewDataset={(id) => openDatasetDetails(id)}
                onViewModel={viewModel}
                onDownload={(r, fmt, parameters, title) =>
                  void acquisition.start(decoded, r.resourceId, downloadBody(source, r, fmt, parameters, title))
                }
                service={isServiceSource(source)}
                onCancel={(r) => acquisition.cancel(decoded, r.resourceId)}
                onDismiss={(r) => acquisition.dismiss(decoded, r.resourceId)}
                storage={
                  storage
                    ? {
                        dirName: decoded,
                        declared: declaredResourceFor(source, resource.resourceId),
                        onAdd: (r, body) => void acquisition.start(decoded, r.resourceId, body),
                      }
                    : undefined
                }
              />
            ))}
          </div>

          {!search.loading &&
          search.searched &&
          search.data.resources.length === 0 &&
          !(storage && (leg?.status === "failed" || listing.scanning)) ? (
            <div className={styles.empty}>
              {storage
                ? q
                  ? `Nothing in ${source.name} matches “${q}”.`
                  : `No files in ${source.name} match its manifest's resources.`
                : `Nothing on this portal matches “${q}”.`}
            </div>
          ) : null}
          {!search.searched && !search.loading ? (
            <div className={styles.empty}>
              Search {source.name} to see what it holds.
            </div>
          ) : null}
        </>
      )}

    </div>
  );
};

export default DiscoverySourceDetail;
