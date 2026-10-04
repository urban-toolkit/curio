import React, { useEffect, useRef, useState } from "react";
import modal from "../modal-content.module.css";
import llmStyles from "../llmConfigs/LlmConfigs.module.css";
import styles from "./ApiSettings.module.css";
import type { DiscoveryKeyRow } from "../../services/discoveryCatalog";

/** The input id for a slot's key, which a source's "Add yours in API Settings"
 *  link lands on. */
export function sourceKeyInputId(slot: string): string {
  return `api-settings-key-${slot.replace(/[^a-z0-9]+/gi, "-")}`;
}

/**
 * The form for one key a Discovery Catalog source sends, opened from API keys'
 * "Add configuration" or a saved key's row. The field is masked and
 * write-only: the server says whether a key is saved, never what it is.
 */
export const SourceKeyForm: React.FC<{
  row: DiscoveryKeyRow;
  title: string;
  /** The "Kind" select, when this form was opened by "Add configuration". */
  kindPicker?: React.ReactNode;
  onSave: (value: string) => Promise<void>;
  onCancel: () => void;
}> = ({ row, title, kindPicker, onSave, onCancel }) => {
  const [value, setValue] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const id = sourceKeyInputId(row.slot);

  useEffect(() => {
    inputRef.current?.scrollIntoView?.({ block: "center" });
    inputRef.current?.focus();
  }, [row.slot]);

  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      await onSave(value);
      setValue("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save the key.");
    } finally {
      setSaving(false);
    }
  };

  const state = row.present
    ? "(saved - leave blank to keep)"
    : row.inherited
      ? "(inherited - leave blank to use it)"
      : "(optional)";

  return (
    <div className={llmStyles.editor} data-testid="source-key-editor">
      <h4 className={llmStyles.editorTitle}>{title}</h4>
      {kindPicker}
      <div className={modal.field} data-key-slot={row.slot}>
        <label className={modal.label} htmlFor={id}>
          {row.label} <span className={styles.optional}>{state}</span>
        </label>
        <input
          ref={inputRef}
          id={id}
          className={modal.input}
          type="password"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder={row.present ? "••••••••  (unchanged)" : row.placeholder || "Your key"}
          autoComplete="new-password"
          disabled={saving}
        />
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
      </div>
      {error ? <p className={modal.error} role="alert">{error}</p> : null}
      <div className={modal.buttonRow}>
        <button type="button" className={modal.ghostBtn} onClick={onCancel} disabled={saving}>
          Cancel
        </button>
        <button
          type="button"
          className={modal.primaryBtn}
          disabled={saving || !value}
          onClick={() => void save()}
        >
          {saving ? "Saving…" : "Save"}
        </button>
      </div>
    </div>
  );
};

/** "Used by A and B.", for the form's hint and the key's row. */
export function usedByText(row: DiscoveryKeyRow): string {
  const names = row.sources.map((s) => s.name);
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
