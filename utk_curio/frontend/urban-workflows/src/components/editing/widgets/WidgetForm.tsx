import React, { useState } from "react";
import styles from "./WidgetTags.module.css";
import { WidgetControl } from "./WidgetControl";
import {
  CHOICE_KINDS,
  NUMERIC_KINDS,
  WIDGET_KINDS,
  WIDGET_KIND_LABELS,
  checkWidgetDef,
  dateTimeValue,
  defaultValueFor,
  type WidgetDef,
  type WidgetKind,
  type WidgetOptions,
  type WidgetValue,
} from "../../../utils/widgets/widgetModel";

const parseChoices = (text: string): string[] =>
  text
    .split(",")
    .map((c) => c.trim())
    .filter((c) => c.length > 0);

/** A typed bound or step: a number, or nothing when the field is empty. */
const parseNumber = (text: string): number | undefined => (text.trim() === "" ? undefined : Number(text));

const numberText = (n: number | undefined) => (n === undefined ? "" : String(n));

/**
 * Adding a widget, or editing one (#662). An existing widget keeps its name:
 * the code's references name it, so a new name is a new widget.
 */
export function WidgetForm({
  initial,
  others,
  onSave,
  onCancel,
}: {
  initial?: WidgetDef;
  others: WidgetDef[];
  onSave: (def: WidgetDef) => void;
  onCancel: () => void;
}) {
  const [name, setName] = useState(initial?.name ?? "");
  const [type, setType] = useState<WidgetKind>(initial?.type ?? "number");
  const [label, setLabel] = useState(initial?.label ?? "");
  const [choicesText, setChoicesText] = useState((initial?.options?.choices ?? []).join(", "));
  const [display, setDisplay] = useState<"dropdown" | "radio">(initial?.options?.display ?? "dropdown");
  const [minText, setMinText] = useState(numberText(initial?.options?.min));
  const [maxText, setMaxText] = useState(numberText(initial?.options?.max));
  const [stepText, setStepText] = useState(numberText(initial?.options?.step));
  const [units, setUnits] = useState(initial?.options?.units ?? "");
  const [def, setDef] = useState<WidgetValue>(initial ? initial.default : defaultValueFor("number"));

  const choices = parseChoices(choicesText);
  const bounds = { min: parseNumber(minText), max: parseNumber(maxText), step: parseNumber(stepText) };

  const optionsFor = (kind: WidgetKind): WidgetOptions | undefined => {
    if (CHOICE_KINDS.includes(kind)) {
      return { choices, ...(kind === "choice" && display === "radio" ? { display } : {}) };
    }
    if (NUMERIC_KINDS.includes(kind)) {
      const out: WidgetOptions = {};
      if (bounds.min !== undefined) out.min = bounds.min;
      if (bounds.max !== undefined) out.max = bounds.max;
      if (bounds.step !== undefined) out.step = bounds.step;
      if (units.trim()) out.units = units.trim();
      return Object.keys(out).length > 0 ? out : undefined;
    }
    return undefined;
  };

  const options = optionsFor(type);
  const candidate: WidgetDef = {
    name: name.trim(),
    type,
    default: def,
    ...(label.trim() ? { label: label.trim() } : {}),
    ...(options ? { options } : {}),
  };
  const problem = checkWidgetDef(candidate, others);

  // A slider's default follows its bounds, so a new bound does not leave it outside.
  const setBound = (which: "min" | "max", text: string) => {
    (which === "min" ? setMinText : setMaxText)(text);
    const bound = parseNumber(text);
    if (type !== "slider" || typeof def !== "number" || bound === undefined || !Number.isFinite(bound)) return;
    if ((which === "min" && def < bound) || (which === "max" && def > bound)) setDef(bound);
  };

  return (
    <div className={styles.form} data-widget-form="true">
      <label>
        Name
        <input
          type="text"
          aria-label="Widget name"
          value={name}
          disabled={initial !== undefined}
          placeholder="season"
          onChange={(e) => setName(e.target.value)}
        />
      </label>
      <label>
        Type
        <select
          aria-label="Widget type"
          value={type}
          onChange={(e) => {
            const next = e.target.value as WidgetKind;
            setType(next);
            if (next === "slider" && minText === "" && maxText === "") {
              // A slider needs bounds; start it at 0 to 100.
              setMinText("0");
              setMaxText("100");
              setDef(0);
            } else if (next === "datetime") {
              setDef(dateTimeValue(new Date()));
            } else {
              setDef(defaultValueFor(next, optionsFor(next)));
            }
          }}
        >
          {WIDGET_KINDS.map((kind) => (
            <option key={kind} value={kind}>
              {WIDGET_KIND_LABELS[kind]}
            </option>
          ))}
        </select>
      </label>
      <label>
        Label
        <input
          type="text"
          aria-label="Widget label"
          value={label}
          placeholder="Shown beside the control"
          onChange={(e) => setLabel(e.target.value)}
        />
      </label>
      {CHOICE_KINDS.includes(type) ? (
        <label>
          Choices, separated by commas
          <input
            type="text"
            aria-label="Widget choices"
            value={choicesText}
            placeholder="summer, winter"
            onChange={(e) => {
              setChoicesText(e.target.value);
              const next = parseChoices(e.target.value);
              if (type === "choice") {
                if (typeof def !== "string" || !next.includes(def)) setDef(next[0] ?? "");
              } else {
                setDef(next.filter((c) => Array.isArray(def) && (def as unknown[]).includes(c)));
              }
            }}
          />
        </label>
      ) : null}
      {type === "choice" ? (
        <label>
          Show as
          <select
            aria-label="Widget display"
            value={display}
            onChange={(e) => setDisplay(e.target.value as "dropdown" | "radio")}
          >
            <option value="dropdown">A dropdown</option>
            <option value="radio">Radio buttons</option>
          </select>
        </label>
      ) : null}
      {NUMERIC_KINDS.includes(type) ? (
        <span className={styles.bounds}>
          <label>
            Minimum
            <input
              type="number"
              step="any"
              aria-label="Widget minimum"
              value={minText}
              placeholder={type === "slider" ? "" : "none"}
              onChange={(e) => setBound("min", e.target.value)}
            />
          </label>
          <label>
            Maximum
            <input
              type="number"
              step="any"
              aria-label="Widget maximum"
              value={maxText}
              placeholder={type === "slider" ? "" : "none"}
              onChange={(e) => setBound("max", e.target.value)}
            />
          </label>
          <label>
            Step
            <input
              type="number"
              step="any"
              aria-label="Widget step"
              value={stepText}
              placeholder="any"
              onChange={(e) => setStepText(e.target.value)}
            />
          </label>
          <label>
            Units
            <input
              type="text"
              aria-label="Widget units"
              value={units}
              placeholder="m, %"
              onChange={(e) => setUnits(e.target.value)}
            />
          </label>
        </span>
      ) : null}
      <div className={styles.field}>
        Default
        <WidgetControl widget={candidate} value={def} onChange={setDef} ariaLabel="Widget default" />
      </div>
      {problem ? <p className={styles.problem}>{problem}</p> : null}
      <span className={styles.formActions}>
        <button type="button" className={styles.button} onClick={onCancel}>
          Cancel
        </button>
        <button type="button" className={styles.primary} disabled={problem !== null} onClick={() => onSave(candidate)}>
          {initial ? "Save widget" : "Add widget"}
        </button>
      </span>
    </div>
  );
}

export default WidgetForm;
