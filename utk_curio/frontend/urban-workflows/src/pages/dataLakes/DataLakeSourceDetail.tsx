import React from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";

import { CatalogDetailHeader } from "../../components/catalog/CatalogDetailHeader";
import {
  LAKE_AUTH_LABEL,
  LAKE_PROVIDER_LABEL,
  dataLakeCatalogApi,
  unsearchableReason,
  useLakeSearch,
  type LakeSourceRow,
} from "../../services/dataLakeCatalog";
import { DataLakeResourceRow } from "./DataLakeResourceRow";
import { LakeSourceIcon } from "./LakeSourceIcon";
import styles from "../catalog/CatalogBrowseLayout.module.css";
import detailStyles from "./DataLakeSourceDetail.module.css";

/**
 * One portal, at `/catalog/lakes/:sourceDir`. **This is where datasets are
 * listed.**
 *
 * The browse page lists sources because a manifest describes a portal; the
 * datasets inside one are discovered live, here. The query lives in the URL so
 * a search is linkable and survives a reload.
 */
export const DataLakeSourceDetail: React.FC = () => {
  const navigate = useNavigate();
  const { sourceDir = "" } = useParams<{ sourceDir: string }>();
  const decoded = sourceDir ? decodeURIComponent(sourceDir) : "";
  const [params, setParams] = useSearchParams();
  const q = params.get("q") ?? "";

  const [source, setSource] = React.useState<LakeSourceRow | null>(null);
  const [loadError, setLoadError] = React.useState<string | null>(null);

  React.useEffect(() => {
    let cancelled = false;
    setLoadError(null);
    dataLakeCatalogApi
      .getSource(decoded)
      .then((row) => !cancelled && setSource(row))
      .catch((err: Error) =>
        !cancelled && setLoadError(err.message || "That portal could not be loaded.")
      );
    return () => {
      cancelled = true;
    };
  }, [decoded]);

  const blocked = source ? unsearchableReason(source) : null;
  const search = useLakeSearch({
    // Not searched at all while the source is still loading or cannot be
    // searched: asking a portal a question we know it will refuse is a request
    // spent for nothing.
    sourceDir: source && !blocked ? decoded : undefined,
    q: source && !blocked ? q : "",
  });

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
        kind="lake"
        title={source.name}
        subtitle={
          <>
            {source.publisher || "Unknown publisher"} ·{" "}
            {LAKE_PROVIDER_LABEL[source.provider] ?? source.provider} ·{" "}
            {LAKE_AUTH_LABEL[source.auth.mode] ?? source.auth.mode}
          </>
        }
        actions={
          <button
            type="button"
            className={styles.publishButton}
            onClick={() => navigate("/catalog/lakes")}
          >
            All portals
          </button>
        }
      >
        <div className={detailStyles.identity}>
          <LakeSourceIcon iconUrl={source.iconUrl} name={source.name} size="lg" />
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

      {blocked ? (
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
          </div>

          {search.error ? (
            <div className={styles.browseBanner} role="alert">
              <span>{search.error}</span>
            </div>
          ) : null}

          <div className={detailStyles.results}>
            {search.data.resources.map((resource) => (
              <DataLakeResourceRow
                key={`${resource.sourceId}:${resource.resourceId}`}
                resource={resource}
                iconUrl={source.iconUrl}
              />
            ))}
          </div>

          {!search.loading && search.searched && search.data.resources.length === 0 ? (
            <div className={styles.empty}>Nothing on this portal matches “{q}”.</div>
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

export default DataLakeSourceDetail;
