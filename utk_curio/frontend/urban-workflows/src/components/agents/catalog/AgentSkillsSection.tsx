import React, { useEffect, useState } from "react";

import { skillsApi, type AgentSkillRow, type AgentSkills } from "../../../services/agents";
import styles from "./AgentDetailModal.module.css";

export interface AgentSkillsSectionProps {
  /** The agent's coordinate, `<agentId>@<major>`. */
  coord: string;
  agentName: string;
  /** An agent Curio ships, whose list Restore brings back. */
  builtIn: boolean;
}

/** What a row says beside its name: why it cannot be removed, or that this
 *  account added it. */
function rowNote(row: AgentSkillRow): string | null {
  if (row.core) return "Every call";
  const holders = [
    row.chat ? "in chat" : null,
    row.modes.length > 0 ? `for ${row.modes.join(", ")}` : null,
    row.asked ? "when another agent asks" : null,
  ].filter((holder): holder is string => holder !== null);
  if (holders.length > 0) return `Always ${holders.join(" and ")}`;
  if (row.added) return "Added by you";
  return null;
}

/**
 * An agent's skills, the fourth of the docs' words in its details
 * (docs/AGENT-CATALOG.md, "Skills"): what tells it how to do a specific task.
 *
 * The rows are this account's: the core skills its preamble holds, then the
 * skills its manifest names after the account's changes, then those its chat
 * or a mode of it always holds. **Add skill** picks one of the skills it does
 * not hold, **Remove** drops one, and **Restore** brings back the list it
 * ships with; each is saved at once and reaches its next run. The core
 * skills and those its instruction or a mode names as its own show no
 * Remove, and an account that may change none (a hosted guest) sees the list
 * alone.
 */
export const AgentSkillsSection: React.FC<AgentSkillsSectionProps> = ({ coord, agentName, builtIn }) => {
  const [skills, setSkills] = useState<AgentSkills | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [adding, setAdding] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setSkills(null);
    setError(null);
    setAdding(false);
    skillsApi
      .agentSkills(coord)
      .then((rows) => {
        if (!cancelled) setSkills(rows);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error && err.message ? err.message : "Skills are not available.");
      });
    return () => {
      cancelled = true;
    };
  }, [coord]);

  const act = async (change: () => Promise<AgentSkills>) => {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      setSkills(await change());
      setAdding(false);
    } catch (err) {
      setError(err instanceof Error && err.message ? err.message : "The change was not saved.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className={styles.section} data-curio-agent-skills="true">
      <h3 className={styles.sectionLabel}>Skills</h3>
      {error ? (
        <p className={styles.skillError} role="alert">
          {error}
        </p>
      ) : null}
      {!skills ? (
        error ? null : <p className={styles.sectionText}>Loading…</p>
      ) : (
        <>
          {skills.skills.length > 0 ? (
            <ul className={styles.skillList}>
              {skills.skills.map((row) => {
                const note = rowNote(row);
                return (
                  <li key={row.name} className={styles.skillRow} data-curio-skill-row={row.name}>
                    <span className={styles.skillName} data-tooltip={row.description}>
                      {row.name}
                    </span>
                    {note ? <span className={styles.skillNote}>{note}</span> : null}
                    {row.removable ? (
                      <button
                        type="button"
                        className={styles.skillButton}
                        aria-label={`Remove ${row.name} from ${agentName}`}
                        disabled={busy}
                        onClick={() => void act(() => skillsApi.removeSkill(coord, row.name))}
                      >
                        Remove
                      </button>
                    ) : null}
                  </li>
                );
              })}
            </ul>
          ) : (
            <p className={styles.sectionText}>None</p>
          )}
          {skills.editable && (skills.addable.length > 0 || skills.changed) ? (
            <div className={styles.skillActions}>
              {skills.addable.length > 0 ? (
                <button
                  type="button"
                  className={styles.skillButton}
                  aria-expanded={adding}
                  disabled={busy}
                  onClick={() => setAdding((open) => !open)}
                >
                  Add skill
                </button>
              ) : null}
              {skills.changed ? (
                <button
                  type="button"
                  className={styles.skillButton}
                  disabled={busy}
                  data-tooltip={
                    builtIn ? "Back to the skills Curio gives this agent" : "Back to the skills its manifest names"
                  }
                  onClick={() => void act(() => skillsApi.restoreSkills(coord))}
                >
                  Restore
                </button>
              ) : null}
            </div>
          ) : null}
          {adding && skills.editable ? (
            <ul className={styles.skillPicker} aria-label={`Skills to add to ${agentName}`}>
              {skills.addable.map((skill) => (
                <li key={skill.name}>
                  <button
                    type="button"
                    className={styles.skillPick}
                    disabled={busy}
                    onClick={() => void act(() => skillsApi.addSkill(coord, skill.name))}
                  >
                    <span className={styles.skillName}>{skill.name}</span>
                    <span className={styles.skillPickText}>{skill.description}</span>
                  </button>
                </li>
              ))}
            </ul>
          ) : null}
        </>
      )}
    </section>
  );
};

export default AgentSkillsSection;
