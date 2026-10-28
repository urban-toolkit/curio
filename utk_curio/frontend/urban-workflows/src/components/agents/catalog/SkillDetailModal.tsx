import React, { useEffect, useState } from "react";

import ModalShell from "../../ModalShell";
import { CatalogDetailHeader } from "../../catalog/CatalogDetailHeader";
import { skillServes, skillsApi, type SkillCard, type SkillText } from "../../../services/agents";
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
 * read when the window opens.
 */
export const SkillDetailModal: React.FC<SkillDetailModalProps> = ({ skill, onClose }) => {
  const [text, setText] = useState<SkillText | null>(null);
  const [textError, setTextError] = useState<string | null>(null);

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
            {skill.author ?? "curio"}
            {skill.version ? ` · v${skill.version}` : null}
          </>
        }
      />

      <div className={styles.body}>
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
