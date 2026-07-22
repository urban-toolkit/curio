import React, { useCallback, useEffect, useState } from "react";
import ModalShell from "../../ModalShell";
import { agentsApi, type ProjectAgentDefaults } from "../../../api/agentsApi";
import styles from "./ProjectAgentSettingsModal.module.css";

/**
 * The **Project agent default** scope for one installed template (memo dev/23):
 * a read-only view of the per-project record and the effective policy with its
 * provenance ("Inherited from account"). The Cost/Quotas/Resource editors
 * arrive with the settings screens; this scope never shows Publish, Release,
 * or Share (memo dev/11/12 invariant).
 */
export const ProjectAgentSettingsModal: React.FC<{
  projectId: string;
  coord: string;
  onClose: () => void;
}> = ({ projectId, coord, onClose }) => {
  const [data, setData] = useState<ProjectAgentDefaults | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setData(await agentsApi.getProjectAgentDefaults(projectId, coord));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load settings");
    } finally {
      setLoading(false);
    }
  }, [projectId, coord]);

  useEffect(() => {
    void load();
  }, [load]);

  const inherited = <span className={styles.provenance}>Inherited from account</span>;

  return (
    <ModalShell onClose={onClose} layer="overlay">
      <div
        className={styles.body}
        role="dialog"
        aria-label={`Project agent settings for ${data?.name ?? coord}`}
      >
        <p className={styles.scope}>Project agent default</p>
        <h2 className={styles.title}>{data?.name ?? coord}</h2>
        <p className={styles.coord}>{coord}</p>

        {loading ? (
          <p className={styles.state}>Loading settings…</p>
        ) : error ? (
          <p className={styles.state}>
            {error}
            <button type="button" className={styles.retry} onClick={() => void load()}>
              Retry
            </button>
          </p>
        ) : data ? (
          <>
            <section className={styles.section}>
              <h3 className={styles.sectionTitle}>Quotas</h3>
              <div className={styles.row}>
                <span>
                  Runs per day: <strong>{data.effective.quotas.runsPerDay.value}</strong> ·{" "}
                  {data.effective.quotas.runsPerDay.usedToday} used today
                </span>
                {inherited}
              </div>
            </section>

            <section className={styles.section}>
              <h3 className={styles.sectionTitle}>Cost</h3>
              <div className={styles.row}>
                <span>
                  {data.effective.cost.configured
                    ? "Project budget configured"
                    : "No project budget set"}
                </span>
                {inherited}
              </div>
            </section>

            <section className={styles.section}>
              <h3 className={styles.sectionTitle}>Resource policy</h3>
              <div className={styles.row}>
                <span>
                  {data.effective.resources.provider
                    ? `${data.effective.resources.provider} · ${data.effective.resources.model ?? ""}`
                    : "No provider available"}
                </span>
                {inherited}
              </div>
            </section>

            <p className={styles.footnote}>
              These project defaults become editable with the Cost, Quotas, and Resource-policy
              settings screens. This scope has no Publish, Release, or Share.
            </p>
          </>
        ) : null}
      </div>
    </ModalShell>
  );
};
