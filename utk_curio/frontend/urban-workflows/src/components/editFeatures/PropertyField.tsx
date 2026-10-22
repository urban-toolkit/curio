/**
 * One property's field in a form of the Map Edits node's workbench (#662):
 * its name, whether it is required, a hint read off the values the layer
 * holds, and a control for its type.
 */
import React from "react";
import type { PropertyDef } from "../../utils/editFeatures/editFeatures";
import styles from "./EditFeatures.module.css";

/** The hint a field shows under its name, read off the values the layer holds. */
export function fieldHint(def: PropertyDef, fc: { features?: any[] } | undefined): string {
  const values = (fc?.features ?? []).map((f) => f?.properties?.[def.name]);
  const present = values.filter((v) => v !== null && v !== undefined && v !== "");
  const type = def.type === "boolean" ? "yes / no" : def.type;
  if (values.length === 0) return type;
  if (def.required) return `${type} · never empty here`;
  if (present.length < values.length / 2) return `${type} · often empty`;
  if (def.type === "number") {
    const numbers = present.filter((v): v is number => typeof v === "number");
    if (numbers.length > 0) return `number · ${Math.min(...numbers).toLocaleString()} to ${Math.max(...numbers).toLocaleString()}`;
  }
  if (def.type === "text") {
    const counts = new Map<string, number>();
    for (const v of present) counts.set(String(v), (counts.get(String(v)) ?? 0) + 1);
    const common = [...counts.entries()].filter(([, n]) => n > 1).sort((a, b) => b[1] - a[1]).slice(0, 2).map(([v]) => v);
    if (common.length > 0) return `text · e.g. ${common.join(", ")}`;
  }
  return type;
}

export function PropertyField({
  def,
  value,
  onChange,
  testId,
  hint,
}: {
  def: PropertyDef;
  value: string;
  onChange: (text: string) => void;
  testId: string;
  hint?: string;
}) {
  const label = (
    <span>
      <b>{def.name}</b>
      {def.required ? <span className={styles.required}> required</span> : null}
      <span className={styles.fieldHint}> {hint ?? def.type}</span>
    </span>
  );
  const choices = def.type === "boolean" ? ["true", "false"] : def.type === "choice" ? def.choices ?? [] : null;
  // A few choices are buttons, as the mockup has them; more are a menu.
  if (choices && choices.length <= 4) {
    const options = [...(def.required ? [] : [""]), ...choices];
    return (
      <div className={styles.formField}>
        {label}
        <span className={styles.segmented} role="group" aria-label={def.name} data-testid={testId}>
          {options.map((choice) => (
            <button key={choice || "empty"} type="button" aria-pressed={value === choice} className={`nodrag nopan ${value === choice ? styles.on : ""}`} onClick={() => onChange(choice)}>
              {choice === "" ? "empty" : choice === "true" ? "yes" : choice === "false" ? "no" : choice}
            </button>
          ))}
        </span>
      </div>
    );
  }
  let input: React.ReactNode;
  if (choices) {
    const other = value !== "" && !choices.includes(value);
    input = (
      <span className={styles.choiceRow}>
        <select className="nodrag nopan" aria-label={def.name} data-testid={testId} value={other ? "__other__" : value} onChange={(e) => onChange(e.target.value === "__other__" ? " " : e.target.value)}>
          <option value="">{def.required ? "Choose…" : "(empty)"}</option>
          {choices.map((choice) => (
            <option key={choice} value={choice}>
              {choice}
            </option>
          ))}
          <option value="__other__">other…</option>
        </select>
        {other ? <input className={`nodrag nopan ${styles.input}`} aria-label={`${def.name}, other value`} value={value.trimStart()} onChange={(e) => onChange(e.target.value)} /> : null}
      </span>
    );
  } else {
    input = (
      <input
        className={`nodrag nopan ${styles.input}`}
        aria-label={def.name}
        data-testid={testId}
        type={def.type === "date" ? "date" : "text"}
        inputMode={def.type === "number" ? "decimal" : undefined}
        placeholder={def.required ? undefined : "Leave empty if it has none"}
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
    );
  }
  return (
    <label className={styles.formField}>
      {label}
      {input}
    </label>
  );
}
