import React, { useState } from "react";
import ModalShell from "../../ModalShell";
import {
  skillsApi,
  suggestSkillName,
  type SkillImportReview,
  type SkillUploadFile,
} from "../../../services/agents";
import styles from "./AgentImportModal.module.css";

/** A browser lets an input pick a folder through this attribute, which React's types do not name. */
const FOLDER_PICKER = { webkitdirectory: "", directory: "" } as Record<string, string>;

/** The files a picker chose, each by its path in what was picked: a picked
 *  folder gives each file its path in the folder, a file alone its name. */
function uploadFiles(list: FileList | null): SkillUploadFile[] {
  return Array.from(list ?? []).map((file) => ({
    path: (file as File & { webkitRelativePath?: string }).webkitRelativePath || file.name,
    file,
  }));
}

/**
 * Import a skill (the agents' import, for a skill): its folder, its loose
 * files or a zip of it, then a review before anything is kept.
 *
 * The server reads the upload as agentskills.io's guide for clients reads a
 * skill authored elsewhere, and its answer is the review: the skill's name and
 * description, what does not follow the format (read anyway), what keeping it
 * in the format leaves out, its files, and why it cannot be kept, if it
 * cannot. A name another skill takes, or that is no skill's name, gets a name
 * field, checked again before Import. The review picks the agents that use
 * the skill, each one offered picked; Import keeps it and gives it to them.
 */
