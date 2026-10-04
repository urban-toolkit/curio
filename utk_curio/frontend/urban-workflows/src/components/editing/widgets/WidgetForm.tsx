import React, { useState } from "react";
import styles from "./WidgetTags.module.css";
import { WidgetControl } from "./WidgetControl";
import {
  WIDGET_KINDS,
  WIDGET_KIND_LABELS,
  checkWidgetDef,
  defaultValueFor,
  type WidgetDef,
  type WidgetKind,
  type WidgetValue,
} from "../../../utils/widgets/widgetModel";

const parseChoices = (text: string): string[] =>
  text
    .split(",")
    .map((c) => c.trim())
    .filter((c) => c.length > 0);

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
  const [def, setDef] = useState<WidgetValue>(initial ? initial.default : defaultValueFor("number"));

  const choices = parseChoices(choicesText);
  const candidate: WidgetDef = {
    name: name.trim(),
    type,
    default: def,
    ...(label.trim() ? { label: label.trim() } : {}),
    ...(type === "choice" ? { options: { choices } } : {}),
  };
  const problem = checkWidgetDef(candidate, others);

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
            setDef(defaultValueFor(next, choices));
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
      {type === "choice" ? (
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
              if (typeof def !== "string" || !next.includes(def)) setDef(next[0] ?? "");
            }}
          />
        </label>
      ) : null}
      <label>
        Default
        <WidgetControl widget={candidate} value={def} onChange={setDef} ariaLabel="Widget default" />
      </label>
      {problem ? <p className={styles.problem}>{problem}</p> : null}
      <span className={styles.formActions}>
        <button type="button" disabled={problem !== null} onClick={() => onSave(candidate)}>
          {initial ? "Save widget" : "Add widget"}
        </button>
        <button type="button" onClick={onCancel}>
          Cancel
        </button>
      </span>
    </div>
  );
}

export default WidgetForm;
