import React, { useCallback, useEffect, useRef, useState } from "react";
import modal from "../modal-content.module.css";
import styles from "../ApiSettingsModal.module.css";
import { useUserContext } from "../../providers/UserProvider";
import { discoveryCatalogApi, type DiscoveryKeyRow } from "../../services/discoveryCatalog";

/**
 * API Settings → Discovery Catalog: one row per key a source can send.
 *
 * The rows come from the server's slot registry (`GET /api/discovery/keys`),
 * so a key a new source needs appears here without a change to this file.
 * Each row is a masked, write-only field: the server says whether a key is
 * saved, never what it is.
 */
export const SourceKeysSection: React.FC<{
  /** Scroll to and focus this slot's field, from a source's "Add your key". */
  focusSlot?: string | null;
}> = ({ focusSlot = null }) => {
  const { updateTokens } = useUserContext();
  const [rows, setRows] = useState<DiscoveryKeyRow[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const res = await discoveryCatalogApi.listKeys();
      setRows(res.keys);
      setLoadError(null);
    } catch (e) {
      // A list we could not read is reported, not guessed at: no row claims a
      // key is saved, or inherited, on no evidence.
      setRows([]);
      setLoadError(e instanceof Error ? e.message : "Could not load the keys");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <section className={styles.section} aria-labelledby="api-settings-discovery-title">
      <h3 id="api-settings-discovery-title" className={styles.sectionTitle}>Discovery Catalog</h3>
      <p className={modal.hint}>Keys the Discovery Catalog sends when it downloads from a source.</p>
      {loadError ? <p className={modal.error}>{loadError}</p> : null}
      {(rows ?? []).map((row) => (
        <SourceKeyRow
          key={row.slot}
          row={row}
          focused={focusSlot === row.slot}
          onSave={async (value) => {
            await updateTokens({ [row.field]: value });
            await load();
          }}
        />
      ))}
    </section>
  );
};

const SourceKeyRow: React.FC<{
  row: DiscoveryKeyRow;
  focused: boolean;
  onSave: (value: string) => Promise<void>;
}> = ({ row, focused, onSave }) => {
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState<null | "save" | "remove">(null);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const id = `api-settings-key-${row.slot.replace(/[^a-z0-9]+/gi, "-")}`;

  useEffect(() => {
    if (!focused) return;
    inputRef.current?.scrollIntoView?.({ block: "center" });
    inputRef.current?.focus();
  }, [focused]);

  const run = async (kind: "save" | "remove", next: string) => {
    setBusy(kind);
    setError(null);
    setSaved(false);
    try {
      await onSave(next);
      setValue("");
      if (kind === "save") setSaved(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : kind === "save" ? "Failed to save the key." : "Failed to remove.");
    } finally {
      setBusy(null);
    }
  };

  const state = row.present
    ? "(saved - leave blank to keep)"
    : row.inherited
      ? "(inherited - leave blank to use it)"
      : "(optional)";

  return (
    <div className={modal.field} data-key-slot={row.slot}>
      <label className={modal.label} htmlFor={id}>
        {row.label} <span className={styles.optional}>{state}</span>
      </label>
      <div className={styles.keyRow}>
        <input
          ref={inputRef}
          id={id}
          className={modal.input}
          type="password"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder={row.present ? "••••••••  (unchanged)" : row.placeholder || "Your key"}
          autoComplete="new-password"
        />
        <button
          type="button"
          className={modal.primaryBtn}
          disabled={busy !== null || !value}
          onClick={() => void run("save", value)}
        >
          {busy === "save" ? "Saving…" : "Save"}
        </button>
      </div>
      <span className={modal.hint}>
        {usedByText(row)}
        {row.note ? <> {row.note}</> : null}
        {row.inherited && !row.present ? (
          <> Whoever runs this Curio set one for everyone. Leave this blank to use it, or fill it in to override it for your account.</>
        ) : null}
      </span>
      {row.helpUrl ? (
        <a href={row.helpUrl} target="_blank" rel="noreferrer" className={styles.keyLink}>
          Get {articleFor(row.label)} {row.label} ↗
        </a>
      ) : null}
      {row.present ? (
        <button
          type="button"
          className={styles.removeSecretBtn}
          onClick={() => void run("remove", "")}
          disabled={busy !== null}
        >
          {busy === "remove" ? "Removing…" : "Remove saved key"}
        </button>
      ) : null}
      {error ? <p className={modal.error}>{error}</p> : null}
      {saved ? <p className={modal.success}>Saved.</p> : null}
    </div>
  );
};

function usedByText(row: DiscoveryKeyRow): string {
  const names = [...row.sources.map((s) => s.name), ...row.alsoUsedBy];
  if (!names.length) return "No source on this Curio uses it yet.";
  return `Used by ${listText(names)}.`;
}

function listText(items: string[]): string {
  if (items.length <= 1) return items.join("");
  return `${items.slice(0, -1).join(", ")} and ${items[items.length - 1]}`;
}

function articleFor(label: string): string {
  return /^[aeiou]/i.test(label) ? "an" : "a";
}
