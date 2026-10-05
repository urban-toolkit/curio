import React, { useId, useState } from "react";

import type { DiscoveryParameter } from "../../services/discoveryCatalog";
import styles from "./DiscoveryAddDialog.module.css";

/**
 * A `tags` answer: OpenStreetMap tags as chips, each `key=value`, or `key=*`
 * for the key with any value (`domain/parameters.py`). The source's suggested
 * keys are offered as `key=*` while typing; Enter or Add checks the entry and
 * adds it. The server checks every entry again.
 */

/** One tag entry. KEEP IN SYNC with `TAG_ENTRY_RE` in `discovery/domain/parameters.py`. */
export const TAG_ENTRY_PATTERN = String.raw`^([A-Za-z0-9][A-Za-z0-9_:.\-]{0,63})=(\*|[^"\\\[\]\x00-\x1f\x7f]{1,255})$`;
export const TAG_ENTRY_RE = new RegExp(TAG_ENTRY_PATTERN);
export const MAX_TAGS = 16;

/** The entry as `key=value`, without the spaces around each part, or null when it is not a tag. */
export function parseTagEntry(text: string): string | null {
  const at = text.indexOf("=");
  if (at < 0) return null;
  const entry = `${text.slice(0, at).trim()}=${text.slice(at + 1).trim()}`;
  return TAG_ENTRY_RE.test(entry) ? entry : null;
}

export interface TagsFieldProps {
  parameter: DiscoveryParameter;
  value: unknown;
  onChange: (value: string[]) => void;
}

export function TagsField({ parameter: p, value, onChange }: TagsFieldProps) {
  const entries = Array.isArray(value) ? (value as string[]) : [];
  const [draft, setDraft] = useState("");
  const [problem, setProblem] = useState<string | null>(null);
  const listId = useId();
  const inputId = `discovery-parameter-${p.id}`;
  const full = entries.length >= MAX_TAGS;

  const commit = () => {
    const text = draft.trim();
    if (!text) return;
    const entry = parseTagEntry(text);
    if (!entry) {
      setProblem(`"${text}" is not a tag: write key=value or key=*.`);
      return;
    }
    if (!entries.includes(entry)) onChange([...entries, entry]);
    setDraft("");
    setProblem(null);
  };

  return (
    <div className={styles.field} data-parameter={p.id}>
      <label className={styles.fieldLabel} htmlFor={inputId}>
        {p.label}
        {p.required ? null : <span className={styles.hint}> optional</span>}
      </label>
      {p.description ? <span className={styles.hint}>{p.description}</span> : null}
      {entries.length > 0 ? (
        <div className={styles.chips} aria-label={`${p.label} chosen`}>
          {entries.map((entry) => (
            <span key={entry} className={styles.chip}>
              {entry}
              <button
                type="button"
                aria-label={`Remove ${entry}`}
                onClick={() => onChange(entries.filter((e) => e !== entry))}
              >
                ×
              </button>
            </span>
          ))}
        </div>
      ) : null}
      <div className={styles.range}>
        <input
          id={inputId}
          className={styles.input}
          list={listId}
          placeholder="amenity=school, or shop=*"
          value={draft}
          disabled={full}
          onChange={(e) => {
            setDraft(e.target.value);
            setProblem(null);
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              commit();
            }
          }}
          onBlur={() => {
            if (parseTagEntry(draft.trim())) commit();
          }}
        />
        <datalist id={listId}>
          {(p.suggestions ?? []).map((key) => (
            <option key={key} value={`${key}=*`} />
          ))}
        </datalist>
        <button type="button" className={styles.modeBtn} disabled={full || !draft.trim()} onClick={commit}>
          Add
        </button>
      </div>
      {full ? <p className={styles.hint}>{MAX_TAGS} tags at most.</p> : null}
      {problem ? <p className={styles.warning}>{problem}</p> : null}
    </div>
  );
}

export default TagsField;
