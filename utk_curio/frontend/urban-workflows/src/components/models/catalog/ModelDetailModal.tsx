import React, { useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";

import ModalShell from "../../ModalShell";
import { CatalogDetailHeader } from "../../catalog/CatalogDetailHeader";
import { DetailLink } from "../../datasets/catalog/DetailLink";
import { LEAVE_DATAFLOW, useLeaveGuard } from "../../../hook/useLeaveGuard";
import {
  MODEL_RUNTIME_LABEL,
  modelCatalogApi,
  type ModelRow,
} from "../../../services/modelCatalog";
import { modelInfoRows } from "./modelFacts";
import styles from "../../agents/catalog/AgentDetailModal.module.css";
import browseStyles from "../../../pages/catalog/CatalogBrowseLayout.module.css";

export interface ModelDetailModalProps {
  modelId: string;
  /** The listing's row, shown at once while the model's own GET answers. */
  fallbackModel?: ModelRow | null;
  /** The dataflow behind the modal has changes not yet saved, so a link that
   *  leaves it asks first. Set only on the canvas. */
  unsavedChanges?: boolean;
  onClose: () => void;
}

function samePath(a: string, b: string): boolean {
  const decode = (p: string) => {
    try {
      return decodeURIComponent(p);
    } catch {
      return p;
    }
  };
  return decode(a) === decode(b);
}

/**
 * "View details" for one model, the Model Catalog's answer to
 * `DiscoverySourceDetailModal` and `DatasetDetailModal`.
 *
 * Opened from the browse page, its deep link, the canvas drawer and the
 * palette, so the same model reads the same everywhere. The rows come from
 * `modelFacts`, the ones the drawers render.
 */
export const ModelDetailModal: React.FC<ModelDetailModalProps> = ({
  modelId,
  fallbackModel = null,
  unsavedChanges = false,
  onClose,
}) => {
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const { leave, dialog: leaveDialog } = useLeaveGuard(unsavedChanges, LEAVE_DATAFLOW, {
    layer: "overlay",
  });
  const [model, setModel] = useState<ModelRow | null>(fallbackModel);
  const [loading, setLoading] = useState(!fallbackModel);
  const [error, setError] = useState<string | null>(null);
  const [license, setLicense] = useState<string | null>(null);
  const [licenseLoading, setLicenseLoading] = useState(false);
  const [licenseError, setLicenseError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(!fallbackModel);
    setError(null);
    void modelCatalogApi
      .getModel(modelId)
      .then((row) => {
        if (!cancelled) setModel(row);
      })
      .catch((err) => {
        if (cancelled) return;
        // A stale link: say so rather than echoing the server's 404 text.
        if ((err as { status?: number } | null)?.status === 404 && !fallbackModel) {
          setModel(null);
          return;
        }
        setError((err as Error)?.message || "Could not load this model.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // The fallback is only the first paint; a new one is not a reason to refetch.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [modelId]);

  const showLicense = async () => {
    if (licenseLoading) return;
    setLicenseLoading(true);
    setLicenseError(null);
    try {
      setLicense(await modelCatalogApi.getLicense(modelId));
    } catch (err) {
      setLicenseError(err instanceof Error && err.message ? err.message : "Could not load the license.");
    } finally {
      setLicenseLoading(false);
    }
  };

  // A link out (the portal a download came from) opens a page, so the modal
  // closes on the way, and leaving a dataflow with unsaved changes asks first,
  // as the dataset details do.
  const followLink = (to: string) => {
    if (samePath(to, pathname)) {
      onClose();
      return;
    }
    leave(() => {
      onClose();
      navigate(to);
    });
  };

  const source = model?.discoverySource;

  return (
    <ModalShell onClose={onClose} size="xlarge" layer="overlay" label="Model details">
      {model ? (
        <>
          <CatalogDetailHeader
            kind="model"
            title={model.name}
            subtitle={
              <>
                {model.publisher || "Unknown publisher"} ·{" "}
                {MODEL_RUNTIME_LABEL[model.runtime] ?? model.runtime} · v{model.version}
              </>
            }
          />

          <div className={styles.body} data-model-id={model.id}>
            {model.description ? <p className={styles.purpose}>{model.description}</p> : null}
            {error ? (
              <p className={styles.purpose} role="alert">
                {error}
              </p>
            ) : null}

            <section className={styles.section}>
              <h3 className={styles.sectionLabel}>Model</h3>
              <dl className={styles.infoGrid}>
                {[...modelInfoRows(model), { label: "Identifier", value: model.id }].map(
                  ({ label, value }) => (
                    <React.Fragment key={label}>
                      <dt className={styles.infoLabel}>{label}</dt>
                      <dd className={styles.infoValue}>{value}</dd>
                    </React.Fragment>
                  ),
                )}
              </dl>
            </section>

            {model.labels.length > 0 ? (
              <section className={styles.section}>
                <h3 className={styles.sectionLabel}>Labels ({model.labelCount})</h3>
                {/* Plain chips, the drawer's tag treatment: a label is a name,
                    and no chip in the catalogs is tinted (#193). */}
                <div className={browseStyles.drawerTagsRow} data-curio-model-labels="true">
                  {model.labels.map((label) => (
                    <span key={label} className={browseStyles.drawerTag}>
                      {label}
                    </span>
                  ))}
                </div>
              </section>
            ) : null}

            <section className={styles.section}>
              <h3 className={styles.sectionLabel}>License</h3>
              <p className={styles.purpose}>
                {model.license || "Unknown"}
                {model.hasLicenseText && license == null ? (
                  <>
                    {" "}
                    <button
                      type="button"
                      className={styles.inlineLink}
                      disabled={licenseLoading}
                      onClick={() => void showLicense()}
                    >
                      {licenseLoading ? "Loading…" : "View license"}
                    </button>
                  </>
                ) : null}
              </p>
              {licenseError ? (
                <p className={styles.purpose} role="alert">
                  {licenseError}
                </p>
              ) : null}
              {license != null ? (
                <pre className={styles.promptText} data-curio-model-license="true">
                  {license}
                </pre>
              ) : null}
            </section>

            {source?.sourceId ? (
              <section className={styles.section}>
                <h3 className={styles.sectionLabel}>Downloaded from</h3>
                <dl className={styles.infoGrid}>
                  <dt className={styles.infoLabel}>Source</dt>
                  <dd className={styles.infoValue}>
                    <DetailLink
                      to={`/catalog/discovery/${encodeURIComponent(source.sourceId)}`}
                      onFollow={followLink}
                    >
                      {source.sourceName || source.sourceId}
                    </DetailLink>
                  </dd>
                  {source.resourceId ? (
                    <>
                      <dt className={styles.infoLabel}>Resource</dt>
                      <dd className={styles.infoValue}>{source.resourceId}</dd>
                    </>
                  ) : null}
                </dl>
              </section>
            ) : null}
          </div>
        </>
      ) : (
        <div className={styles.body}>
          <p className={styles.purpose} role={error ? "alert" : undefined}>
            {loading ? "Loading…" : error ?? "This model is not in your Model Catalog."}
          </p>
        </div>
      )}
      {leaveDialog}
    </ModalShell>
  );
};

export default ModelDetailModal;
