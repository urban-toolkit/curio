import React, { useEffect, useState } from "react";

import ModalShell from "../../ModalShell";
import { CatalogDetailHeader } from "../../catalog/CatalogDetailHeader";
import {
  SKILL_SOURCE_WORDS,
  skillByline,
  skillServes,
  skillsApi,
  type SkillCard,
  type SkillText,
} from "../../../services/agents";
import styles from "./AgentDetailModal.module.css";

export interface SkillDetailModalProps {
  skill: SkillCard;
  onClose: () => void;
}

/**
 * "View details" for one skill: a modal, as an agent's details are, never a
 * page.
 *
 * What the skill is for, in its own words; what it serves, the kinds of node
 * whose templates name one of its behaviors and the features of a dataflow it
 * names; the agents that use it, after this account's changes; its facts; its
 * text as an agent reads it, collapsed as an agent's prompts are; and its
 * other files. The text is the one thing the card does not carry, so it is
 * read when the window opens. **Export** saves the skill as a zip of its
 * folder, as an agent's details export the agent: a skill Curio ships with
 * its markers filled, so it reads as the format has it in any Agent Skills
 * tool.
 */
export const SkillDetailModal: React.FC<SkillDetailModalProps> = ({ skill, onClose }) => {
  const [text, setText] = useState<SkillText | null>(null);
  const [textError, setTextError] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);
  // The export's own failure, beside the button that caused it, as an
  // agent's details show theirs.
  const [exportError, setExportError] = useState<string | null>(null);

  const onExport = async () => {
    if (exporting) return;
    setExporting(true);
    setExportError(null);
    try {
      await skillsApi.exportSkill(skill.name);
    } catch (err) {
      setExportError(err instanceof Error && err.message ? err.message : "Export failed.");
    } finally {
      setExporting(false);
    }
  };

  useEffect(() => {
    let cancelled = false;
    setText(null);
    setTextError(null);
    skillsApi
      .read(skill.name)
      .then((read) => {
        if (!cancelled) setText(read);
      })
      .catch(() => {
        if (!cancelled) setTextError("The skill's text is not available.");
      });
    return () => {
      cancelled = true;
    };
  }, [skill.name]);

  const serves = skillServes(skill);
  const files = text?.files ?? skill.files;
  const rows: [string, React.ReactNode][] = [
    ["Name", skill.name],
    ["From", SKILL_SOURCE_WORDS[skill.source ?? "curio"]],
    ["Version", skill.version ?? "Not given"],
    ["Author", skill.author ?? "Not given"],
    ["License", skill.license ?? "Not given"],
    ["Compatibility", skill.compatibility ?? "Not given"],
  ];

  return (
    <ModalShell onClose={onClose} size="xlarge" layer="overlay" label="Skill details">
      <CatalogDetailHeader
        kind="skill"
        title={skill.name}
        subtitle={
          <>
            {skillByline(skill)}
            {skill.version ? ` · v${skill.version}` : null}
          </>
        }
        actions={
          <button
            type="button"
            className={styles.exportButton}
            disabled={exporting}
            data-tooltip="Save this skill as a zip of its folder"
            onClick={() => void onExport()}
          >
            {exporting ? "Exporting…" : "Export"}
          </button>
        }
      />

      <div className={styles.body}>
        {exportError ? (
          <p className={styles.purpose} role="alert" data-curio-export-error="true">
            Export failed: {exportError}
          </p>
        ) : null}

        <section className={styles.section}>
          <h3 className={styles.sectionLabel}>Description</h3>
          <p className={styles.sectionText}>{skill.description}</p>
        </section>

        <section className={styles.section}>
          <h3 className={styles.sectionLabel}>Serves</h3>
          {skill.core ? (
            <p className={styles.sectionText}>Every call of every agent: the preamble holds it.</p>
          ) : serves.length > 0 ? (
            <ul className={styles.list}>
              {serves.map((served) => (
                <li key={served}>{served}</li>
              ))}
            </ul>
          ) : (
            <p className={styles.sectionText}>Nothing on its own: a chat loads it when a task needs it.</p>
          )}
        </section>

        <section className={styles.section}>
          <h3 className={styles.sectionLabel}>Used by</h3>
          {skill.agents.length > 0 ? (
            <ul className={styles.list}>
              {skill.agents.map((agent) => (
                <li key={agent.coord}>
                  {agent.name}
                  {agent.added ? " (added by you)" : ""}
                </li>
              ))}
            </ul>
          ) : (
            <p className={styles.sectionText}>No agent</p>
          )}
        </section>

        <section className={styles.section}>
          <h3 className={styles.sectionLabel}>Skill info</h3>
          <dl className={styles.infoGrid}>
            {rows.map(([label, value]) => (
              <React.Fragment key={label}>
                <dt className={styles.infoLabel}>{label}</dt>
                <dd className={styles.infoValue}>{value}</dd>
              </React.Fragment>
            ))}
          </dl>
        </section>

        <section className={styles.section}>
          <h3 className={styles.sectionLabel}>Text</h3>
          {textError ? (
            <p className={styles.purpose}>{textError}</p>
          ) : !text ? (
            <p className={styles.purpose}>Loading…</p>
          ) : (
            <details className={styles.promptBlock}>
              {/* Collapsed, as an agent's prompts are: a skill runs to
                  hundreds of lines. */}
              <summary className={styles.promptName}>
                <span className={styles.promptRuns}>What an agent reads</span>
                {" · "}
                SKILL.md
              </summary>
              <pre className={styles.promptText}>{text.text}</pre>
            </details>
          )}
        </section>

        <section className={styles.section}>
          <h3 className={styles.sectionLabel}>Files</h3>
          {files.length > 0 ? (
            <ul className={styles.list}>
              {files.map((file) => (
                <li key={file}>{file}</li>
              ))}
            </ul>
          ) : (
            <p className={styles.sectionText}>None besides SKILL.md</p>
          )}
        </section>
      </div>
    </ModalShell>
  );
};

export default SkillDetailModal;
