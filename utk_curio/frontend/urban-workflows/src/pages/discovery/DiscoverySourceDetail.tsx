import React from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";

import { CatalogDetailHeader } from "../../components/catalog/CatalogDetailHeader";
import {
  useDatasetDetails,
  viewDatasetDetailsToast,
} from "../../components/datasets/catalog/datasetDetailsContext";
import { useToastContext } from "../../providers/ToastProvider";
import {
  DISCOVERY_AUTH_LABEL,
  DISCOVERY_PROVIDER_LABEL,
  acquireKey,
  discoveryCatalogApi,
  declaredResourceFor,
  isLinkSource,
  isStorageSource,
  notifyDatasetCatalogRefresh,
  unsearchableReason,
  useDiscoveryAcquire,
  useDiscoverySearch,
  useStorageListing,
  type DiscoverySourceRow,
} from "../../services/discoveryCatalog";
import { DiscoveryLinkForm } from "./DiscoveryLinkForm";
import { DiscoveryResourceRow } from "./DiscoveryResourceRow";
import { DiscoverySourceIcon } from "./DiscoverySourceIcon";
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
  const decoded = sourceDir ? decodeURIComponent(sourceDir) : "";
  const [params, setParams] = useSearchParams();
  const q = params.get("q") ?? "";

  const [source, setSource] = React.useState<DiscoverySourceRow | null>(null);
  const [loadError, setLoadError] = React.useState<string | null>(null);
  // The same details modal the Data Catalog opens, over this page, so the
  // search that found the resource is still there when it closes.
  const { openDatasetDetails } = useDatasetDetails();
  const { showToast } = useToastContext();

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
  }, [decoded]);

  const storage = source ? isStorageSource(source) : false;

  // A finished download is a new Data Catalog dataset, so every surface that
  // lists datasets - in this tab and in any other - has to be told. Skipping
  // this is how the download succeeds and the dataset appears to be missing.
  const acquisition = useDiscoveryAcquire((job) => {
    notifyDatasetCatalogRefresh();
    // Reported like an import into the Data Catalog, which is what it is.
    if (job.datasetId) {
      const title = typeof job.dataset?.title === "string" ? job.dataset.title : "The dataset";
      if (job.alreadyPresent && job.unchanged) {
        showToast(
          `Nothing has changed in ${title} since it was added.`,
          "info",
          viewDatasetDetailsToast(openDatasetDetails, job.datasetId),
        );
        return;
      }
      showToast(
        `${storage ? "Added" : "Downloaded"} ${title} to your Data Catalog.`,
        "success",
        viewDatasetDetailsToast(openDatasetDetails, job.datasetId),
      );
    }
  });

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
      <div className={styles.detailPage}>
        <div className={styles.error}>{loadError}</div>
      </div>
    );
  }
  if (!source) {
    return (
      <div className={styles.detailPage}>
        <div className={styles.empty}>Loading…</div>
      </div>
    );
  }

  const setQuery = (next: string) => {
    const updated = new URLSearchParams(params);
    if (next) updated.set("q", next);
    else updated.delete("q");
    setParams(updated, { replace: true });
  };

  return (
    <div className={styles.detailPage}>
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
            onClick={() => navigate("/catalog/discovery")}
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
                onDownload={(r, fmt, parameters) =>
                  // The portal's own title, or the dataset lands named after
                  // the remote FILE - "ijzp-q8t2.csv" rather than "Crimes -
                  // 2001 to Present", which is unreadable in the Data Catalog
                  // and cannot be searched for by the name it was found under.
                  void acquisition.start(decoded, r.resourceId, {
                    format: fmt,
                    title: r.name,
                    ...(parameters ? { parameters } : {}),
                  })
                }
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
