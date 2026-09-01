import React, { useState } from "react";
import ModalShell from "../../ModalShell";
import { agentsApi } from "../../../api/agentsApi";
import { buildUploadPayload, type NamedText } from "./buildUploadPayload";
import styles from "./AgentImportModal.module.css";

/**
 * Import package (memo dev/36): upload a user-authored agent definition —
 * one `manifest.json` plus its `.txt` prompt files - into My imports as an
 * owned, publishable definition. Server-side rules are authoritative (forced
 * `imported` trust, digest stamping, exact file correspondence, size limits,
 * immutability 409s); this modal assembles the payload and shows the server's
 * field-specific errors verbatim. Import never installs or publishes.
 */
export const AgentImportModal: React.FC<{
  onImported: (dirName: string) => void;
  onClose: () => void;
}> = ({ onImported, onClose }) => {
  const [files, setFiles] = useState<NamedText[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  /**
   * Accumulate across dialogs, replacing same-named entries.
   *
   * This used to `setFiles(read)`, which made the documented package layout
   * impossible to import. An agent package is `<id>@<version>/manifest.json`
   * plus `<id>@<version>/prompts/*.txt` (docs/AGENT-CATALOG.md) - two
   * directories - and one OS file dialog cannot span two directories. So the
   * manifest and its prompts had to be picked in two goes, and the second go
   * discarded the first. The only way through was to flatten the package into
   * a single folder first, which nothing tells the user to do.
   */
  const pick = async (list: FileList | null) => {
    if (!list) return;
    setError(null);
    const read = await Promise.all(
      Array.from(list).map(async (f) => ({ name: f.name, text: await f.text() })),
    );
    setFiles((prev) => {
      const byName = new Map(prev.map((f) => [f.name, f]));
      for (const f of read) byName.set(f.name, f);
      return Array.from(byName.values());
    });
  };

  const submit = async () => {
    setError(null);
    setBusy(true);
    try {
      const payload = buildUploadPayload(files);
      const card = await agentsApi.uploadImport(payload.manifest, payload.prompts);
      onImported(card.dirName);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Import failed");
    } finally {
      setBusy(false);
    }
  };

  const promptCount = files.filter((f) => f.name.toLowerCase() !== "manifest.json").length;
  const hasManifest = files.some((f) => f.name.toLowerCase() === "manifest.json");

  return (
    <ModalShell onClose={onClose} layer="overlay" titleId="agent-import-title">
      <div className={styles.body}>
        <h2 id="agent-import-title" className={styles.title}>Import agent package</h2>
        <p className={styles.hint}>
          Pick a <code>.curio-agent.json</code> exported from an agent&apos;s details
          screen, or one <code>manifest.json</code> and its <code>.txt</code> prompt
          files. Those live in separate folders, so you can pick them in more than one
          go - each selection adds to the list.
        </p>

        <label className={styles.picker}>
          <input
            type="file"
            multiple
            accept=".json,.txt"
            aria-label="Package files"
            onChange={(e) => void pick(e.target.files)}
          />
        </label>

        {files.length > 0 ? (
          <p className={styles.summary}>
            {hasManifest ? "manifest.json" : "no manifest yet"} · {promptCount} prompt file
            {promptCount === 1 ? "" : "s"}
            {" "}
            {/* Selections accumulate, so there has to be a way back to empty. */}
            <button type="button" className={styles.clear} onClick={() => setFiles([])}>
              Clear
            </button>
          </p>
        ) : null}

        {error ? <p className={styles.error}>{error}</p> : null}

        <div className={styles.footer}>
          <button type="button" className={styles.cancel} onClick={onClose}>
            Cancel
          </button>
          <button
            type="button"
            className={styles.import}
            disabled={busy || !hasManifest}
            onClick={() => void submit()}
          >
            {busy ? "Importing…" : "Import"}
          </button>
        </div>
      </div>
    </ModalShell>
  );
};
