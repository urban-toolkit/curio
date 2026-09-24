import React from "react";
import { useNavigate, useParams } from "react-router-dom";

import { CatalogDetailHeader } from "../../components/catalog/CatalogDetailHeader";
import {
  LAKE_AUTH_LABEL,
  LAKE_PROVIDER_LABEL,
  dataLakeCatalogApi,
  unsearchableReason,
  type LakeSourceRow,
} from "../../services/dataLakeCatalog";
import { LakeSourceIcon } from "./LakeSourceIcon";
import styles from "../catalog/CatalogBrowseLayout.module.css";
import detailStyles from "./DataLakeSourceDetail.module.css";

/**
 * One portal, at `/catalog/lakes/:sourceDir`.
 *
 * This is where searching a portal will happen: the search box, the resource
 * rows and the download button arrive with the providers. Until they do, the
 * page identifies the source and says plainly that browsing is not wired yet,
 * rather than rendering a search box that silently returns nothing. A control
 * that looks functional and is not is worse than no control.
 */
export const DataLakeSourceDetail: React.FC = () => {
  const navigate = useNavigate();
  const { sourceDir = "" } = useParams<{ sourceDir: string }>();
  const decoded = sourceDir ? decodeURIComponent(sourceDir) : "";
  const [source, setSource] = React.useState<LakeSourceRow | null>(null);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    let cancelled = false;
    setError(null);
    dataLakeCatalogApi
      .getSource(decoded)
      .then((row) => {
        if (!cancelled) setSource(row);
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message || "That portal could not be loaded.");
      });
    return () => {
      cancelled = true;
    };
  }, [decoded]);

  if (error) {
    return (
      <div className={styles.detailPage}>
        <div className={styles.error}>{error}</div>
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

  const blocked = unsearchableReason(source);

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
          <p className={detailStyles.blurb}>{source.description}</p>
        </div>
      </CatalogDetailHeader>

      <div className={styles.empty}>
        {blocked ??
          "Searching this portal is not wired up yet - the connectors land in the next change."}
      </div>
    </div>
  );
};

export default DataLakeSourceDetail;
