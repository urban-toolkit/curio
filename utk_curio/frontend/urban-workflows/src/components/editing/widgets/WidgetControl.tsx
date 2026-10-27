import React, { useEffect, useId, useRef, useState } from "react";
import Button from "@mui/material/Button";
import Checkbox from "@mui/material/Checkbox";
import Chip from "@mui/material/Chip";
import FormControlLabel from "@mui/material/FormControlLabel";
import FormGroup from "@mui/material/FormGroup";
import InputAdornment from "@mui/material/InputAdornment";
import Radio from "@mui/material/Radio";
import RadioGroup from "@mui/material/RadioGroup";
import Slider from "@mui/material/Slider";
import TextField from "@mui/material/TextField";
import { ThemeProvider } from "@mui/material/styles";
import styles from "./WidgetTags.module.css";
import { LocationControl } from "./LocationControl";
import { widgetTheme } from "./widgetTheme";
import { useDatasetWidgetNode } from "./datasetWidgetContext";
import { tooltipStore } from "../../tooltip/tooltipStore";
import { CatalogFormatBadge } from "../../catalog/CatalogKindVisuals";
import {
  DATASET_FORMAT_LABEL,
  DATASET_IMPORT_ACCEPT,
  type DatasetFormat,
} from "../../../services/datasetCatalog/datasetCatalogTypes";
import {
  FILE_WIDGET_MAX_CHARS,
  checkWidgetValue,
  normalizeDate,
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
  if (type === "datetime" || type === "date") return typeof value === "string" ? value : "";
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
  const fileInput = useRef<HTMLInputElement>(null);
  // A dataset widget's node: the dataset's title, and the files it takes.
  const datasetNode = useDatasetWidgetNode();
  const sliderRef = useRef<HTMLSpanElement | null>(null);
  // A slider's value while its thumb is dragged: the press closed the hover
  // tooltip, so this one shows at the thumb until the drag ends.
  const dragTooltipKey = useId();
  const showDraggedValue = (text: string) => {
    const thumb = sliderRef.current?.querySelector(".MuiSlider-thumb") ?? null;
    if (!thumb) return;
    tooltipStore.show(
      {
        key: dragTooltipKey,
        target: null,
        anchor: () => (thumb.isConnected ? thumb.getBoundingClientRect() : null),
        anchorElement: thumb,
        side: "top",
        pointer: null,
        content: { kind: "text", text },
      },
      "pointer",
    );
  };

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
    } else if (widget.type === "date") {
      setDraft((d) => (normalizeDate(d) === value ? d : typeof value === "string" ? value : ""));
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
  // The units sit inside the number's field, at its end.
  const unitsAdornment = options.units
    ? { endAdornment: <InputAdornment position="end">{options.units}</InputAdornment> }
    : undefined;

  let control: React.ReactNode;
  switch (widget.type) {
    case "number":
      control = (
        <TextField
          type="number"
          fullWidth
          value={draft}
          disabled={disabled}
          inputProps={{ step: options.step ?? "any", min: options.min, max: options.max, "aria-label": label }}
          InputProps={unitsAdornment}
          onChange={(e) => {
            setDraft(e.target.value);
            commit(e.target.value.trim() === "" ? (NaN as number) : Number(e.target.value));
          }}
        />
      );
      break;
    case "slider": {
      const min = options.min ?? 0;
      const max = options.max ?? 100;
      const current = typeof value === "number" ? value : min;
      const valueText = (n: number) => `${n}${options.units ? ` ${options.units}` : ""}`;
      control = (
        <span className={styles.inline} style={{ gap: 12, paddingLeft: 6 }}>
          <Slider
            ref={sliderRef}
            aria-label={label}
            min={min}
            max={max}
            // Material UI has no "any" step: a hundredth of the span when none is set.
            step={options.step ?? (max - min) / 100}
            value={current}
            disabled={disabled}
            // The value shows in the Curio tooltip on the thumb, not in
            // Material UI's bubble, which grew with the canvas's zoom: while
            // the thumb is hovered or focused (its data-tooltip), and while
            // it is dragged.
            valueLabelDisplay="off"
            slotProps={{ thumb: { "data-tooltip": valueText(current) } as any }}
            marks={[
              { value: min, label: String(min) },
              { value: max, label: String(max) },
            ]}
            onChange={(event, next) => {
              const n = Array.isArray(next) ? next[0] : next;
              commit(n);
              if (/^(mouse|pointer|touch)/.test(event.type)) showDraggedValue(valueText(n));
            }}
            onChangeCommitted={() => tooltipStore.leave(dragTooltipKey)}
          />
          <output className={styles.units} style={{ whiteSpace: "nowrap" }}>
            {current}
            {options.units ? ` ${options.units}` : ""}
          </output>
        </span>
      );
      break;
    }
    case "text":
      control = (
        <TextField
          fullWidth
          value={typeof value === "string" ? value : ""}
          disabled={disabled}
          inputProps={{ "aria-label": label }}
          onChange={(e) => commit(e.target.value)}
        />
      );
      break;
    case "choice":
      control =
        options.display === "radio" ? (
          <RadioGroup
            row
            name={radioGroup}
            aria-label={label}
            value={typeof value === "string" ? value : ""}
            onChange={(e) => commit(e.target.value)}
          >
            {choices.map((choice) => (
              <FormControlLabel key={choice} value={choice} label={choice} disabled={disabled} control={<Radio />} />
            ))}
          </RadioGroup>
        ) : (
          // A native list: it opens at any zoom of the canvas.
          <TextField
            select
            fullWidth
            SelectProps={{ native: true }}
            value={typeof value === "string" ? value : ""}
            disabled={disabled}
            inputProps={{ "aria-label": label }}
            onChange={(e) => commit(e.target.value)}
          >
            {choices.map((choice) => (
              <option key={choice} value={choice}>
                {choice}
              </option>
            ))}
          </TextField>
        );
      break;
    case "checkbox-group": {
      const selected = chosen(value);
      control = (
        <FormGroup row role="group" aria-label={label}>
          {choices.map((choice) => (
            <FormControlLabel
              key={choice}
              label={choice}
              disabled={disabled}
              control={
                <Checkbox
                  checked={selected.includes(choice)}
                  // In the order of the choices, so the same picks are the same value.
                  onChange={(e) =>
                    commit(choices.filter((c) => (c === choice ? e.target.checked : selected.includes(c))))
                  }
                />
              }
            />
          ))}
        </FormGroup>
      );
      break;
    }
    case "multi-select": {
      const selected = chosen(value);
      const remaining = choices.filter((c) => !selected.includes(c));
      control = (
        <span className={styles.multi} style={{ gap: 6 }}>
          {selected.length > 0 ? (
            <span className={styles.picks} aria-label={`${label}: chosen`} style={{ gap: 4 }}>
              {selected.map((choice) => (
                <Chip
                  key={choice}
                  label={choice}
                  color="primary"
                  variant="outlined"
                  disabled={disabled}
                  // Material UI's chip takes Backspace and Delete even when
                  // disabled: disabled, it stays out of the tab order and
                  // removes nothing, as the disabled Remove button did.
                  skipFocusWhenDisabled
                  onDelete={() => {
                    if (!disabled) commit(selected.filter((c) => c !== choice));
                  }}
                  deleteIcon={
                    <span role="button" aria-label={`Remove ${choice}`} style={{ fontSize: 14, lineHeight: 1 }}>
                      ×
                    </span>
                  }
                />
              ))}
            </span>
          ) : null}
          <TextField
            select
            fullWidth
            SelectProps={{ native: true }}
            value=""
            disabled={disabled || remaining.length === 0}
            inputProps={{ "aria-label": label }}
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
          </TextField>
        </span>
      );
      break;
    }
    case "datetime":
      control = (
        <TextField
          type="datetime-local"
          fullWidth
          value={draft}
          disabled={disabled}
          inputProps={{ step: 1, "aria-label": label }}
          onChange={(e) => {
            setDraft(e.target.value);
            commit(normalizeDateTime(e.target.value) ?? e.target.value);
          }}
        />
      );
      break;
    case "date":
      control = (
        <TextField
          type="date"
          fullWidth
          value={draft}
          disabled={disabled}
          inputProps={{ "aria-label": label }}
          onChange={(e) => {
            setDraft(e.target.value);
            commit(normalizeDate(e.target.value) ?? e.target.value);
          }}
        />
      );
      break;
    case "location":
      control = <LocationControl value={value} onCommit={commit} label={label} disabled={disabled} />;
      break;
    case "checkbox":
      control = (
        <Checkbox
          checked={value === true}
          disabled={disabled}
          inputProps={{ "aria-label": label }}
          onChange={(e) => commit(e.target.checked)}
        />
      );
      break;
    case "number-list":
    case "text-list":
      control = (
        <TextField
          fullWidth
          value={draft}
          disabled={disabled}
          placeholder={widget.type === "number-list" ? "[1, 2, 3]" : '["a", "b"]'}
          inputProps={{ "aria-label": label }}
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
        <span style={{ display: "flex", gap: 6, alignItems: "center" }}>
          <TextField
            type="number"
            fullWidth
            value={rangeDraft[0]}
            disabled={disabled}
            inputProps={{ step: "any", "aria-label": `${label} from` }}
            onChange={(e) => update(0, e.target.value)}
          />
          <span className={styles.units}>to</span>
          <TextField
            type="number"
            fullWidth
            value={rangeDraft[1]}
            disabled={disabled}
            inputProps={{ step: "any", "aria-label": `${label} to` }}
            onChange={(e) => update(1, e.target.value)}
          />
        </span>
      );
      break;
    }
    case "file":
      control = (
        <span style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          <Button
            variant="outlined"
            component="label"
            disabled={disabled}
            // A label opens its file input on a click only: Enter and Space
            // open it too, as they did the browser's own file button.
            onKeyDown={(e: React.KeyboardEvent<HTMLLabelElement>) => {
              if (e.key !== "Enter" && e.key !== " ") return;
              e.preventDefault();
              fileInput.current?.click();
            }}
          >
            Choose file
            <input
              ref={fileInput}
              type="file"
              hidden
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
          </Button>
          <span className={styles.units}>
            {typeof value === "string" && value.length > 0
              ? `${value.length.toLocaleString("en-US")} characters loaded`
              : `No file yet (at most ${FILE_WIDGET_MAX_CHARS.toLocaleString("en-US")} characters)`}
          </span>
        </span>
      );
      break;
    case "dataset": {
      // Where a file or a Data Catalog dataset is dropped. The node takes the
      // drop on its whole card (NodeContainer), so this shows what it holds,
      // lights up while a drop is over the node, and offers Choose file.
      const id = typeof value === "string" ? value : "";
      const known = id ? datasetNode.describe(id) : undefined;
      const format = known?.format as DatasetFormat | undefined;
      const formatLabel = format ? DATASET_FORMAT_LABEL[format] : undefined;
      const canChoose = !disabled && datasetNode.takeFiles !== undefined;
      control = (
        <span
          className={`${styles.datasetDrop}${datasetNode.dropping ? ` ${styles.datasetDropActive}` : ""}`}
          data-dataset-drop={id ? "set" : "empty"}
        >
          {id ? (
            <>
              <span className={styles.datasetName} data-tooltip={id}>
                {known?.title || id}
              </span>
              {format && formatLabel ? <CatalogFormatBadge label={formatLabel} formatKey={format} /> : null}
            </>
          ) : (
            <span className={styles.datasetHint}>Drop a file or a Data Catalog dataset here</span>
          )}
          {canChoose ? (
            <Button
              variant="outlined"
              component="label"
              onKeyDown={(e: React.KeyboardEvent<HTMLLabelElement>) => {
                if (e.key !== "Enter" && e.key !== " ") return;
                e.preventDefault();
                fileInput.current?.click();
              }}
            >
              Choose file
              <input
                ref={fileInput}
                type="file"
                hidden
                aria-label={label}
                accept={DATASET_IMPORT_ACCEPT}
                onChange={(e) => {
                  const files = Array.from(e.target.files ?? []);
                  // The same file chosen again is a change too.
                  e.target.value = "";
                  if (files.length > 0) datasetNode.takeFiles?.(files);
                }}
              />
            </Button>
          ) : null}
        </span>
      );
      break;
    }
    default:
      control = null;
  }

  // Material UI's look, as SCOUT draws its widgets (widgetTheme). `nodrag` and
  // `nowheel`: dragging a slider or scrolling a list never moves the canvas.
  return (
    <ThemeProvider theme={widgetTheme}>
      <span className={`${styles.control} nodrag nowheel`}>
        {control}
        {problem ? <span className={styles.problem}>{problem}</span> : null}
      </span>
    </ThemeProvider>
  );
}

export default WidgetControl;
