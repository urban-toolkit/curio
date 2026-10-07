import React from "react";

import type { DiscoveryAreaValue, DiscoveryParameter } from "../../services/discoveryCatalog";
import { AreaField, boxProblem } from "./AreaField";
import { findBoundary, noBoundaryCalled } from "./placeSearch";
import { MAX_TAGS, TAG_ENTRY_RE, TagsField } from "./TagsField";
import styles from "./DiscoveryAddDialog.module.css";

/**
 * The questions a source declares, as one form: an area, a date range, a
 * choice, a number, a yes or no, a text, a link or OpenStreetMap tags
 * (`domain/parameters.py`).
 *
 * Drawn from the manifest's declarations, so a source that asks something new
 * needs no new page. The server checks every answer again; this form only
 * keeps a person from sending one it would refuse.
 */

export type ParameterValues = Record<string, unknown>;

/** The starting answers: each parameter's declared default, if it has one. */
export function initialValues(parameters: DiscoveryParameter[]): ParameterValues {
  const out: ParameterValues = {};
  for (const p of parameters) if (p.default !== undefined) out[p.id] = p.default;
  return out;
}

/** The answers to send: empty optional ones left out. */
export function answered(parameters: DiscoveryParameter[], values: ParameterValues): ParameterValues {
  const out: ParameterValues = {};
  for (const p of parameters) {
    const v = values[p.id];
    if (v === undefined || v === null || v === "" || (Array.isArray(v) && v.length === 0)) continue;
    out[p.id] = v;
  }
  return out;
}

/** The first thing wrong with the answers, in words, or null. */
export function parameterProblem(parameters: DiscoveryParameter[], values: ParameterValues): string | null {
  for (const p of parameters) {
    const v = values[p.id];
    const empty = v === undefined || v === null || v === "" || (Array.isArray(v) && v.length === 0);
    if (empty) {
      if (p.required) return `${p.label} is needed.`;
      continue;
    }
    if (p.type === "area") {
      const area = v as DiscoveryAreaValue;
      if ("box" in area) {
        const problem = boxProblem(area.box, p.maxAreaKm2);
        if (problem) return `${p.label}: ${problem}`;
      } else if (!area.names?.geocodeArea || !area.names.areas?.length) {
        return `${p.label} needs a place and at least one area.`;
      }
    }
    if (p.type === "number" || p.type === "integer") {
      const n = Number(v);
      if (!Number.isFinite(n)) return `${p.label} takes a number.`;
      if (p.type === "integer" && !Number.isInteger(n)) return `${p.label} takes a whole number.`;
      if (p.min != null && n < p.min) return `${p.label} is at least ${p.min}.`;
      if (p.max != null && n > p.max) return `${p.label} is at most ${p.max}.`;
    }
    if (p.type === "dateRange") {
      const range = v as { start?: string; end?: string };
      if (range.start && range.end && range.start > range.end) return `${p.label} starts after it ends.`;
    }
    if (p.type === "url" && !String(v).trim().startsWith("https://")) return `${p.label} must be an https link.`;
    if (p.type === "tags") {
      const entries = Array.isArray(v) ? (v as unknown[]) : [];
      if (entries.length > MAX_TAGS) return `${p.label} takes at most ${MAX_TAGS} tags.`;
      const bad = entries.find((entry) => typeof entry !== "string" || !TAG_ENTRY_RE.test(entry));
      if (bad !== undefined) return `${p.label}: "${String(bad)}" is not a tag.`;
    }
  }
  return null;
}

/** Whether an answer is named areas, whose place a download looks up first. */
export function hasNamedAreas(parameters: DiscoveryParameter[], values: ParameterValues): boolean {
  return parameters.some((p) => {
    const v = values[p.id];
    return p.type === "area" && typeof v === "object" && v !== null && "names" in v;
  });
}

/**
 * The answers as a download sends them: each named area's place as
 * OpenStreetMap names it, looked up as **Within** looks it up. The server
 * keeps what the place search answered, so a place the field already found
 * is not asked for again. Resolves to the answers, or to what is wrong.
 */
export async function withOsmPlaceNames(
  parameters: DiscoveryParameter[],
  values: ParameterValues,
): Promise<ParameterValues | string> {
  const out: ParameterValues = { ...values };
  for (const p of parameters) {
    const area = values[p.id] as DiscoveryAreaValue | undefined;
    if (p.type !== "area" || !area || !("names" in area)) continue;
    const place = await findBoundary(area.names.geocodeArea);
    if (!place) return `${p.label}: ${noBoundaryCalled(area.names.geocodeArea)}`;
    out[p.id] = { names: { ...area.names, geocodeArea: place.name } };
  }
  return out;
}

