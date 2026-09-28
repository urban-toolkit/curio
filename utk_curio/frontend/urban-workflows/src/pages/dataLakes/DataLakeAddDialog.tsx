import React from "react";

import ConfirmDialog from "../../components/ConfirmDialog";
import type {
  LakeAcquireBody,
  LakeFieldFilter,
  LakeFieldValues,
  LakeResourceRow,
} from "../../services/dataLakeCatalog";
import styles from "./DataLakeAddDialog.module.css";

/**
 * Add a storage row to the Data Catalog, all of it or some of it.
 *
 * Each path field the row is not already split by can narrow the add: tick
 * the values to keep when the row lists them, or set a range when it has too
 * many to list. Leaving every field as it opens adds the whole row.
 */

export interface DataLakeAddDialogProps {
  resource: LakeResourceRow;
  /** Fields the row is split by, which it cannot be narrowed by again. */
  splitBy: string[];
  onAdd: (body: LakeAcquireBody) => void;
  onCancel: () => void;
}

/** The fields a row can be narrowed by. */
export function narrowableFields(resource: LakeResourceRow, splitBy: string[]): LakeFieldValues[] {
  return (resource.fieldValues ?? []).filter(
    (field) => !splitBy.includes(field.name) && field.distinct > 1,
  );
}

type Choice = { kind: "values"; kept: Set<string> } | { kind: "range"; min: string; max: string };

function initialChoice(field: LakeFieldValues): Choice {
  if (field.values) return { kind: "values", kept: new Set(field.values) };
  return { kind: "range", min: field.min ?? "", max: field.max ?? "" };
}

/** What is wrong with a range, in words, or null when it selects files. */
export function rangeProblem(field: LakeFieldValues, min: string, max: string): string | null {
  const low = min.trim();
  const high = max.trim();
  if (!low || !high) return `${field.name} needs both ends of its range.`;
  if (field.type === "int") {
    if (!/^-?\d+$/.test(low) || !/^-?\d+$/.test(high)) return `${field.name} takes whole numbers.`;
    return Number(low) > Number(high) ? `${field.name} starts after it ends.` : null;
  }
  if (field.type === "date") {
    const day = /^\d{4}-\d{2}-\d{2}$/;
    if (!day.test(low) || !day.test(high)) return `${field.name} takes dates like 2024-05-01.`;
  } else if (field.type === "datetime") {
    if (Number.isNaN(Date.parse(low)) || Number.isNaN(Date.parse(high))) {
      return `${field.name} takes times like 2024-05-01T06:00:00.`;
    }
  }
  return low > high ? `${field.name} starts after it ends.` : null;
}

/** The filters the choices amount to, leaving out every field kept whole. */
export function filtersOf(
  fields: LakeFieldValues[],
  choices: Record<string, Choice>,
): Record<string, LakeFieldFilter> {
  const out: Record<string, LakeFieldFilter> = {};
  for (const field of fields) {
    const choice = choices[field.name];
    if (!choice) continue;
    if (choice.kind === "values") {
      if (field.values && choice.kept.size < field.values.length) {
        out[field.name] = field.values.filter((v) => choice.kept.has(v));
      }
    } else if (choice.min !== field.min || choice.max !== field.max) {
      out[field.name] = { min: choice.min, max: choice.max };
    }
  }
  return out;
}

export function DataLakeAddDialog({ resource, splitBy, onAdd, onCancel }: DataLakeAddDialogProps) {
  const fields = React.useMemo(() => narrowableFields(resource, splitBy), [resource, splitBy]);
  const [choices, setChoices] = React.useState<Record<string, Choice>>(() =>
    Object.fromEntries(fields.map((field) => [field.name, initialChoice(field)])),
  );
  const [title, setTitle] = React.useState(resource.name);

  const empty = Object.values(choices).some((c) => c.kind === "values" && c.kept.size === 0);
  const problem =
    fields
      .map((field) => {
        const choice = choices[field.name];
        return choice?.kind === "range" ? rangeProblem(field, choice.min, choice.max) : null;
      })
      .find(Boolean) ?? null;
  const filters = filtersOf(fields, choices);
  const narrowed = Object.keys(filters).length > 0;

  const toggle = (name: string, value: string) =>
    setChoices((prev) => {
      const choice = prev[name];
      if (choice?.kind !== "values") return prev;
      const kept = new Set(choice.kept);
      if (kept.has(value)) kept.delete(value);
      else kept.add(value);
      return { ...prev, [name]: { kind: "values", kept } };
    });

  const setBound = (name: string, bound: "min" | "max", value: string) =>
    setChoices((prev) => {
      const choice = prev[name];
      if (choice?.kind !== "range") return prev;
      return { ...prev, [name]: { ...choice, [bound]: value } };
    });

  const body = (
    <div className={styles.form}>
      <p className={styles.lede}>
        {narrowed
          ? "Only the files whose fields match what is kept below are added."
          : `All ${(resource.fileCount ?? 0).toLocaleString()} files are added.`}
      </p>
      <label className={styles.field}>
        <span className={styles.fieldLabel}>Name in your Data Catalog</span>
        <input
          className={styles.input}
          value={title}
          onChange={(e) => setTitle(e.target.value)}
        />
      </label>
      {fields.map((field) => {
        const choice = choices[field.name];
        return (
          <fieldset key={field.name} className={styles.fieldset}>
            <legend className={styles.fieldLabel}>{field.name}</legend>
            {choice?.kind === "values" ? (
              <div className={styles.values}>
                {(field.values ?? []).map((value) => (
                  <label key={value} className={styles.value}>
                    <input
                      type="checkbox"
                      checked={choice.kept.has(value)}
                      onChange={() => toggle(field.name, value)}
                    />
                    {value}
                  </label>
                ))}
              </div>
            ) : choice?.kind === "range" ? (
              <div className={styles.range}>
                <input
                  className={styles.input}
                  aria-label={`${field.name} from`}
                  value={choice.min}
                  onChange={(e) => setBound(field.name, "min", e.target.value)}
                />
                <span>to</span>
                <input
                  className={styles.input}
                  aria-label={`${field.name} to`}
                  value={choice.max}
                  onChange={(e) => setBound(field.name, "max", e.target.value)}
                />
              </div>
            ) : null}
          </fieldset>
        );
      })}
      {empty ? <p className={styles.warning}>Keep at least one value of every field.</p> : null}
      {problem ? <p className={styles.warning}>{problem}</p> : null}
    </div>
  );

  return (
    <ConfirmDialog
      title={`Add ${resource.name}`}
      body={body}
      confirmLabel="Add to Data Catalog"
      onCancel={onCancel}
      onConfirm={() => {
        // A field with nothing kept, or a range that cannot hold a value,
        // selects no file; the warning says so.
        if (empty || problem) return;
        onAdd({ title: title.trim() || resource.name, ...(narrowed ? { filters } : {}) });
      }}
    />
  );
}

export default DataLakeAddDialog;
