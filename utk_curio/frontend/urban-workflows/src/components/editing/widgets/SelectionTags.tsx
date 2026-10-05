import React, { useEffect, useState } from "react";
import styles from "./WidgetTags.module.css";
import { SelectionTag } from "./WidgetTag";
import { WIDGET_NAME_RE } from "../../../utils/widgets/widgetModel";
import {
  idColumns,
  isOverCap,
  overCapText,
  selectionSize,
  suggestTagName,
  type SelectionTag as SelectionTagDef,
} from "../../../utils/references/selectionTags";
import { selectionStateOf, viewRowsOf } from "../../../utils/references/viewSelections";
import type { SelectionView } from "../../../hook/useSelectionViews";

/** What a tag shows beside it: how many ids it holds, or why it holds none. */
export function selectionStatus(tag: SelectionTagDef, viewExists: boolean): string {
  if (!viewExists) return "Its view was deleted.";
  if (isOverCap(tag)) {
    const text = overCapText(selectionSize(tag));
    return text.charAt(0).toUpperCase() + text.slice(1);
  }
  const size = selectionSize(tag);
  return size === 0 ? "Nothing selected" : `${size} selected`;
}

type Read =
  | { status: "reading" }
  | { status: "none" }
  | { status: "ready"; columns: string[] };

/**
 * The form that adds a selection tag: a view, the column whose values identify
 * its rows, and a name. A view whose rows have no such column is refused.
 */
export function SelectionForm({
  views,
  taken,
  onSave,
  onCancel,
}: {
  views: SelectionView[];
  taken: string[];
  onSave: (tag: SelectionTagDef) => void;
  onCancel: () => void;
}) {
  const [viewId, setViewId] = useState(views[0]?.id ?? "");
  const [read, setRead] = useState<Read>({ status: "reading" });
  const [column, setColumn] = useState("");
  const [name, setName] = useState(() => suggestTagName(views[0]?.label, taken));
  const [named, setNamed] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const view = views.find((v) => v.id === viewId);

  useEffect(() => {
    let current = true;
    setRead({ status: "reading" });
    setError(null);
    viewRowsOf(viewId).then((held) => {
      if (!current) return;
      if (!held || held.rows.count === 0) {
        setRead({ status: "none" });
        return;
      }
      const columns = idColumns(held.rows, held.columns);
      setRead({ status: "ready", columns });
      setColumn(columns[0] ?? "");
    });
    if (!named) setName(suggestTagName(view?.label, taken));
    return () => {
      current = false;
    };
  }, [viewId]);

  const label = view?.label ?? viewId;
  const refusal =
    read.status === "none"
      ? `Run ${label} first: its rows are not known yet.`
      : read.status === "ready" && read.columns.length === 0
        ? `The rows of ${label} have no column that tells them apart, such as osm_id or building_id, so its selection cannot be named by id.`
        : null;
  const nameProblem = !WIDGET_NAME_RE.test(name)
    ? "A name is letters, digits and underscores, and does not start with a digit."
    : taken.includes(name)
      ? `This node already has a selection tag named ${name}.`
      : null;
  const problem = refusal ?? nameProblem ?? error;
  const ready = read.status === "ready" && column !== "" && refusal === null && nameProblem === null && !saving;

  const save = () => {
    setSaving(true);
    selectionStateOf(viewId, column).then((state) => {
      setSaving(false);
      if (state === null) {
        setError(`Run ${label} first: its rows are not known yet.`);
        return;
      }
      onSave({ name, node: viewId, column, ...state });
    });
  };

  return (
    <div className={styles.form} data-selection-form="true">
      <label>
        View
        <select aria-label="Selection view" value={viewId} onChange={(e) => setViewId(e.target.value)}>
          {views.map((v) => (
            <option key={v.id} value={v.id}>
              {v.label}
            </option>
          ))}
        </select>
      </label>
      {read.status === "reading" ? <p className={styles.hint}>Reading the rows of {label}...</p> : null}
      {read.status === "ready" && read.columns.length > 0 ? (
        <label>
          Identify the rows by
          <select aria-label="Selection id column" value={column} onChange={(e) => setColumn(e.target.value)}>
            {read.columns.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </label>
      ) : null}
      <label>
        Name
        <input
          type="text"
          aria-label="Selection tag name"
          value={name}
          onChange={(e) => {
            setName(e.target.value);
            setNamed(true);
          }}
        />
      </label>
      {problem ? (
        <p className={styles.problem} data-selection-problem="true">
          {problem}
        </p>
      ) : null}
      <span className={styles.formActions}>
        <button type="button" className={styles.button} onClick={onCancel}>
          Cancel
        </button>
        <button type="button" className={styles.primary} disabled={!ready} onClick={save}>
          Add selection tag
        </button>
      </span>
    </div>
  );
}

/**
 * A node's selection tags, in its Widgets tab (#662): each with the view it
 * reads and what that view's selection holds now. Nothing when the dataflow
 * has no view and the node no tag.
 */
export function SelectionSection({
  selections,
  onSelectionsChange,
  views,
  allNodeIds,
  disabled = false,
  locked = false,
}: {
  selections: SelectionTagDef[];
  onSelectionsChange: (next: SelectionTagDef[]) => void;
  views: SelectionView[];
  /** Every node of the dataflow, so a tag whose view was deleted says so. */
  allNodeIds: ReadonlySet<string>;
  disabled?: boolean;
  /** Another form in the tab is open. */
  locked?: boolean;
}) {
  const [adding, setAdding] = useState(false);
  if (selections.length === 0 && views.length === 0) return null;
  const labelOf = (id: string) => views.find((v) => v.id === id)?.label ?? id;
  return (
    <div className={styles.shared} data-selections-panel="true">
      <p className={styles.sharedHeading}>Selections</p>
      {selections.map((tag) => {
        const exists = allNodeIds.has(tag.node);
        const status = selectionStatus(tag, exists);
        return (
          <div key={tag.name} className={styles.row} data-selection-row={tag.name}>
            <span className={styles.rowLabel}>
              {exists ? labelOf(tag.node) : "A deleted view"}, by {tag.column}
            </span>
            <SelectionTag name={tag.name} disabled={disabled} />
            <span
              className={exists && !isOverCap(tag) ? styles.sharedValue : styles.selectionProblem}
              data-selection-state={tag.name}
              title={status}
            >
              {status}
            </span>
            <span className={styles.rowActions}>
              <button
                type="button"
                className={styles.danger}
                aria-label={`Delete selection tag ${tag.name}`}
                disabled={disabled || locked || adding}
                onClick={() => onSelectionsChange(selections.filter((t) => t.name !== tag.name))}
              >
                Delete
              </button>
            </span>
          </div>
        );
      })}
      {adding ? (
        <SelectionForm
          views={views}
          taken={selections.map((t) => t.name)}
          onSave={(tag) => {
            onSelectionsChange([...selections, tag]);
            setAdding(false);
          }}
          onCancel={() => setAdding(false)}
        />
      ) : views.length > 0 ? (
        <button
          type="button"
          className={`${styles.button} ${styles.add}`}
          disabled={disabled || locked}
          onClick={() => setAdding(true)}
        >
          Add selection
        </button>
      ) : null}
    </div>
  );
}

export default SelectionSection;