export interface SourceParameterFormProps {
  parameters: DiscoveryParameter[];
  values: ParameterValues;
  onChange: (values: ParameterValues) => void;
}

export function SourceParameterForm({ parameters, values, onChange }: SourceParameterFormProps) {
  const set = (id: string, value: unknown) => onChange({ ...values, [id]: value });
  return (
    <>
      {parameters.map((p) =>
        p.type === "area" ? (
          <AreaField
            key={p.id}
            parameter={p}
            value={(values[p.id] as DiscoveryAreaValue | undefined) ?? null}
            onChange={(v) => set(p.id, v)}
          />
        ) : p.type === "tags" ? (
          <TagsField key={p.id} parameter={p} value={values[p.id]} onChange={(v) => set(p.id, v)} />
        ) : (
          <ParameterField key={p.id} parameter={p} value={values[p.id]} onChange={(v) => set(p.id, v)} />
        ),
      )}
    </>
  );
}

function ParameterField({
  parameter: p,
  value,
  onChange,
}: {
  parameter: DiscoveryParameter;
  value: unknown;
  onChange: (value: unknown) => void;
}) {
  const id = `discovery-parameter-${p.id}`;
  const label = (
    <>
      {p.label}
      {p.unit ? ` (${p.unit})` : null}
      {p.required ? null : <span className={styles.hint}> optional</span>}
    </>
  );
  const hint = p.description ? <span className={styles.hint}>{p.description}</span> : null;

  if (p.type === "boolean") {
    return (
      <label className={styles.value} data-parameter={p.id}>
        <input type="checkbox" checked={Boolean(value)} onChange={(e) => onChange(e.target.checked)} />
        {p.label}
        {hint}
      </label>
    );
  }

  if (p.type === "choice" && p.multiple) {
    const picked = new Set(Array.isArray(value) ? (value as string[]) : []);
    return (
      <fieldset className={styles.fieldset} data-parameter={p.id}>
        <legend className={styles.fieldLabel}>{label}</legend>
        {hint}
        <div className={styles.values}>
          {(p.options ?? []).map((o) => (
            <label key={o.value} className={styles.value}>
              <input
                type="checkbox"
                checked={picked.has(o.value)}
                onChange={() => {
                  const next = new Set(picked);
                  if (next.has(o.value)) next.delete(o.value);
                  else next.add(o.value);
                  onChange((p.options ?? []).map((x) => x.value).filter((v) => next.has(v)));
                }}
              />
              {o.label}
            </label>
          ))}
        </div>
      </fieldset>
    );
  }

  if (p.type === "dateRange") {
    const range = (value as { start?: string; end?: string } | undefined) ?? {};
    const update = (bound: "start" | "end", day: string) => {
      const next = { ...range, [bound]: day || undefined };
      onChange(next.start || next.end ? next : null);
    };
    return (
      <fieldset className={styles.fieldset} data-parameter={p.id}>
        <legend className={styles.fieldLabel}>{label}</legend>
        {hint}
        <div className={styles.range}>
          <input
            className={styles.input}
            type="date"
            aria-label={`${p.label} from`}
            min={p.minDate}
            max={p.maxDate}
            value={range.start ?? ""}
            onChange={(e) => update("start", e.target.value)}
          />
          <span>to</span>
          <input
            className={styles.input}
            type="date"
            aria-label={`${p.label} to`}
            min={p.minDate}
            max={p.maxDate}
            value={range.end ?? ""}
            onChange={(e) => update("end", e.target.value)}
          />
        </div>
      </fieldset>
    );
  }

  return (
    <label className={styles.field} htmlFor={id} data-parameter={p.id}>
      <span className={styles.fieldLabel}>{label}</span>
      {p.type === "choice" ? (
        <select
          id={id}
          className={styles.input}
          value={(value as string | undefined) ?? ""}
          onChange={(e) => onChange(e.target.value || null)}
        >
          {p.required ? null : <option value="">Any</option>}
          {(p.options ?? []).map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      ) : (
        <input
          id={id}
          className={styles.input}
          type={p.type === "number" || p.type === "integer" ? "number" : p.type === "url" ? "url" : "text"}
          min={p.min}
          max={p.max}
          step={p.step ?? (p.type === "integer" ? 1 : undefined)}
          placeholder={p.type === "url" ? "https://" : undefined}
          value={value === undefined || value === null ? "" : String(value)}
          onChange={(e) => {
            const raw = e.target.value;
            if (p.type === "number" || p.type === "integer") onChange(raw === "" ? null : Number(raw));
            else onChange(raw);
          }}
        />
      )}
      {hint}
    </label>
  );
}

export default SourceParameterForm;
