import React from "react";

import ConfirmDialog from "../../components/ConfirmDialog";
import type {
  DiscoveryAcquireBody,
  DiscoveryFieldFilter,
  DiscoveryFieldValues,
  DiscoveryParameter,
  DiscoveryResource,
} from "../../services/discoveryCatalog";
import styles from "./DiscoveryAddDialog.module.css";
import {
  SourceParameterForm,
  answered,
  hasNamedAreas,
  initialValues,
  parameterProblem,
  withOsmPlaceNames,
  type ParameterValues,
} from "./SourceParameterForm";

/**
 * Add a row to the Data Catalog, all of it or some of it.
 *
 * The questions its source declares come first (an area, a date range; see
 * `SourceParameterForm`). Then, for a storage row, each path field the row is
 * not already split by can narrow the add: tick the values to keep when the
 * row lists them, or set a range when it has too many to list. Leaving every
 * field as it opens adds the whole row.
 */

export interface DiscoveryAddDialogProps {
  resource: DiscoveryResource;
  /** Fields the row is split by, which it cannot be narrowed by again. */
  splitBy: string[];
  /** What the row's source asks before an add; defaults to the row's own. */
  parameters?: DiscoveryParameter[];
  /** "download" for a portal row narrowed before its download. */
  verb?: "add" | "download";
  /** A service row: the dataset is named after the place unless a name is
   *  typed, so the field starts empty. */
  titleFromPlace?: boolean;
  onAdd: (body: DiscoveryAcquireBody) => void;
  onCancel: () => void;
}

/** The fields a row can be narrowed by. */
export function narrowableFields(resource: DiscoveryResource, splitBy: string[]): DiscoveryFieldValues[] {
  return (resource.fieldValues ?? []).filter(
    (field) => !splitBy.includes(field.name) && field.distinct > 1,
  );
}

type Choice = { kind: "values"; kept: Set<string> } | { kind: "range"; min: string; max: string };

function initialChoice(field: DiscoveryFieldValues): Choice {
  if (field.values) return { kind: "values", kept: new Set(field.values) };
  return { kind: "range", min: field.min ?? "", max: field.max ?? "" };
}

/** What is wrong with a range, in words, or null when it selects files. */
export function rangeProblem(field: DiscoveryFieldValues, min: string, max: string): string | null {
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
  fields: DiscoveryFieldValues[],
  choices: Record<string, Choice>,
): Record<string, DiscoveryFieldFilter> {
  const out: Record<string, DiscoveryFieldFilter> = {};
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

export function DiscoveryAddDialog({
  resource,
  splitBy,
  parameters: declared,
  verb = "add",
  titleFromPlace = false,
  onAdd,
  onCancel,
}: DiscoveryAddDialogProps) {
  const fields = React.useMemo(() => narrowableFields(resource, splitBy), [resource, splitBy]);
  const parameters = React.useMemo(() => declared ?? resource.parameters ?? [], [declared, resource]);
  const [values, setValues] = React.useState<ParameterValues>(() => initialValues(parameters));
  const parameterIssue = parameterProblem(parameters, values);
  // A named area's place, looked up when the add is asked for, and what was wrong with it.
  const [lookingUp, setLookingUp] = React.useState(false);
  const [placeIssue, setPlaceIssue] = React.useState<string | null>(null);
  const [choices, setChoices] = React.useState<Record<string, Choice>>(() =>
    Object.fromEntries(fields.map((field) => [field.name, initialChoice(field)])),
  );
  const [title, setTitle] = React.useState(titleFromPlace ? "" : resource.name);

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
  const answers = answered(parameters, values);
  const asked = Object.keys(answers).length > 0;

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
      {fields.length > 0 ? (
        <p className={styles.lede}>
          {narrowed
            ? "Only the files whose fields match what is kept below are added."
            : `All ${(resource.fileCount ?? 0).toLocaleString()} files are added.`}
        </p>
      ) : null}
      <label className={styles.field}>
        <span className={styles.fieldLabel}>Name in your Data Catalog</span>
        <input
          className={styles.input}
          value={title}
          placeholder={titleFromPlace ? `${resource.name}, and the place it covers` : undefined}
          onChange={(e) => setTitle(e.target.value)}
        />
      </label>
      <SourceParameterForm
        parameters={parameters}
        values={values}
        onChange={(next) => {
          setValues(next);
          setPlaceIssue(null);
        }}
      />
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
      {parameterIssue ? <p className={styles.warning}>{parameterIssue}</p> : null}
      {placeIssue ? <p className={styles.warning}>{placeIssue}</p> : null}
    </div>
  );

  return (
    <ConfirmDialog
      title={verb === "download" ? `Download ${resource.name}` : `Add ${resource.name}`}
      body={body}
      confirmLabel={verb === "download" ? "Download" : "Add to Data Catalog"}
      busy={lookingUp}
      onCancel={onCancel}
      onConfirm={() => {
        // A field with nothing kept, or a range that cannot hold a value,
        // selects no file; the warning says so.
        if (empty || problem || parameterIssue || lookingUp) return;
        const named = title.trim() || (titleFromPlace ? "" : resource.name);
        const add = (sent: ParameterValues) =>
          onAdd({
            ...(named ? { title: named } : {}),
            ...(narrowed ? { filters } : {}),
            ...(asked ? { parameters: sent } : {}),
          });
        if (!hasNamedAreas(parameters, answers)) {
          add(answers);
          return;
        }
        // The loader matches a named area's place by its OpenStreetMap name,
        // so the place is looked up first, and one not found is not sent.
        setLookingUp(true);
        setPlaceIssue(null);
        withOsmPlaceNames(parameters, answers).then(
          (sent) => {
            setLookingUp(false);
            if (typeof sent === "string") setPlaceIssue(sent);
            else add(sent);
          },
          (err: Error) => {
            setLookingUp(false);
            setPlaceIssue(err.message || "The place search did not answer.");
          },
        );
      }}
    />
  );
}

export default DiscoveryAddDialog;
