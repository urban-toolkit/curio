import React, { useEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";

import ModalShell from "../../ModalShell";
import DataflowThumbnail from "../../DataflowThumbnail";
import { CatalogDetailHeader } from "../../catalog/CatalogDetailHeader";
import { LEAVE_DATAFLOW, useLeaveGuard } from "../../../hook/useLeaveGuard";
import {
  useScenarioDetails,
  type ScenarioDetails,
  type ScenarioRow,
} from "../../../services/scenarioCatalog";
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

/** What the In project details change of a scenario. */
export type ScenarioFieldsPatch = { name?: string; color?: string; description?: string };

/** A scenario of the open dataflow, in the drawer's In project tab. */
export interface InProjectScenario {
  /** Read off the canvas (`inProjectDetails` in `inProjectRows.ts`). */
  details: ScenarioDetails;
  /** Changes its name, color or description. Absent for a shared viewer,
   *  who reads the scenario and changes nothing. */
  onEdit?: (patch: ScenarioFieldsPatch) => void;
}

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
  /** A scenario of the open dataflow: read off the canvas, so an unsaved one
   *  has its details too, and edited in place. Nothing is fetched. */
  inProject?: InProjectScenario;
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
 * A scenario of another project is read off its project, so this only reads:
 * its fixed context, its levers and its outcomes, each node with its parameter
 * value and its saved outputs, and the project graph with the scenario marked
 * on it. Changing it means opening its project.
 *
 * A scenario of the open dataflow (the drawer's In project tab) is read off the
 * canvas, and its name, color and description are edited here.
 */
export const ScenarioDetailModal: React.FC<ScenarioDetailModalProps> = ({
  projectId,
  scenarioId,
  fallbackScenario = null,
  unsavedChanges = false,
  onLeave,
  onClose,
  inProject,
}) => {
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const { leave, dialog: leaveDialog } = useLeaveGuard(unsavedChanges, LEAVE_DATAFLOW, {
    layer: "overlay",
  });
  const fetched = useScenarioDetails(inProject ? null : projectId, inProject ? null : scenarioId);
  const details: ScenarioDetails | null = inProject ? inProject.details : fetched.details;
  const error = inProject ? null : fetched.error;
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
              // The open dataflow is where its own scenarios are edited.
              inProject ? undefined : (
                <button type="button" className={styles.exportButton} onClick={openProject}>
                  Open source project
                </button>
              )
            }
          />

          <div className={styles.body} data-scenario-key={scenario.key}>
            {inProject?.onEdit ? (
              <ScenarioFields scenario={scenario} onEdit={inProject.onEdit} />
            ) : scenario.description ? (
              <p className={styles.purpose}>{scenario.description}</p>
            ) : null}
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
                {scenarioInfoRows(scenario, details, { origin: !inProject }).map(({ label, value }) => (
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
                  <ScenarioNodeList
                    entries={details.context}
                    results={!inProject}
                    empty={inProject && details.levers.length > 0 ? "None: everything it reads is in it." : "None."}
                  />
                </section>
                <section className={styles.section} aria-label="Levers">
                  <h3 className={styles.sectionLabel}>Levers</h3>
                  <ScenarioNodeList
                    entries={details.levers}
                    results={!inProject}
                    empty={inProject ? "No nodes: add some, or delete it." : "None."}
                  />
                </section>
                <section className={styles.section} aria-label="Outcomes">
                  <h3 className={styles.sectionLabel}>Outcomes</h3>
                  <ScenarioNodeList entries={details.outcomes} results={!inProject} />
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

/**
 * The name, color and description of a scenario of the open dataflow: the
 * name is changed on Enter or on leaving the field (an empty one goes back),
 * the color as it is picked, the description on leaving the field.
 */
function ScenarioFields({
  scenario,
  onEdit,
}: {
  scenario: Pick<ScenarioRow, "name" | "color" | "description">;
  onEdit: (patch: ScenarioFieldsPatch) => void;
}) {
  const [name, setName] = useState(scenario.name);
  const [description, setDescription] = useState(scenario.description);
  // Enter commits, and the blur that follows must not commit it again.
  const sentName = useRef<string | null>(null);
  useEffect(() => {
    setName(scenario.name);
    sentName.current = null;
  }, [scenario.name]);
  useEffect(() => setDescription(scenario.description), [scenario.description]);

  const commitName = () => {
    const next = name.trim();
    if (!next) {
      setName(scenario.name);
      return;
    }
    if (next === scenario.name || next === sentName.current) return;
    sentName.current = next;
    onEdit({ name: next });
  };
  const commitDescription = () => {
    if (description !== scenario.description) onEdit({ description });
  };

  return (
    <section className={factStyles.fields} aria-label="Name, color and description">
      <span className={factStyles.fieldLabel}>Name</span>
      <input
        type="text"
        className={factStyles.fieldInput}
        aria-label="Scenario name"
        value={name}
        onChange={(e) => setName(e.target.value)}
        onBlur={commitName}
        onKeyDown={(e) => {
          if (e.key !== "Enter") return;
          commitName();
          e.currentTarget.blur();
        }}
      />
      <span className={factStyles.fieldLabel}>Color</span>
      <input
        type="color"
        className={factStyles.fieldColor}
        aria-label={`Color of ${scenario.name}`}
        value={scenario.color}
        onChange={(e) => onEdit({ color: e.target.value })}
      />
      <span className={factStyles.fieldLabel}>Description</span>
      <textarea
        className={factStyles.fieldInput}
        aria-label="Scenario description"
        placeholder="Description"
        rows={2}
        value={description}
        onChange={(e) => setDescription(e.target.value)}
        onBlur={commitDescription}
      />
    </section>
  );
}

export default ScenarioDetailModal;
