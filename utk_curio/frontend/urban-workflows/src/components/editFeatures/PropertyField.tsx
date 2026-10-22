/**
 * One property's field in a form of the Map Edits node's workbench (#662):
 * its name, whether it is required, a hint read off the values the layer
 * holds, and a widget's control for its type (`fields`): a few choices as a
 * radio group, more as a list, else a text field.
 */
import React, { useId } from "react";
import type { PropertyDef } from "../../utils/editFeatures/editFeatures";
import { RadioChoices, SelectInput, TextInput } from "./fields";
import { TYPE_LABEL } from "./workbenchParts";
import styles from "./EditFeatures.module.css";

/** The hint a field shows beside its name, read off the values the layer holds. */
export function fieldHint(def: PropertyDef, fc: { features?: any[] } | undefined): string {
  const values = (fc?.features ?? []).map((f) => f?.properties?.[def.name]);
  const present = values.filter((v) => v !== null && v !== undefined && v !== "");
  const type = TYPE_LABEL[def.type];
  if (values.length === 0) return type;
  if (def.required) return `${type} · never empty here`;
  if (present.length < values.length / 2) return `${type} · often empty`;
  if (def.type === "number") {
    const numbers = present.filter((v): v is number => typeof v === "number");
    if (numbers.length > 0) return `${type} · ${Math.min(...numbers).toLocaleString()} to ${Math.max(...numbers).toLocaleString()}`;
  }
  if (def.type === "text") {
    const counts = new Map<string, number>();
    for (const v of present) counts.set(String(v), (counts.get(String(v)) ?? 0) + 1);
    const common = [...counts.entries()].filter(([, n]) => n > 1).sort((a, b) => b[1] - a[1]).slice(0, 2).map(([v]) => v);
    if (common.length > 0) return `${type} · e.g. ${common.join(", ")}`;
  }
  return type;
}

/** How a choice reads: the empty one, yes and no for a Yes / no property, else itself. */
const choiceLabel = (choice: string) => (choice === "" ? "Empty" : choice === "true" ? "Yes" : choice === "false" ? "No" : choice);

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
  const id = useId();
  const choices = def.type === "boolean" ? ["true", "false"] : def.type === "choice" ? def.choices ?? [] : null;
  // A few choices are a radio group, as a widget's choice can be; more are a list.
  const radios = !!choices && choices.length <= 4;
  const name = (
    <>
      <span className={styles.fieldName}>{def.name}</span>
      {def.required ? <span className={styles.required}> required</span> : null}
      <span className={styles.hint}> {hint ?? TYPE_LABEL[def.type]}</span>
    </>
  );
  // A radio group is named by its own label; a field by this one.
  const head = radios ? <span>{name}</span> : <label htmlFor={id}>{name}</label>;
  let input: React.ReactNode;
  if (choices && radios) {
    const options = [...(def.required ? [] : [""]), ...choices];
    input = (
      <RadioChoices label={def.name} testId={testId} value={value} onChange={onChange} options={options.map((choice) => ({ value: choice, label: choiceLabel(choice) }))} />
    );
  } else if (choices) {
    const other = value !== "" && !choices.includes(value);
    input = (
      <span className={styles.choiceRow}>
        <SelectInput id={id} label={def.name} testId={testId} value={other ? "__other__" : value} onChange={(next) => onChange(next === "__other__" ? " " : next)}>
          <option value="">{def.required ? "Choose…" : "(empty)"}</option>
          {choices.map((choice) => (
            <option key={choice} value={choice}>
              {choice}
            </option>
          ))}
          <option value="__other__">other…</option>
        </SelectInput>
        {other ? <TextInput label={`${def.name}, other value`} value={value.trimStart()} onChange={onChange} /> : null}
      </span>
    );
  } else {
    input = (
      <TextInput
        id={id}
        label={def.name}
        testId={testId}
        type={def.type === "date" ? "date" : "text"}
        inputMode={def.type === "number" ? "decimal" : undefined}
        placeholder={def.required ? undefined : "Leave empty if it has none"}
        value={value}
        onChange={onChange}
      />
    );
  }
  return (
    <div className={styles.field}>
      {head}
      {input}
    </div>
  );
}
