/**
 * Accessible per-node color control (memo dev/89 §3 "Node Researcher DOD
 * profile" / §5): the named palette as a labeled, keyboard-operable radio
 * group plus a validated six-digit custom-hex input. Validation is the ONE
 * shared `utils/nodeAppearance` utility — this component never invents color
 * rules; invalid input is announced (aria-live) and never propagated.
 *
 * A direct recolor through this control is an ordinary canvas edit: the
 * caller writes the normalized value into `node.data.appearance` and the
 * regular save path persists it — no package rebuild, ever (dev/89 §3).
 */

import React, { useId, useState } from "react";
import {
  NAMED_COLORS,
  normalizeBackground,
  resolveBackground,
} from "../utils/nodeAppearance";
import styles from "./NodeColorControl.module.css";

export interface NodeColorControlProps {
  /** The stored backgroundColor (hex or legacy junk — resolved for display). */
  value: string | undefined;
  /** Receives the NORMALIZED hex for every valid selection or hex entry. */
  onChange: (backgroundColor: string) => void;
  /** Group label; defaults to "Note color". */
  label?: string;
}

const PALETTE_ORDER = ["yellow", "pink", "blue", "green", "orange", "lavender"];

export function NodeColorControl({
  value,
  onChange,
  label = "Note color",
}: NodeColorControlProps): JSX.Element {
  const groupId = useId();
  const current = resolveBackground(value);
  const [hexDraft, setHexDraft] = useState("");
  const [error, setError] = useState<string | null>(null);

  const commitHex = () => {
    if (!hexDraft.trim()) return;
    const result = normalizeBackground(hexDraft.trim());
    if (!result.ok) {
      setError(result.reason);
      return;
    }
    setError(null);
    setHexDraft("");
    onChange(result.value);
  };

  return (
    <div className={styles.root}>
      <fieldset className={styles.swatches} aria-describedby={`${groupId}-error`}>
        <legend className={styles.legend}>{label}</legend>
        {PALETTE_ORDER.map((name) => {
          const hex = NAMED_COLORS[name];
          const inputId = `${groupId}-${name}`;
          return (
            <label key={name} className={styles.swatchLabel} htmlFor={inputId}>
              <input
                id={inputId}
                className={styles.swatchInput}
                type="radio"
                name={`${groupId}-palette`}
                value={name}
                checked={current === hex}
                onChange={() => {
                  setError(null);
                  onChange(hex);
                }}
                aria-label={`${name} (${hex})`}
              />
              <span className={styles.swatch} style={{ background: hex }} aria-hidden="true" />
            </label>
          );
        })}
      </fieldset>
      <div className={styles.hexRow}>
        <label htmlFor={`${groupId}-hex`}>Custom hex</label>
        <input
          id={`${groupId}-hex`}
          className={styles.hexInput}
          type="text"
          inputMode="text"
          placeholder="#rrggbb"
          maxLength={7}
          value={hexDraft}
          onChange={(e) => setHexDraft(e.target.value)}
          onBlur={commitHex}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              commitHex();
            }
          }}
          aria-invalid={error !== null}
          aria-describedby={`${groupId}-error`}
        />
      </div>
      <div
        id={`${groupId}-error`}
        className={styles.error}
        role="status"
        aria-live="polite"
      >
        {error ?? ""}
      </div>
    </div>
  );
}

export default NodeColorControl;
