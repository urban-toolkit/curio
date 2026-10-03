import React, { useEffect, useState } from "react";
import styles from "./WidgetTags.module.css";
import {
  FILE_WIDGET_MAX_CHARS,
  checkWidgetValue,
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

/**
 * The control for one widget (#662). A value reaches `onChange` only when it
 * is valid for the widget; what the user is still typing stays in the control.
 */
export function WidgetControl({ widget, value, onChange, disabled = false, ariaLabel }: Props) {
  const label = ariaLabel ?? widget.label ?? widget.name;
  const [draft, setDraft] = useState<string>(() =>
    widget.type === "number" ? String(value ?? "") : listText(value),
  );
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
    }
    setProblem(null);
  }, [valueKey, widget.type]);

  const commit = (candidate: WidgetValue) => {
    const why = checkWidgetValue(widget, candidate);
    setProblem(why);
    if (why === null) onChange(candidate);
  };

  let control: React.ReactNode;
  switch (widget.type) {
    case "number":
      control = (
        <input
          type="number"
          step="any"
          aria-label={label}
          value={draft}
          disabled={disabled}
          onChange={(e) => {
            setDraft(e.target.value);
            commit(e.target.value.trim() === "" ? (NaN as number) : Number(e.target.value));
          }}
        />
      );
      break;
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
      control = (
        <select
          aria-label={label}
          value={typeof value === "string" ? value : ""}
          disabled={disabled}
          onChange={(e) => commit(e.target.value)}
        >
          {(widget.options?.choices ?? []).map((choice) => (
            <option key={choice} value={choice}>
              {choice}
            </option>
          ))}
        </select>
      );
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
