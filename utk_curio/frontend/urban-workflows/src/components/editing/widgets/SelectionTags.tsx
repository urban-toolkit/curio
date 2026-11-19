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

/** The choice a view is in the form's list: its node's id, or for one view of a node, the node's and the view's. */
const choiceOf = (view: SelectionView | undefined): string =>
  view === undefined ? "" : view.view === undefined ? view.id : JSON.stringify([view.id, view.view]);

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
  const [choice, setChoice] = useState(choiceOf(views[0]));
  const [read, setRead] = useState<Read>({ status: "reading" });
  const [column, setColumn] = useState("");
  const [name, setName] = useState(() => suggestTagName(views[0]?.label, taken));
  const [named, setNamed] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const view = views.find((v) => choiceOf(v) === choice);
  const viewId = view?.id ?? "";

  useEffect(() => {
    let current = true;
    setRead({ status: "reading" });
    setError(null);
    viewRowsOf(viewId, view?.layer).then((held) => {
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
  }, [choice]);

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
    selectionStateOf(viewId, column, undefined, view?.view).then((state) => {
      setSaving(false);
      if (state === null) {
        setError(`Run ${label} first: its rows are not known yet.`);
        return;
      }
      onSave({ name, node: viewId, ...(view?.view ? { view: view.view } : {}), column, ...state });
    });
  };

  return (
    <div className={styles.form} data-selection-form="true">
      <label>
        View
        <select aria-label="Selection view" value={choice} onChange={(e) => setChoice(e.target.value)}>
          {views.map((v) => (
            <option key={choiceOf(v)} value={choiceOf(v)}>
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
  // A tag on one view of a node is named after the node, then the view ("Node · heights").
  const labelOf = (id: string, view?: string) => {
    const own = views.find((v) => v.id === id && v.view === view)?.label;
    if (own) return own;
    const node = views.find((v) => v.id === id && v.view === undefined)?.label ?? id;
    return view === undefined ? node : `${node} · ${view}`;
  };
  return (
    <div className={styles.shared} data-selections-panel="true">
      <p className={styles.sharedHeading}>Selections</p>
      {selections.map((tag) => {
        const exists = allNodeIds.has(tag.node);
        const status = selectionStatus(tag, exists);
        return (
          <div key={tag.name} className={styles.row} data-selection-row={tag.name}>
            <span className={styles.rowLabel}>
              {exists ? labelOf(tag.node, tag.view) : "A deleted view"}, by {tag.column}
            </span>
            <SelectionTag name={tag.name} disabled={disabled} />
            <span
              className={exists && !isOverCap(tag) ? styles.sharedValue : styles.selectionProblem}
              data-selection-state={tag.name}
              data-tooltip={status}
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
