import React from "react";
import { useLocation, useNavigate } from "react-router-dom";

import ModalShell from "../../ModalShell";
import DataflowThumbnail from "../../DataflowThumbnail";
import { CatalogDetailHeader } from "../../catalog/CatalogDetailHeader";
import { LEAVE_DATAFLOW, useLeaveGuard } from "../../../hook/useLeaveGuard";
import { useScenarioDetails, type ScenarioRow } from "../../../services/scenarioCatalog";
import {
  ScenarioNodeList,
  ScenarioSwatch,
  scenarioHighlight,
  scenarioInfoRows,
  scenarioNodeCount,
  scenarioProjectPath,
} from "./scenarioFacts";
import styles from "../../agents/catalog/AgentDetailModal.module.css";
import factStyles from "./scenarioFacts.module.css";

export interface ScenarioDetailModalProps {
  projectId: string;
  scenarioId: string;
  /** The listing's row, shown at once while the scenario's own GET answers. */
  fallbackScenario?: ScenarioRow | null;
  /** The dataflow behind the modal has changes not yet saved, so opening
   *  another project asks first. Set only on the canvas. */
  unsavedChanges?: boolean;
  /** Runs as the modal leaves for the source project, so the canvas drawer
   *  under it closes too. */
  onLeave?: () => void;
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
 * "View details" for one scenario, the Scenario Catalog's answer to
 * `ModelDetailModal`: the same modal, the same header.
 *
 * A scenario is read off its project, so this only reads: its fixed context,
 * its levers and its outcomes, each node with its parameter value and its
 * saved outputs, and the project graph with the scenario marked on it.
 * Changing a scenario means opening its project.
 */
export const ScenarioDetailModal: React.FC<ScenarioDetailModalProps> = ({
  projectId,
  scenarioId,
  fallbackScenario = null,
  unsavedChanges = false,
  onLeave,
  onClose,
}) => {
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const { leave, dialog: leaveDialog } = useLeaveGuard(unsavedChanges, LEAVE_DATAFLOW, {
    layer: "overlay",
  });
  const { details, error } = useScenarioDetails(projectId, scenarioId);
  const scenario: ScenarioRow | null = details ?? fallbackScenario;

  // Opening the project leaves this page (or this dataflow, which asks first
  // when it has unsaved changes). The project already open just closes.
  const openProject = () => {
    const to = scenarioProjectPath(projectId);
    if (samePath(to, pathname)) {
      onClose();
      onLeave?.();
      return;
    }
    leave(() => {
      onClose();
      onLeave?.();
      navigate(to);
    });
  };

  return (
    <ModalShell onClose={onClose} size="xlarge" layer="overlay" label="Scenario details">
      {scenario ? (
        <>
          <CatalogDetailHeader
            kind="scenario"
            title={scenario.name}
            subtitle={
              <>
                <ScenarioSwatch color={scenario.color} /> {scenario.project.name} ·{" "}
                {scenarioNodeCount(scenario)}
              </>
            }
            actions={
              <button type="button" className={styles.exportButton} onClick={openProject}>
                Open source project
              </button>
            }
          />

          <div className={styles.body} data-scenario-key={scenario.key}>
            {scenario.description ? <p className={styles.purpose}>{scenario.description}</p> : null}
            {error ? (
              <p className={styles.purpose} role="alert">
                {error}
              </p>
            ) : null}

            <div className={factStyles.detailThumb} data-curio-scenario-thumbnail="true">
              <DataflowThumbnail
                preview={scenario.preview}
                highlight={details ? scenarioHighlight(details) : null}
              />
            </div>

            <section className={styles.section}>
              <h3 className={styles.sectionLabel}>Scenario</h3>
              <dl className={styles.infoGrid}>
                {scenarioInfoRows(scenario, details).map(({ label, value }) => (
                  <React.Fragment key={label}>
                    <dt className={styles.infoLabel}>{label}</dt>
                    <dd className={styles.infoValue}>{value}</dd>
                  </React.Fragment>
                ))}
              </dl>
            </section>

            {details ? (
              <>
                <section className={styles.section} aria-label="Fixed context">
                  <h3 className={styles.sectionLabel}>Fixed context</h3>
                  <ScenarioNodeList entries={details.context} />
                </section>
                <section className={styles.section} aria-label="Levers">
                  <h3 className={styles.sectionLabel}>Levers</h3>
                  <ScenarioNodeList entries={details.levers} />
                </section>
                <section className={styles.section} aria-label="Outcomes">
                  <h3 className={styles.sectionLabel}>Outcomes</h3>
                  <ScenarioNodeList entries={details.outcomes} />
                </section>
              </>
            ) : error ? null : (
              <p className={styles.purpose}>Loading…</p>
            )}
          </div>
        </>
      ) : (
        // Without details or an error the GET is still out: the hook starts
        // it in an effect, after the first paint.
        <div className={styles.body}>
          <p className={styles.purpose} role={error ? "alert" : undefined}>
            {error ?? "Loading…"}
          </p>
        </div>
      )}
      {leaveDialog}
    </ModalShell>
  );
};

export default ScenarioDetailModal;
