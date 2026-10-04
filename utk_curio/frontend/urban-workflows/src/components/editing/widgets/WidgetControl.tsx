import React, { useEffect, useId, useState } from "react";
import styles from "./WidgetTags.module.css";
import { LocationControl } from "./LocationControl";
import {
  FILE_WIDGET_MAX_CHARS,
  checkWidgetValue,
  normalizeDateTime,
  type WidgetDef,
  type WidgetValue,
} from "../../../utils/widgets/widgetModel";

type Props = {
  widget: Pick<WidgetDef, "name" | "type" | "options" | "label">;
  value: WidgetValue | undefined;
  onChange: (value: WidgetValue) => void;
  disabled?: boolean;
  /** The accessible name of the control; the widget's label by default. */
  ariaLabel?: string;
};

const listText = (value: WidgetValue | undefined) => (Array.isArray(value) ? JSON.stringify(value) : "[]");

const initialDraft = (type: WidgetDef["type"], value: WidgetValue | undefined): string => {
  if (type === "number") return String(value ?? "");
  if (type === "datetime") return typeof value === "string" ? value : "";
  return listText(value);
};

/** The strings in a list value. */
const chosen = (value: WidgetValue | undefined): string[] =>
  Array.isArray(value) ? (value as unknown[]).filter((v): v is string => typeof v === "string") : [];

/**
 * The control for one widget (#662). A value reaches `onChange` only when it
 * is valid for the widget; what the user is still typing stays in the control.
 */