export const SkillImportModal: React.FC<{
  onImported: (name: string) => void;
  onClose: () => void;
}> = ({ onImported, onClose }) => {
  const [files, setFiles] = useState<SkillUploadFile[]>([]);
  const [review, setReview] = useState<SkillImportReview | null>(null);
  const [name, setName] = useState("");
  const [agents, setAgents] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [importing, setImporting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const check = async (picked: SkillUploadFile[], asName?: string) => {
    setBusy(true);
    setError(null);
    try {
      const next = await skillsApi.checkImport(picked, asName);
      setReview(next);
      if (asName === undefined) {
        // A new pick: every agent offered starts picked, and a name the
        // review cannot keep gets one to edit.
        setAgents(new Set(next.agents.map((agent) => agent.coord)));
        setName(next.rename ? suggestSkillName(next) : next.name);
      }
    } catch (e) {
      if (asName === undefined) setReview(null);
      setError(e instanceof Error && e.message ? e.message : "The skill could not be read.");
    } finally {
      setBusy(false);
    }
  };

  const pick = (list: FileList | null) => {
    const picked = uploadFiles(list);
    if (picked.length === 0) return;
    setFiles(picked);
    void check(picked);
  };

  const submit = async () => {
    if (!review) return;
    setBusy(true);
    setImporting(true);
    setError(null);
    try {
      const result = await skillsApi.importSkill(files, {
        name: review.name,
        agents: review.agents.filter((agent) => agents.has(agent.coord)).map((agent) => agent.coord),
      });
      onImported(result.skill.name);
    } catch (e) {
      setError(e instanceof Error && e.message ? e.message : "The skill was not imported.");
    } finally {
      setBusy(false);
      setImporting(false);
    }
  };

  const toggle = (coord: string) =>
    setAgents((current) => {
      const next = new Set(current);
      if (next.has(coord)) next.delete(coord);
      else next.add(coord);
      return next;
    });

  // The name the review checked is the one Import keeps; an edited name is
  // checked again first.
  const renaming = Boolean(review?.rename);
  const nameChecked = !renaming || name === review?.name;
  const canImport = Boolean(review) && !busy && review?.problem == null && nameChecked;

  return (
    <ModalShell onClose={onClose} layer="overlay" titleId="skill-import-title">
      <div className={styles.body} data-curio-skill-import="true">
        <h2 id="skill-import-title" className={styles.title}>Import skill</h2>
        <p className={styles.hint}>
          Pick a skill&apos;s folder, which holds its <code>SKILL.md</code>, or its files, or a{" "}
          <code>.zip</code> of it. Curio reads it as other Agent Skills tools do, says what does not
          follow the format, and keeps it in the format.
        </p>

        <div className={styles.pickers}>
          <label className={styles.picker}>
            <span className={styles.pickerLabel}>A folder</span>
            <input
              type="file"
              multiple
              aria-label="Skill folder"
              {...FOLDER_PICKER}
              onChange={(e) => pick(e.target.files)}
            />
          </label>
          <label className={styles.picker}>
            <span className={styles.pickerLabel}>Files or a zip</span>
            <input type="file" multiple aria-label="Skill files" onChange={(e) => pick(e.target.files)} />
          </label>
        </div>

        {busy && !review ? <p className={styles.summary}>Reading the skill…</p> : null}

        {review ? (
          <div className={styles.review} data-curio-skill-review="true">
            <section className={styles.reviewSection}>
              <h3 className={styles.reviewLabel}>Skill</h3>
              <p className={styles.reviewText}>
                <strong>{review.name}</strong>
              </p>
              <p className={styles.reviewText}>{review.description}</p>
              {review.replaces ? (
                <p className={styles.reviewText}>It replaces your skill {review.name}, an older version.</p>
              ) : null}
            </section>

            {review.problem ? (
              <section className={styles.reviewSection}>
                <h3 className={styles.reviewLabel}>Cannot be imported as it is</h3>
                <p className={styles.error} role="alert">{review.problem}</p>
                {renaming ? (
                  <div className={styles.nameRow}>
                    <input
                      className={styles.nameInput}
                      aria-label="Skill name"
                      value={name}
                      onChange={(e) => setName(e.target.value.trim())}
                    />
                    <button
                      type="button"
                      className={styles.cancel}
                      disabled={busy || !name || name === review.name}
                      onClick={() => void check(files, name)}
                    >
                      Check name
                    </button>
                  </div>
                ) : null}
              </section>
            ) : null}

            {review.warnings.length > 0 ? (
              <section className={styles.reviewSection}>
                <h3 className={styles.reviewLabel}>Read anyway: not in the format</h3>
                <ul className={styles.reviewList}>
                  {review.warnings.map((warning) => (
                    <li key={warning}>{warning}</li>
                  ))}
                </ul>
              </section>
            ) : null}

            {review.leftOut.length > 0 ? (
              <section className={styles.reviewSection}>
                <h3 className={styles.reviewLabel}>Left out</h3>
                <ul className={styles.reviewList}>
                  {review.leftOut.map((line) => (
                    <li key={line}>{line}</li>
                  ))}
                </ul>
              </section>
            ) : null}

            <section className={styles.reviewSection}>
              <h3 className={styles.reviewLabel}>Files</h3>
              {review.files.length > 0 ? (
                <ul className={styles.reviewList}>
                  {review.files.map((file) => (
                    <li key={file}>{file}</li>
                  ))}
                </ul>
              ) : (
                <p className={styles.reviewText}>None besides SKILL.md</p>
              )}
            </section>

            <section className={styles.reviewSection}>
              <h3 className={styles.reviewLabel}>Agents that use it</h3>
              {review.agents.map((agent) => (
                <label key={agent.coord} className={styles.agentRow}>
                  <input
                    type="checkbox"
                    checked={agents.has(agent.coord)}
                    onChange={() => toggle(agent.coord)}
                  />
                  {agent.name}
                </label>
              ))}
            </section>
          </div>
        ) : null}

        {error ? <p className={styles.error} role="alert">{error}</p> : null}

        <div className={styles.footer}>
          <button type="button" className={styles.cancel} onClick={onClose}>
            Cancel
          </button>
          <button type="button" className={styles.import} disabled={!canImport} onClick={() => void submit()}>
            {importing ? "Importing…" : review?.replaces ? "Replace" : "Import"}
          </button>
        </div>
      </div>
    </ModalShell>
  );
};

export default SkillImportModal;