export function WidgetControl({ widget, value, onChange, disabled = false, ariaLabel }: Props) {
  const label = ariaLabel ?? widget.label ?? widget.name;
  // One radio group per control: two nodes' widgets may share a name.
  const radioGroup = useId();
  const [draft, setDraft] = useState<string>(() => initialDraft(widget.type, value));
  const [rangeDraft, setRangeDraft] = useState<[string, string]>(() =>
    Array.isArray(value) && value.length === 2 ? [String(value[0]), String(value[1])] : ["", ""],
  );
  const [problem, setProblem] = useState<string | null>(null);

  // A value set from outside (a load, another control) replaces the draft. A
  // draft that already says the value is kept, so "1." is not cut to "1"
  // while it is being typed.
  const valueKey = JSON.stringify(value ?? null);
  useEffect(() => {
    if (widget.type === "number") {
      setDraft((d) =>
        d.trim() !== "" && Number(d) === value ? d : value === undefined || value === null ? "" : String(value),
      );
    } else if (widget.type === "number-list" || widget.type === "text-list") {
      setDraft((d) => {
        try {
          if (JSON.stringify(JSON.parse(d)) === valueKey) return d;
        } catch {
          // not a list yet: replaced below
        }
        return listText(value);
      });
    } else if (widget.type === "range" && Array.isArray(value) && value.length === 2) {
      setRangeDraft((d) =>
        Number(d[0]) === value[0] && Number(d[1]) === value[1] ? d : [String(value[0]), String(value[1])],
      );
    } else if (widget.type === "datetime") {
      setDraft((d) => (normalizeDateTime(d) === value ? d : typeof value === "string" ? value : ""));
    }
    setProblem(null);
  }, [valueKey, widget.type]);

  const commit = (candidate: WidgetValue) => {
    const why = checkWidgetValue(widget, candidate);
    setProblem(why);
    if (why === null) onChange(candidate);
  };

  const options = widget.options ?? {};
  const choices = options.choices ?? [];
  const units = options.units ? <span className={styles.units}>{options.units}</span> : null;

  let control: React.ReactNode;
  switch (widget.type) {
    case "number": {
      const input = (
        <input
          type="number"
          step={options.step ?? "any"}
          min={options.min}
          max={options.max}
          aria-label={label}
          value={draft}
          disabled={disabled}
          onChange={(e) => {
            setDraft(e.target.value);
            commit(e.target.value.trim() === "" ? (NaN as number) : Number(e.target.value));
          }}
        />
      );
      control = units ? (
        <span className={styles.inline}>
          {input}
          {units}
        </span>
      ) : (
        input
      );
      break;
    }
    case "slider": {
      const min = options.min ?? 0;
      const max = options.max ?? 100;
      const current = typeof value === "number" ? value : min;
      control = (
        <span className={styles.inline}>
          <input
            type="range"
            aria-label={label}
            min={min}
            max={max}
            step={options.step ?? "any"}
            value={current}
            disabled={disabled}
            onChange={(e) => commit(Number(e.target.value))}
          />
          <output className={styles.units}>
            {current}
            {options.units ? ` ${options.units}` : ""}
          </output>
        </span>
      );
      break;
    }
    case "text":
      control = (
        <input
          type="text"
          aria-label={label}
          value={typeof value === "string" ? value : ""}
          disabled={disabled}
          onChange={(e) => commit(e.target.value)}
        />
      );
      break;
    case "choice":
      control =
        options.display === "radio" ? (
          <span role="radiogroup" aria-label={label} className={styles.choices}>
            {choices.map((choice) => (
              <label key={choice} className={styles.choiceItem}>
                <input
                  type="radio"
                  name={radioGroup}
                  value={choice}
                  checked={value === choice}
                  disabled={disabled}
                  onChange={() => commit(choice)}
                />
                {choice}
              </label>
            ))}
          </span>
        ) : (
          <select
            aria-label={label}
            value={typeof value === "string" ? value : ""}
            disabled={disabled}
            onChange={(e) => commit(e.target.value)}
          >
            {choices.map((choice) => (
              <option key={choice} value={choice}>
                {choice}
              </option>
            ))}
          </select>
        );
      break;
    case "checkbox-group": {
      const selected = chosen(value);
      control = (
        <span role="group" aria-label={label} className={styles.choices}>
          {choices.map((choice) => (
            <label key={choice} className={styles.choiceItem}>
              <input
                type="checkbox"
                checked={selected.includes(choice)}
                disabled={disabled}
                // In the order of the choices, so the same picks are the same value.
                onChange={(e) =>
                  commit(choices.filter((c) => (c === choice ? e.target.checked : selected.includes(c))))
                }
              />
              {choice}
            </label>
          ))}
        </span>
      );
      break;
    }
    case "multi-select": {
      const selected = chosen(value);
      const remaining = choices.filter((c) => !selected.includes(c));
      control = (
        <span className={styles.multi}>
          {selected.length > 0 ? (
            <span className={styles.picks} aria-label={`${label}: chosen`}>
              {selected.map((choice) => (
                <span key={choice} className={styles.pick}>
                  {choice}
                  <button
                    type="button"
                    aria-label={`Remove ${choice}`}
                    disabled={disabled}
                    onClick={() => commit(selected.filter((c) => c !== choice))}
                  >
                    ×
                  </button>
                </span>
              ))}
            </span>
          ) : null}
          <select
            aria-label={label}
            value=""
            disabled={disabled || remaining.length === 0}
            onChange={(e) => {
              const added = e.target.value;
              if (added) commit(choices.filter((c) => c === added || selected.includes(c)));
            }}
          >
            <option value="">{remaining.length > 0 ? "Add a choice…" : "All chosen"}</option>
            {remaining.map((choice) => (
              <option key={choice} value={choice}>
                {choice}
              </option>
            ))}
          </select>
        </span>
      );
      break;
    }
    case "datetime":
      control = (
        <input
          type="datetime-local"
          step={1}
          aria-label={label}
          value={draft}
          disabled={disabled}
          onChange={(e) => {
            setDraft(e.target.value);
            commit(normalizeDateTime(e.target.value) ?? e.target.value);
          }}
        />
      );
      break;
    case "location":
      control = <LocationControl value={value} onCommit={commit} label={label} disabled={disabled} />;
      break;
    case "checkbox":
      control = (
        <input
          type="checkbox"
          aria-label={label}
          checked={value === true}
          disabled={disabled}
          onChange={(e) => commit(e.target.checked)}
        />
      );
      break;
    case "number-list":
    case "text-list":
      control = (
        <input
          type="text"
          aria-label={label}
          value={draft}
          disabled={disabled}
          onChange={(e) => {
            setDraft(e.target.value);
            let parsed: unknown;
            try {
              parsed = JSON.parse(e.target.value);
            } catch {
              parsed = undefined;
            }
            commit(parsed as WidgetValue);
          }}
        />
      );
      break;
    case "range": {
      const update = (index: 0 | 1, text: string) => {
        const next: [string, string] = index === 0 ? [text, rangeDraft[1]] : [rangeDraft[0], text];
        setRangeDraft(next);
        const nums = next.map((t) => (t.trim() === "" ? NaN : Number(t)));
        commit(nums as number[]);
      };
      control = (
        <span style={{ display: "flex", gap: 4 }}>
          <input
            type="number"
            step="any"
            aria-label={`${label} from`}
            value={rangeDraft[0]}
            disabled={disabled}
            onChange={(e) => update(0, e.target.value)}
          />
          <input
            type="number"
            step="any"
            aria-label={`${label} to`}
            value={rangeDraft[1]}
            disabled={disabled}
            onChange={(e) => update(1, e.target.value)}
          />
        </span>
      );
      break;
    }
    case "file":
      control = (
        <span style={{ display: "flex", flexDirection: "column", gap: 2 }}>
          <input
            type="file"
            aria-label={label}
            accept=".txt, .csv, .json, .geojson, .tsv"
            disabled={disabled}
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (!file) return;
              const reader = new FileReader();
              reader.onload = () => commit(typeof reader.result === "string" ? reader.result : "");
              reader.onerror = () => setProblem("The file could not be read.");
              reader.readAsText(file);
            }}
          />
          <span>
            {typeof value === "string" && value.length > 0
              ? `${value.length.toLocaleString("en-US")} characters loaded`
              : `No file yet (at most ${FILE_WIDGET_MAX_CHARS.toLocaleString("en-US")} characters)`}
          </span>
        </span>
      );
      break;
    default:
      control = null;
  }

  return (
    <span className={styles.control}>
      {control}
      {problem ? <span className={styles.problem}>{problem}</span> : null}
    </span>
  );
}

export default WidgetControl;
