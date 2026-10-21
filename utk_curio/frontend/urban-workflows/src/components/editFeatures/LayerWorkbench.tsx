/**
 * The Interaction node's layer workbench (#662), as the Interaction Node Flow
 * mockups draw it: the layers the node is fed, and
 * what can be done with each layer, one step at a time.
 *
 * 1. The layers, as cards grouped by the geometry their features have
 *    (points, lines, areas): the name, where it came from and how many
 *    features it holds, and its properties. + New data layer makes one: a
 *    name, its geometry and the properties its features carry.
 * 2. A layer picked: what to do with it, four cards: Add (draw on the map,
 *    then fill in the layer's own properties, the values it holds offered as
 *    choices), Edit (pick a feature on the map, reshape or move it, change its
 *    values), Remove (pick features on the map, or by a rule) and Add a
 *    property (a new column with a value for every feature).
 * 3. The action: its form here, its drawing on the map.
 *
 * The node is linked to an Autark map (*mapId*), and the drawing happens on
 * that map (`MapEditOverlay`, through `mapEditBus`). Every action becomes an
 * entry of the node's edit log, through *onEdit*.
 */
import React, { useEffect, useMemo, useRef, useState } from "react";
import type { SelectionId } from "../../utils/references/selectionTags";
import {
  NEW_LAYER_GEOMETRIES,
  PROPERTY_TYPES,
  type EditValue,
  type FeatureEdit,
  type Geometry,
  type NewLayerDef,
  type NewLayerGeometry,
  type PropertyDef,
  type PropertyType,
} from "../../utils/editFeatures/editFeatures";
import {
  GEOMETRY_KIND,
  KIND_GEOMETRY,
  KIND_LABEL,
  KIND_NOUN,
  editedFeatures,
  formDefaults,
  formProblems,
  formValue,
  formValues,
  geometryKinds,
  mainKind,
  nextId,
  propertiesFor,
  type EditedFeature,
  type GeometryKind,
} from "../../utils/editFeatures/layerModel";
import { evaluate, exprProblem, parseExpr, truthy } from "../../utils/editFeatures/editExpr";
import { publishMapSession, type MapEditMode } from "../../utils/editFeatures/mapEditBus";
import { partsOf, withPart } from "../../utils/editFeatures/geometryParts";
import styles from "./EditFeatures.module.css";


/** A layer the workbench offers: one of the input's, or one the node makes. */
export interface WorkbenchLayer {
  /** Its name in the edit log: the input's layer name, or the new layer's. */
  name: string;
  /** Shown in the list. */
  label: string;
  /** The table the map draws it as (`input_0`), when it is one of the input's. */
  table?: string;
  fc: { features?: any[]; crs?: any };
  /** The column that identifies its features, or undefined when it has none. */
  key?: string;
  /** Set for a layer the node makes. */
  newLayer?: NewLayerDef;
}

export type Action = "add" | "edit" | "remove" | "property";

/** Whether *fc*'s coordinates are longitude-latitude. */
export function isGeographic(fc: { features?: any[]; crs?: any } | undefined): boolean {
  const name = String(fc?.crs?.properties?.name ?? "");
  if (/3395|3857|900913/.test(name)) return false;
  if (/4326|CRS84/.test(name)) return true;
  let geographic = true;
  let seen = 0;
  for (const f of (fc?.features ?? []).slice(0, 30)) {
    const walk = (v: any) => {
      if (!Array.isArray(v)) return;
      if (typeof v[0] === "number") {
        seen += 1;
        if (Math.abs(v[0]) > 180 || Math.abs(v[1]) > 90) geographic = false;
      } else v.forEach(walk);
    };
    walk(f?.geometry?.coordinates);
  }
  return seen > 0 && geographic;
}

/** The CRS name a drawn shape in *fc*'s coordinates is in. */
export function crsName(fc: { features?: any[]; crs?: any } | undefined): string {
  const name = String(fc?.crs?.properties?.name ?? "");
  const code = /EPSG::?(\d+)/.exec(name);
  if (code) return `EPSG:${code[1]}`;
  if (/CRS84/.test(name)) return "EPSG:4326";
  return isGeographic(fc) ? "EPSG:4326" : "EPSG:3395";
}

/** An on/off switch: a way of changing the picked feature's shape. */
function ShapeSwitch({ on, icon, label, testId, onToggle }: { on: boolean; icon: "points" | "whole"; label: string; testId: string; onToggle: () => void }) {
  return (
    <button type="button" role="switch" aria-checked={on} data-testid={testId} className={`nodrag nopan ${styles.switch} ${on ? styles.switchOn : ""}`} onClick={onToggle}>
      <svg className={styles.switchIcon} width={18} height={18} viewBox="0 0 18 18" aria-hidden="true">
        {icon === "points" ? (
          <>
            <polyline points="3,14 8,4 15,9" fill="none" stroke="currentColor" strokeWidth={1.6} strokeLinejoin="round" />
            <rect x={1.5} y={12.5} width={3} height={3} fill="#FFFFFF" stroke="currentColor" strokeWidth={1.4} />
            <rect x={6.5} y={2.5} width={3} height={3} fill="#FFFFFF" stroke="currentColor" strokeWidth={1.4} />
            <rect x={13.5} y={7.5} width={3} height={3} fill="#FFFFFF" stroke="currentColor" strokeWidth={1.4} />
          </>
        ) : (
          <path d="M9 1.5v15M1.5 9h15M9 1.5l-2.2 2.2M9 1.5l2.2 2.2M9 16.5l-2.2-2.2M9 16.5l2.2-2.2M1.5 9l2.2-2.2M1.5 9l2.2 2.2M16.5 9l-2.2-2.2M16.5 9l-2.2 2.2" fill="none" stroke="currentColor" strokeWidth={1.6} strokeLinecap="round" />
        )}
      </svg>
      <span className={styles.switchLabel}>{label}</span>
      <span className={styles.switchTrack} aria-hidden="true">
        <span className={styles.switchKnob} />
      </span>
      <span className={styles.switchState} aria-hidden="true">{on ? "On" : "Off"}</span>
    </button>
  );
}

const plural = (n: number, one: string, many: string) => `${n.toLocaleString()} ${n === 1 ? one : many}`;

function KindIcon({ kind, size = 16 }: { kind: GeometryKind; size?: number }) {
  if (kind === "points") {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
        <circle cx="12" cy="12" r="5" />
      </svg>
    );
  }
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d={kind === "lines" ? "M4 18L10 8l4 6 6-9" : "M5 7l8-3 6 7-4 9-10-3z"} />
    </svg>
  );
}

/** The hint a field shows under its name, read off the values the layer holds. */
function fieldHint(def: PropertyDef, fc: { features?: any[] } | undefined): string {
  const values = (fc?.features ?? []).map((f) => f?.properties?.[def.name]);
  const present = values.filter((v) => v !== null && v !== undefined && v !== "");
  const type = def.type === "boolean" ? "yes / no" : def.type;
  if (values.length === 0) return type;
  if (def.required) return `${type} · never empty here`;
  if (present.length < values.length / 2) return `${type} · often empty`;
  if (def.type === "number") {
    const numbers = present.filter((v): v is number => typeof v === "number");
    if (numbers.length > 0) return `number · ${Math.min(...numbers).toLocaleString()} to ${Math.max(...numbers).toLocaleString()}`;
  }
  if (def.type === "text") {
    const counts = new Map<string, number>();
    for (const v of present) counts.set(String(v), (counts.get(String(v)) ?? 0) + 1);
    const common = [...counts.entries()].filter(([, n]) => n > 1).sort((a, b) => b[1] - a[1]).slice(0, 2).map(([v]) => v);
    if (common.length > 0) return `text · e.g. ${common.join(", ")}`;
  }
  return type;
}

function PropertyField({
  def,
  value,
  onChange,
  testId,
  hint,
}: {
  def: PropertyDef;
  value: string;
  onChange: (text: string) => void;
  testId: string;
  hint?: string;
}) {
  const label = (
    <span>
      <b>{def.name}</b>
      {def.required ? <span className={styles.required}> required</span> : null}
      <span className={styles.fieldHint}> {hint ?? def.type}</span>
    </span>
  );
  const choices = def.type === "boolean" ? ["true", "false"] : def.type === "choice" ? def.choices ?? [] : null;
  // A few choices are buttons, as the mockup has them; more are a menu.
  if (choices && choices.length <= 4) {
    const options = [...(def.required ? [] : [""]), ...choices];
    return (
      <div className={styles.formField}>
        {label}
        <span className={styles.segmented} role="group" aria-label={def.name} data-testid={testId}>
          {options.map((choice) => (
            <button key={choice || "empty"} type="button" aria-pressed={value === choice} className={`nodrag nopan ${value === choice ? styles.on : ""}`} onClick={() => onChange(choice)}>
              {choice === "" ? "empty" : choice === "true" ? "yes" : choice === "false" ? "no" : choice}
            </button>
          ))}
        </span>
      </div>
    );
  }
  let input: React.ReactNode;
  if (choices) {
    const other = value !== "" && !choices.includes(value);
    input = (
      <span className={styles.choiceRow}>
        <select className="nodrag nopan" aria-label={def.name} data-testid={testId} value={other ? "__other__" : value} onChange={(e) => onChange(e.target.value === "__other__" ? " " : e.target.value)}>
          <option value="">{def.required ? "Choose…" : "(empty)"}</option>
          {choices.map((choice) => (
            <option key={choice} value={choice}>
              {choice}
            </option>
          ))}
          <option value="__other__">other…</option>
        </select>
        {other ? <input className={`nodrag nopan ${styles.input}`} aria-label={`${def.name}, other value`} value={value.trimStart()} onChange={(e) => onChange(e.target.value)} /> : null}
      </span>
    );
  } else {
    input = (
      <input
        className={`nodrag nopan ${styles.input}`}
        aria-label={def.name}
        data-testid={testId}
        type={def.type === "date" ? "date" : "text"}
        inputMode={def.type === "number" ? "decimal" : undefined}
        placeholder={def.required ? undefined : "Leave empty if it has none"}
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
    );
  }
  return (
    <label className={styles.formField}>
      {label}
      {input}
    </label>
  );
}

/** The builder of a new layer: its name, its geometry and its properties. */
function NewLayerForm({ taken, onCreate, onCancel }: { taken: string[]; onCreate: (def: NewLayerDef) => void; onCancel: () => void }) {
  const [name, setName] = useState("");
  const [geometry, setGeometry] = useState<NewLayerGeometry>("Point");
  const [props, setProps] = useState<{ name: string; type: PropertyType; required: boolean; choices: string; def: string }[]>([
    { name: "name", type: "text", required: true, choices: "", def: "" },
  ]);
  const trimmed = name.trim();
  const problem = trimmed === "" ? "Name the layer" : taken.includes(trimmed) ? "The map already has a layer with that name" : null;
  const update = (i: number, patch: Partial<(typeof props)[number]>) => setProps(props.map((p, j) => (j === i ? { ...p, ...patch } : p)));
  const create = () => {
    if (problem) return;
    const properties: PropertyDef[] = props
      .filter((p) => p.name.trim() !== "")
      .map((p) => ({
        name: p.name.trim(),
        type: p.type,
        ...(p.required ? { required: true } : {}),
        ...(p.type === "choice" ? { choices: p.choices.split(",").map((c) => c.trim()).filter(Boolean) } : {}),
        ...(p.def.trim() !== "" ? { default: p.type === "number" && Number.isFinite(Number(p.def)) ? Number(p.def) : p.def.trim() } : {}),
      }));
    onCreate({ name: trimmed, geometry, ...(properties.length > 0 ? { properties } : {}) });
  };
  return (
    <div className={styles.form} data-testid="interaction-new-layer">
      <button type="button" className={`nodrag nopan ${styles.back}`} onClick={onCancel}>
        ← All layers
      </button>
      <span className={styles.title}>New data layer</span>
      <label className={styles.formField}>
        <b>Name</b>
        <input className={`nodrag nopan ${styles.input}`} aria-label="Layer name" data-testid="interaction-new-layer-name" value={name} placeholder="Cooling centers" onChange={(e) => setName(e.target.value)} />
      </label>
      <div className={styles.formField}>
        <b>Geometry</b>
        <span className={styles.segmented} role="group" aria-label="Geometry">
          {NEW_LAYER_GEOMETRIES.map((g) => (
            <button key={g} type="button" aria-pressed={geometry === g} data-testid={`interaction-new-layer-${g}`} className={`nodrag nopan ${geometry === g ? styles.on : ""}`} onClick={() => setGeometry(g)}>
              <KindIcon kind={GEOMETRY_KIND[g]} size={14} />
              {KIND_LABEL[GEOMETRY_KIND[g]]}
            </button>
          ))}
        </span>
      </div>
      <div className={styles.formField}>
        <b>Properties</b>
        <div className={styles.propGrid}>
          <span className={styles.head}>Name</span>
          <span className={styles.head}>Type</span>
          <span className={styles.head}>Choices or default</span>
          <span className={styles.head}>Required</span>
          <span />
          {props.map((p, i) => (
            <React.Fragment key={i}>
              <input className={`nodrag nopan ${styles.input}`} aria-label={`Property ${i + 1} name`} value={p.name} onChange={(e) => update(i, { name: e.target.value })} />
              <select className="nodrag nopan" aria-label={`Property ${i + 1} type`} value={p.type} onChange={(e) => update(i, { type: e.target.value as PropertyType })}>
                {PROPERTY_TYPES.map((t) => (
                  <option key={t} value={t}>
                    {t === "boolean" ? "Yes / no" : t[0].toUpperCase() + t.slice(1)}
                  </option>
                ))}
              </select>
              {p.type === "choice" ? (
                <input className={`nodrag nopan ${styles.input}`} aria-label={`Property ${i + 1} choices`} placeholder="library, school, …" value={p.choices} onChange={(e) => update(i, { choices: e.target.value })} />
              ) : (
                <input className={`nodrag nopan ${styles.input}`} aria-label={`Property ${i + 1} default`} placeholder="default" value={p.def} onChange={(e) => update(i, { def: e.target.value })} />
              )}
              <input type="checkbox" className="nodrag nopan" aria-label={`Property ${i + 1} required`} checked={p.required} onChange={(e) => update(i, { required: e.target.checked })} />
              <button type="button" className={`nodrag nopan ${styles.delete}`} aria-label={`Remove property ${i + 1}`} onClick={() => setProps(props.filter((_, j) => j !== i))}>
                ×
              </button>
            </React.Fragment>
          ))}
        </div>
        <button type="button" className={`nodrag nopan ${styles.small} ${styles.dashed}`} data-testid="interaction-new-layer-add-property" onClick={() => setProps([...props, { name: "", type: "text", required: false, choices: "", def: "" }])}>
          + Add property
        </button>
        <span className={styles.hint}>Types: Text, Number, Yes / no, Choice, Date.</span>
      </div>
      {problem && name !== "" ? <span className={styles.problem}>{problem}</span> : null}
      <span className={styles.formButtons}>
        <button type="button" className={`nodrag nopan ${styles.big} ${styles.primary}`} data-testid="interaction-new-layer-create" disabled={problem !== null} onClick={create}>
          Create layer and start drawing
        </button>
        <button type="button" className={`nodrag nopan ${styles.big} ${styles.secondary}`} onClick={onCancel}>
          Cancel
        </button>
      </span>
    </div>
  );
}

/**
 * *defs* with the columns the log's "Add a property" edits give the layer
 * *layerName*: a property added is one its features are asked for, and one
 * they are edited by, like the columns the layer came with.
 */
export function withAddedColumns(
  defs: PropertyDef[],
  edits: readonly FeatureEdit[],
  layerName: string,
  nodeLayer: string | null,
): PropertyDef[] {
  const out = [...defs];
  for (const edit of edits) {
    if (edit.op !== "add_column" || edit.enabled === false || !edit.column) continue;
    if ((edit.layer ?? nodeLayer ?? null) !== layerName || out.some((d) => d.name === edit.column)) continue;
    const type: PropertyType = typeof edit.value === "number" ? "number" : typeof edit.value === "boolean" ? "boolean" : "text";
    out.push({ name: edit.column, type });
  }
  return out;
}

/** A rule's test: what the column is compared by. */
const TESTS = ["is", "is not", ">", "<", "is empty", "is not empty"] as const;
type Test = (typeof TESTS)[number];
/**
 * What a rule, or a change to several picked features, does in one column
 * (ops of `curio_edit_features`): set a value, or, in a number column, the
 * result of an expression.
 */
type RuleOp = "set" | "expr";
const RULE_OPS: { op: RuleOp; label: string }[] = [
  { op: "set", label: "Set to" },
  { op: "expr", label: "Set to the expression" },
];
interface Condition {
  column: string;
  test: Test;
  value: string;
}

const columnRef = (column: string) => (/^[A-Za-z_][A-Za-z0-9_]*$/.test(column) ? column : `\`${column}\``);
const literal = (def: PropertyDef | undefined, text: string) => {
  if (def?.type === "number" && text.trim() !== "" && Number.isFinite(Number(text))) return String(Number(text));
  if (def?.type === "boolean") return /^(true|yes)$/i.test(text) ? "true" : "false";
  return JSON.stringify(text);
};

/** The conditions as one `where` the log reads, or null while one is unfinished. */
export function ruleText(conditions: readonly Condition[], defs: readonly PropertyDef[]): string | null {
  const parts: string[] = [];
  for (const c of conditions) {
    if (!c.column) return null;
    const col = columnRef(c.column);
    const def = defs.find((d) => d.name === c.column);
    if (c.test === "is empty") parts.push(`(${col} == null or ${col} == "")`);
    else if (c.test === "is not empty") parts.push(`(${col} != null and ${col} != "")`);
    else {
      if (c.value.trim() === "") return null;
      const op = c.test === "is" ? "==" : c.test === "is not" ? "!=" : c.test;
      parts.push(`${col} ${op} ${literal(def, c.value)}`);
    }
  }
  return parts.length > 0 ? parts.join(" and ") : null;
}

/** The id the shape drawn but not yet added goes by, on the map. */
const DRAFT = "__drawn__";

export default function LayerWorkbench({
  layers,
  edits,
  nodeLayer,
  writable,
  picked,
  setPicked,
  onEdit,
  onEdits,
  onNewLayer,
  onAddLayerProperty,
  mapId,
  nodeId = "",
}: {
  layers: WorkbenchLayer[];
  edits: readonly FeatureEdit[];
  /** The layer the log's edits apply to when they name none. */
  nodeLayer: string | null;
  writable: boolean;
  /** The features picked in the layer being worked on. */
  picked: SelectionId[];
  setPicked: (ids: SelectionId[]) => void;
  /** One entry for the log, on *layer*. */
  onEdit: (edit: FeatureEdit, layer: WorkbenchLayer) => void;
  /** Several entries at once, on *layer*. */
  onEdits: (edits: FeatureEdit[], layer: WorkbenchLayer) => void;
  onNewLayer: (def: NewLayerDef) => void;
  onAddLayerProperty: (layerName: string, def: PropertyDef) => void;
  /** The Autark map the node is linked to: the drawing happens there. */
  mapId: string;
  nodeId?: string;
}) {
  const [activeName, setActiveName] = useState<string | null>(null);
  const [action, setAction] = useState<Action | null>(null);
  const [creating, setCreating] = useState(false);
  const [drawn, setDrawn] = useState<Geometry | null>(null);
  const [texts, setTexts] = useState<Record<string, string>>({});
  // How the picked feature's shape is changed, or null: neither, and a drag pans the map.
  const [shapeMode, setShapeMode] = useState<"reshape" | "move" | null>(null);
  const toggleShape = (next: "reshape" | "move") => setShapeMode((current) => (current === next ? null : next));
  const [editTexts, setEditTexts] = useState<Record<string, string>>({});
  const [newProp, setNewProp] = useState<{ name: string; type: PropertyType; value: string }>({ name: "", type: "text", value: "" });
  const [removeBy, setRemoveBy] = useState<"click" | "rule">("click");
  // Editing by a rule: what it does to the features it matches, in which column, by what.
  const [editBy, setEditBy] = useState<"click" | "rule">("click");
  const [ruleOp, setRuleOp] = useState<RuleOp>("set");
  const [ruleColumn, setRuleColumn] = useState("");
  const [ruleValue, setRuleValue] = useState("");
  // Show only this layer: the map hides its other layers while one is worked on.
  const [solo, setSolo] = useState(false);
  const [conditions, setConditions] = useState<Condition[]>([{ column: "", test: "is", value: "" }]);

  // What was just added or edited, lit up on the map once it draws them again.
  const [recent, setRecent] = useState<SelectionId[]>([]);
  // Drawing one more part: of the feature being added ("draft") or of the picked one.
  const [partFor, setPartFor] = useState<"draft" | "picked" | null>(null);

  const active = layers.find((l) => l.name === activeName) ?? null;
  useEffect(() => {
    setDrawn(null);
    setPicked([]);
    setRecent([]);
    setPartFor(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeName, action]);

  const kind: GeometryKind | null = active ? (active.newLayer ? GEOMETRY_KIND[active.newLayer.geometry] : mainKind(active.fc)) : null;
  // A feature is called by its geometry ("point", "line", "area"), never by a
  // guess from the layer's name.
  const nouns = kind ? { one: KIND_NOUN[kind], many: `${KIND_NOUN[kind]}s` } : { one: "feature", many: "features" };
  const defs = useMemo(
    () => (active ? withAddedColumns(propertiesFor(active.fc, active.key, active.newLayer), edits, active.name, nodeLayer) : []),
    [active, edits, nodeLayer],
  );
  const features = useMemo(
    () => (active ? editedFeatures(active.fc, edits, active.key ?? (active.newLayer ? "id" : undefined), active.name, nodeLayer) : []),
    [active, edits, nodeLayer],
  );
  // A fresh rule for each layer. Keyed on the layer, not on defs: defs is
  // rebuilt after every edit, which cleared a rule just applied.
  useEffect(() => {
    setConditions([{ column: defs[0]?.name ?? "", test: "is", value: "" }]);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active?.name]);
  const geographic = active ? isGeographic(active.fc) || (active.newLayer ? isGeographic(layers.find((l) => !l.newLayer)?.fc) : false) : false;
  const pickedOne = picked.length === 1 ? features.find((f) => f.id !== null && String(f.id) === String(picked[0])) : undefined;
  const textsOf = (f: EditedFeature) =>
    Object.fromEntries(defs.map((d) => [d.name, f.properties[d.name] === null || f.properties[d.name] === undefined ? "" : String(f.properties[d.name])]));
  useEffect(() => {
    setEditTexts(pickedOne ? textsOf(pickedOne) : {});
    setPartFor((current) => (current === "picked" ? null : current));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pickedOne?.id, defs]);

  // What a rule picks now, among the features as the log leaves them.
  const byRule = (action === "remove" && removeBy === "rule") || (action === "edit" && editBy === "rule");
  const rule = byRule ? ruleText(conditions, defs) : null;
  const ruleProblem = rule ? exprProblem(rule) : null;
  const matches = useMemo<SelectionId[] | null>(() => {
    if (!rule || ruleProblem) return null;
    const condition = parseExpr(rule);
    return features.filter((f) => f.id !== null && truthy(evaluate(condition, f.properties as any))).map((f) => f.id as SelectionId);
  }, [rule, ruleProblem, features]);

  const grouped = useMemo(() => {
    const groups = new Map<GeometryKind, WorkbenchLayer[]>();
    for (const layer of layers) {
      const kinds = layer.newLayer ? [GEOMETRY_KIND[layer.newLayer.geometry]] : geometryKinds(layer.fc).map((k) => k.kind);
      for (const k of kinds) {
        const list = groups.get(k) ?? [];
        if (!list.includes(layer)) list.push(layer);
        groups.set(k, list);
      }
    }
    return (["points", "lines", "areas"] as GeometryKind[]).filter((k) => groups.has(k)).map((k) => ({ kind: k, layers: groups.get(k) as WorkbenchLayer[] }));
  }, [layers]);

  const countOf = (layer: WorkbenchLayer) =>
    layer.newLayer ? edits.filter((e) => e.op === "add" && e.layer === layer.name && e.enabled !== false).length : (layer.fc.features ?? []).length;

  const onSelect = (id: SelectionId | null, additive: boolean) => {
    if (drawn || (action === "edit" && editBy === "rule")) return;
    if (id === null) {
      if (!additive) setPicked([]);
      return;
    }
    setPicked(additive ? (picked.some((p) => String(p) === String(id)) ? picked.filter((p) => String(p) !== String(id)) : [...picked, id]) : [id]);
  };
  // A part drawn is added to the feature being added, or to the picked one.
  const onDrawn = (geometry: Geometry) => {
    if (partFor === "draft" && drawn) {
      setDrawn(withPart(drawn, geometry) ?? drawn);
      setPartFor(null);
      return;
    }
    if (partFor === "picked" && active && pickedOne?.geometry && pickedOne.id !== null) {
      const merged = withPart(pickedOne.geometry, geometry);
      if (merged) {
        onEdit({ op: "geometry", ids: [pickedOne.id], geometry: merged }, active);
        setRecent([pickedOne.id]);
      }
      setPartFor(null);
      return;
    }
    setDrawn(geometry);
  };
  const onReshape = (id: SelectionId, geometry: Geometry) => {
    if (!active) return;
    onEdit({ op: "geometry", ids: [id], geometry }, active);
    setRecent([id]);
  };

  // What a click on the map does now: nothing until an action that draws.
  const mode: MapEditMode | null =
    !active || !action || action === "property"
      ? null
      : action === "add"
        ? drawn && partFor !== "draft" ? "select" : "draw"
        : action === "edit" && editBy === "rule"
          ? "select" // a rule changes values only: no points or features to move
          : action === "edit" && pickedOne && partFor === "picked"
          ? "draw"
          : action === "edit" && pickedOne && shapeMode
            ? shapeMode
            : "select";
  const shown = useMemo<EditedFeature[]>(
    () => (drawn ? [...features, { id: DRAFT, geometry: drawn, properties: {}, status: "added" }] : features),
    [features, drawn],
  );

  // Linked to a map: the action is drawn there.
  const handlers = useRef({ onSelect, onDrawn, onReshape });
  handlers.current = { onSelect, onDrawn, onReshape };
  useEffect(() => {
    const soloTable = solo && active ? active.table ?? active.name : null;
    if (!active || !kind || (!mode && !soloTable)) {
      publishMapSession(mapId, null);
      return;
    }
    publishMapSession(mapId, {
      interactionId: nodeId,
      solo: soloTable,
      active: !mode ? null : {
        table: active.table ?? active.name,
        label: active.label,
        kind,
        noun: nouns.one,
        mode,
        features: shown,
        selected: drawn ? [DRAFT] : picked,
        matches: matches ?? undefined,
        recent,
        geographic,
        key: active.key ?? (active.newLayer ? "id" : undefined),
      },
      onSelect: (id, additive) => handlers.current.onSelect(id, additive),
      onDrawn: (geometry) => handlers.current.onDrawn(geometry),
      onReshape: (id, geometry) => handlers.current.onReshape(id, geometry),
      onShapeDone: () => setShapeMode(null),
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mapId, active, kind, mode, shown, drawn, picked, matches, recent, geographic, nouns.one, solo]);
  // Back on the list of layers, the map shows them all again.
  useEffect(() => {
    if (activeName === null) setSolo(false);
  }, [activeName]);
  useEffect(
    () => () => {
      publishMapSession(mapId, null);
    },
    [mapId],
  );

  const addDrawn = () => {
    if (!active || !drawn) return;
    const key = active.key ?? "id";
    const id = nextId(active.fc, edits, key, active.newLayer ? active.name : active.name === nodeLayer ? undefined : active.name);
    onEdit({ op: "add", id, geometry: drawn, values: formValues(defs, texts) }, active);
    setRecent([id as SelectionId]);
    setDrawn(null);
    setTexts(formDefaults(defs));
  };
  const dirty = pickedOne ? defs.filter((def) => String(pickedOne.properties[def.name] ?? "") !== String(formValues([def], editTexts)[def.name] ?? "")) : [];
  const applyValues = () => {
    if (!active || !pickedOne || pickedOne.id === null) return;
    const values = formValues(defs, editTexts);
    const changed: FeatureEdit[] = dirty.map((def) => ({ op: "set", ids: [pickedOne.id as SelectionId], column: def.name, value: (values[def.name] ?? null) as EditValue }));
    if (changed.length > 0) {
      onEdits(changed, active);
      setRecent([pickedOne.id as SelectionId]);
    }
  };
  const go = (next: Action) => {
    setAction(next);
    if (next === "add") setTexts(formDefaults(defs));
  };

  if (creating) {
    return (
      <div className={styles.workbench} data-testid="interaction-workbench">
        <NewLayerForm
          taken={layers.map((l) => l.name)}
          onCancel={() => setCreating(false)}
          onCreate={(def) => {
            onNewLayer(def);
            setCreating(false);
            setActiveName(def.name);
            setAction("add");
            setTexts(formDefaults(def.properties ?? []));
          }}
        />
      </div>
    );
  }

  if (!active || !kind) {
    return (
      <div className={styles.workbench} data-testid="interaction-workbench">
        <div className={styles.group} data-testid="interaction-layers">
          <span className={styles.lead}>
            {layers.length === 0 ? (
              "No layers yet."
            ) : (
              <>
                Found <b>{plural(layers.length, "layer", "layers")}</b>
                {grouped.length > 1 ? (
                  <>
                    {" "}in <b>{grouped.length} geometry types</b>
                  </>
                ) : null}
                . Pick a layer to work on:
              </>
            )}
          </span>
          {grouped.map((group) => (
            <div key={group.kind} className={styles.group}>
              <span className={styles.groupLabel}>
                <KindIcon kind={group.kind} />
                {KIND_LABEL[group.kind]} · {KIND_GEOMETRY[group.kind]}
              </span>
              {group.layers.map((layer) => {
                const n = countOf(layer);
                const columns = layer.newLayer
                  ? (layer.newLayer.properties ?? []).map((p) => p.name)
                  : withAddedColumns(propertiesFor(layer.fc, layer.key), edits, layer.name, nodeLayer).map((p) => p.name);
                return (
                  <button
                    key={layer.name}
                    type="button"
                    data-testid={`interaction-layer-${layer.name}`}
                    className={`nodrag nopan ${styles.layerCard}`}
                    onClick={() => {
                      setActiveName(layer.name);
                      setAction(null);
                    }}
                  >
                    <span className={styles.top}>
                      <b>
                        {layer.label} {layer.newLayer ? <span className={styles.badge}>new</span> : null}
                      </b>
                      <span className={styles.mono}>
                        {layer.newLayer ? "new layer" : layer.table ?? layer.name} · {plural(n, KIND_NOUN[group.kind], `${KIND_NOUN[group.kind]}s`)}
                      </span>
                    </span>
                    <span className={styles.props}>
                      {columns.length > 0 ? `properties: ${columns.slice(0, 8).join(", ")}${columns.length > 8 ? ", …" : ""}` : "no properties"}
                      {!layer.key && !layer.newLayer ? " · no id column" : ""}
                    </span>
                  </button>
                );
              })}
            </div>
          ))}
          {writable ? (
            <div className={styles.footer}>
              <button type="button" data-testid="interaction-new-layer-open" className={`nodrag nopan ${styles.dashedButton}`} onClick={() => setCreating(true)}>
                + New data layer
              </button>
              <span className={styles.hint}>or start a layer of your own, with its own properties</span>
            </div>
          ) : null}
          {grouped.length > 1 ? <span className={styles.hint}>A layer with mixed geometry is listed under each kind, so each list only offers the tools that fit it.</span> : null}
        </div>
      </div>
    );
  }

  const canEdit = !!(active.key || active.newLayer);

  const soloSwitch = (
    <label className={`nodrag nopan ${styles.soloSwitch}`} title="Hide the map's other layers while you work on this one">
      <input type="checkbox" role="switch" data-testid="interaction-solo" checked={solo} onChange={(e) => setSolo(e.target.checked)} />
      <span className={styles.track} aria-hidden="true" />
      Show only this layer
    </label>
  );

  if (!action) {
    const cards: { action: Action; title: string; text: string }[] = [
      { action: "add", title: `+ Add ${nouns.many}`, text: kind === "points" ? "Click the map to place them, then fill in their properties" : `Draw new ${KIND_NOUN[kind]}s, then fill in their properties` },
      { action: "edit", title: `Edit ${nouns.many}`, text: `Change a${kind === "areas" ? "n" : ""} ${KIND_NOUN[kind]}'s shape or its values` },
      { action: "remove", title: `Remove ${nouns.many}`, text: "Click them on the map, or pick them by a rule" },
      { action: "property", title: "Add a property", text: `A new column on every ${nouns.one}, with a default value` },
    ];
    return (
      <div className={styles.workbench} data-testid="interaction-workbench">
        <div className={styles.form} data-testid="interaction-active-layer" data-layer={active.name} data-kind={kind}>
          <button type="button" className={`nodrag nopan ${styles.back}`} onClick={() => setActiveName(null)}>
            ← All layers
          </button>
          <div className={styles.titleRow}>
            <KindIcon kind={kind} size={20} />
            <span className={styles.title}>{active.label}</span>
            <span className={styles.mono}>
              {KIND_LABEL[kind].toLowerCase()} · {features.length.toLocaleString()}
            </span>
            <span style={{ flex: 1 }} />
            {soloSwitch}
          </div>
          {!canEdit ? (
            <span className={styles.problem}>This layer has no column that identifies its features, so they cannot be edited or removed: add an id column upstream. You can still draw into a new layer.</span>
          ) : null}
          <span className={styles.lead}>What do you want to do?</span>
          <div className={styles.actionGrid}>
            {cards.map((card) => (
              <button key={card.action} type="button" data-testid={`interaction-action-${card.action}`} className={`nodrag nopan ${styles.actionCard}`} disabled={!writable || !canEdit} onClick={() => go(card.action)}>
                <b>{card.title}</b>
                <span>{card.text}</span>
              </button>
            ))}
          </div>
          {writable ? (
            <div className={styles.footer}>
              <button type="button" className={`nodrag nopan ${styles.dashedButton}`} onClick={() => setCreating(true)}>
                + New data layer instead
              </button>
            </div>
          ) : null}
        </div>
      </div>
    );
  }

  const back = (
    <div className={styles.backRow}>
      <button type="button" data-testid="interaction-back" className={`nodrag nopan ${styles.back}`} onClick={() => setAction(null)}>
        ← {active.label}
      </button>
      {soloSwitch}
    </div>
  );
  const onTheMap = "on the map";
  const capital = nouns.one[0].toUpperCase() + nouns.one.slice(1);

  /** The conditions a rule is made of, with how many features match them now. */
  const ruleBuilder = (lead: string) => (
    <div className={styles.section}>
      <span className={styles.kind}>{lead}</span>
      {conditions.map((c, i) => {
        const def = defs.find((d) => d.name === c.column);
        const needsValue = c.test !== "is empty" && c.test !== "is not empty";
        const choices = def?.type === "choice" ? def.choices ?? [] : def?.type === "boolean" ? ["true", "false"] : null;
        const set = (patch: Partial<Condition>) => setConditions(conditions.map((x, j) => (j === i ? { ...x, ...patch } : x)));
        return (
          <div key={i} className={styles.ruleRow} data-testid={`interaction-rule-${i}`}>
            <span className={styles.kind}>{i === 0 ? "" : "and"}</span>
            <select className={`nodrag nopan ${styles.first}`} aria-label="Property" value={c.column} onChange={(e) => set({ column: e.target.value, value: "" })}>
              {defs.map((d) => (
                <option key={d.name} value={d.name}>
                  {d.name}
                </option>
              ))}
            </select>
            <select className="nodrag nopan" aria-label="Test" value={c.test} onChange={(e) => set({ test: e.target.value as Test })}>
              {TESTS.filter((t) => def?.type === "number" || (t !== ">" && t !== "<")).map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
            {!needsValue ? (
              <span />
            ) : choices ? (
              <select className="nodrag nopan" aria-label="Value" data-testid={`interaction-rule-value-${i}`} value={c.value} onChange={(e) => set({ value: e.target.value })}>
                <option value="">Choose…</option>
                {choices.map((choice) => (
                  <option key={choice} value={choice}>
                    {choice}
                  </option>
                ))}
              </select>
            ) : (
              <input className={`nodrag nopan ${styles.input}`} aria-label="Value" data-testid={`interaction-rule-value-${i}`} value={c.value} onChange={(e) => set({ value: e.target.value })} />
            )}
            {i > 0 ? (
              <button type="button" className={`nodrag nopan ${styles.delete}`} aria-label={`Remove condition ${i + 1}`} onClick={() => setConditions(conditions.filter((_, j) => j !== i))}>
                ×
              </button>
            ) : (
              <span />
            )}
          </div>
        );
      })}
      <button type="button" className={`nodrag nopan ${styles.small} ${styles.dashed}`} onClick={() => setConditions([...conditions, { column: defs[0]?.name ?? "", test: "is", value: "" }])}>
        + condition
      </button>
      {ruleProblem ? <span className={styles.problem}>{ruleProblem}</span> : null}
      <span className={styles.matchCount} data-testid="interaction-matching">
        <b>Matches {plural(matches?.length ?? 0, nouns.one, nouns.many)}</b> <span className={styles.kind}>of {features.length.toLocaleString()}</span>
      </span>
    </div>
  );
  const pickBy = (current: "click" | "rule", choose: (by: "click" | "rule") => void, testId: string) => (
    <span className={styles.segmented} role="group" aria-label="Pick by">
      <button type="button" aria-pressed={current === "click"} className={`nodrag nopan ${current === "click" ? styles.on : ""}`} onClick={() => choose("click")}>
        Click
      </button>
      <button type="button" aria-pressed={current === "rule"} data-testid={testId} className={`nodrag nopan ${current === "rule" ? styles.on : ""}`} onClick={() => choose("rule")}>
        By a rule
      </button>
    </span>
  );

  // What an edit by a rule, or of several picked features, does: in which
  // column, how, by what; *make* gives the edit on what *base* picks.
  const valueChange = () => {
    // Any column can be set to a value; a number column also to an expression.
    const columns = defs;
    const column = columns.find((d) => d.name === ruleColumn) ?? columns[0];
    const ops = RULE_OPS.filter(({ op }) => op === "set" || column?.type === "number");
    const op: RuleOp = ops.some((o) => o.op === ruleOp) ? ruleOp : "set";
    const choices = op === "set" && column ? (column.type === "choice" ? column.choices ?? [] : column.type === "boolean" ? ["true", "false"] : null) : null;
    const valueProblem =
      op === "expr"
        ? ruleValue.trim() === ""
          ? "Give an expression."
          : exprProblem(ruleValue)
        : ruleValue.trim() !== "" && column && formValue(column, ruleValue) === undefined
          ? `Give a ${column.type === "number" ? "number" : "value"} for ${column.name}.`
          : null;
    const make = (base: { where: string } | { ids: SelectionId[] }): FeatureEdit | null => {
      if (!column || valueProblem) return null;
      const edit = { op, ...base, column: column.name };
      if (op === "expr") return { ...edit, value: ruleValue.trim() };
      const value = ruleValue.trim() === "" ? null : formValue(column, ruleValue);
      return value === undefined ? null : { ...edit, value: value as EditValue };
    };
    const section = (
      <div className={styles.section}>
        <span className={styles.kind}>Then</span>
        {columns.length === 0 ? <span className={styles.hint}>This layer has no property to change.</span> : null}
        <div className={styles.ruleRow}>
          <span className={styles.kind} />
          <select className={`nodrag nopan ${styles.first}`} aria-label="Change" data-testid="interaction-rule-column" value={column?.name ?? ""} onChange={(e) => setRuleColumn(e.target.value)}>
            {columns.map((d) => (
              <option key={d.name} value={d.name}>
                {d.name}
              </option>
            ))}
          </select>
          <select className="nodrag nopan" aria-label="How" data-testid="interaction-rule-op" value={op} disabled={ops.length === 1} onChange={(e) => setRuleOp(e.target.value as RuleOp)}>
            {ops.map((o) => (
              <option key={o.op} value={o.op}>
                {o.label}
              </option>
            ))}
          </select>
          {choices ? (
            <select className="nodrag nopan" aria-label="By" data-testid="interaction-rule-set-value" value={ruleValue} onChange={(e) => setRuleValue(e.target.value)}>
              <option value="">Empty</option>
              {choices.map((choice) => (
                <option key={choice} value={choice}>
                  {choice}
                </option>
              ))}
            </select>
          ) : (
            <input
              className={`nodrag nopan ${styles.input}`}
              aria-label="By"
              data-testid="interaction-rule-set-value"
              value={ruleValue}
              placeholder={op === "expr" ? `${column?.name ?? "height"} * 0.8` : "empty"}
              onChange={(e) => setRuleValue(e.target.value)}
            />
          )}
          <span />
        </div>
        {valueProblem ? <span className={styles.problem}>{valueProblem}</span> : null}
      </div>
    );
    return { make, section };
  };

  let body: React.ReactNode = null;
  if (action === "add") {
    const problems = formProblems(defs, texts);
    const draftParts = partsOf(drawn).length;
    body = drawn && partFor !== "draft" ? (
      <div className={styles.form} data-testid="interaction-property-form">
        {back}
        <span className={styles.title}>New {nouns.one}: its properties</span>
        {draftParts > 1 ? <span className={styles.hint} data-testid="interaction-part-count">{draftParts} parts</span> : null}
        <span className={styles.hint}>
          {active.newLayer ? "The fields are the properties the layer was made with." : "The fields are the layer's columns; the choices are the values already in it."}
        </span>
        {defs.length === 0 ? <span className={styles.hint}>This layer has no properties to fill in.</span> : null}
        {defs.map((def) => (
          <PropertyField key={def.name} def={def} value={texts[def.name] ?? ""} hint={fieldHint(def, active.fc)} testId={`interaction-field-${def.name}`} onChange={(text) => setTexts({ ...texts, [def.name]: text })} />
        ))}
        {problems.length > 0 ? <span className={styles.problem}>{problems.join(" · ")}</span> : null}
        <span className={styles.formButtons}>
          <button type="button" className={`nodrag nopan ${styles.big} ${styles.primary}`} data-testid="interaction-form-submit" disabled={problems.length > 0} onClick={addDrawn}>
            Add {nouns.one}
          </button>
          <button type="button" className={`nodrag nopan ${styles.big} ${styles.secondary}`} data-testid="interaction-add-part" onClick={() => setPartFor("draft")}>
            Add another part
          </button>
          <button type="button" className={`nodrag nopan ${styles.big} ${styles.secondary}`} onClick={() => setDrawn(null)}>
            Discard {KIND_NOUN[kind]}
          </button>
        </span>
      </div>
    ) : drawn ? (
      <div className={styles.form}>
        {back}
        <span className={styles.title}>
          New {nouns.one}: part {draftParts + 1}
        </span>
        <span className={styles.lead}>
          {kind === "points"
            ? `Click ${onTheMap} to place another ${KIND_NOUN[kind]} of this ${nouns.one}.`
            : `Click ${onTheMap} to add points along the next ${KIND_NOUN[kind]}, then double-click or press Enter to finish it.`}
        </span>
        <span className={styles.formButtons}>
          <button type="button" className={`nodrag nopan ${styles.big} ${styles.secondary}`} data-testid="interaction-cancel-part" onClick={() => setPartFor(null)}>
            Cancel this part
          </button>
        </span>
      </div>
    ) : (
      <div className={styles.form}>
        {back}
        <span className={styles.title}>Add {nouns.many}</span>
        <span className={styles.lead}>
          {kind === "points"
            ? `Click ${onTheMap} to place a ${nouns.one}.`
            : `Click ${onTheMap} to add points along the ${KIND_NOUN[kind]}, then double-click or press Enter to finish.`}
        </span>
        <span className={styles.hint}>Its properties are asked for next. Drag to move the map; Esc gives up.</span>
      </div>
    );
  } else if (action === "edit" && editBy === "rule") {
    const change = valueChange();
    const ruleEdit = (): FeatureEdit | null => (rule && !ruleProblem ? change.make({ where: rule }) : null);
    const ready = ruleEdit();
    const n = matches?.length ?? 0;
    body = (
      <div className={styles.form} data-testid="interaction-edit-rule">
        {back}
        <span className={styles.title}>Edit {nouns.many}</span>
        {pickBy(editBy, (by) => {
          setEditBy(by);
          setPicked([]);
          setShapeMode(null);
          setPartFor(null);
        }, "interaction-edit-by-rule")}
        {ruleBuilder(`Change ${nouns.many} where`)}
        {change.section}
        <span className={styles.formButtons}>
          <button
            type="button"
            data-testid="interaction-rule-apply"
            className={`nodrag nopan ${styles.big} ${styles.primary}`}
            disabled={!ready || n === 0}
            onClick={() => {
              if (!ready) return;
              onEdit(ready, active);
              setRecent(matches ?? []);
            }}
          >
            Apply to {n > 0 ? plural(n, nouns.one, nouns.many) : nouns.many}
          </button>
        </span>
        <span className={styles.hint}>
          Kept as a rule: {nouns.many} that match it later are changed too. The match is outlined in red {onTheMap}.
        </span>
      </div>
    );
  } else if (action === "edit" && picked.length > 1) {
    const change = valueChange();
    const ready = change.make({ ids: picked });
    body = (
      <div className={styles.form} data-testid="interaction-edit-many">
        {back}
        <span className={styles.title}>Edit {nouns.many}</span>
        <span className={styles.lead}>{plural(picked.length, nouns.one, nouns.many)} picked.</span>
        {change.section}
        <span className={styles.formButtons}>
          <button
            type="button"
            data-testid="interaction-many-apply"
            className={`nodrag nopan ${styles.big} ${styles.primary}`}
            disabled={!ready}
            onClick={() => {
              if (!ready) return;
              onEdit(ready, active);
              setRecent(picked);
            }}
          >
            Apply to {plural(picked.length, nouns.one, nouns.many)}
          </button>
          <button type="button" className={`nodrag nopan ${styles.big} ${styles.secondary}`} onClick={() => setPicked([])}>
            Clear the pick
          </button>
        </span>
        <span className={styles.hint}>Shift-click adds or drops one.</span>
      </div>
    );
  } else if (action === "edit") {
    const problems = formProblems(defs, editTexts);
    body = pickedOne ? (
      <div className={styles.form}>
        {back}
        <div className={`${styles.titleRow} ${styles.spread}`}>
          <span className={styles.title}>
            {capital} · {String(pickedOne.properties.name ?? pickedOne.id)}
          </span>
          <span className={styles.kind}>1 selected</span>
        </div>
        <div className={styles.section} data-testid="interaction-selection">
          <div className={styles.sectionHead}>
            <b>Selection</b>
          </div>
          <span className={styles.hint}>Shift-click {nouns.many} {onTheMap} to pick more.</span>
        </div>
        <div className={styles.section}>
          <div className={styles.sectionHead}>
            <b>Geometry</b>
            {pickedOne.status === "redrawn" ? <span className={styles.changed}>changed</span> : null}
          </div>
          <span className={styles.switches} role="group" aria-label="Shape">
            <ShapeSwitch
              on={shapeMode === "reshape"}
              icon="points"
              label={kind === "points" ? "Move point" : "Move points"}
              testId="interaction-reshape"
              onToggle={() => toggleShape("reshape")}
            />
            {/* A point is one corner: moving it whole is moving its point. */}
            {kind === "points" ? null : (
              <ShapeSwitch on={shapeMode === "move"} icon="whole" label={`Move whole ${nouns.one}`} testId="interaction-move" onToggle={() => toggleShape("move")} />
            )}
          </span>
          <span className={styles.formButtons}>
            {partFor === "picked" ? (
              <button type="button" className={`nodrag nopan ${styles.small}`} data-testid="interaction-cancel-part" onClick={() => setPartFor(null)}>
                Cancel the new part
              </button>
            ) : (
              <button
                type="button"
                className={`nodrag nopan ${styles.small}`}
                data-testid="interaction-add-part"
                onClick={() => {
                  setShapeMode(null);
                  setPartFor("picked");
                }}
              >
                + Add a part
              </button>
            )}
            {partsOf(pickedOne.geometry).length > 1 ? (
              <span className={styles.kind} data-testid="interaction-part-count">
                {partsOf(pickedOne.geometry).length} parts
              </span>
            ) : null}
          </span>
          <span className={styles.hint}>
            {partFor === "picked"
              ? kind === "points"
                ? `Click ${onTheMap} to place the new ${KIND_NOUN[kind]}; it joins this ${nouns.one}.`
                : `Draw the new part ${onTheMap}: click to add points, then double-click or press Enter. It joins this ${nouns.one}.`
              : shapeMode === null
              ? `Turn on ${kind === "points" ? "Move point to move it" : "one of these to change its shape"}. Until then, drag ${onTheMap} to pan it.`
              : shapeMode === "reshape"
              ? kind === "points"
                ? `Drag the ${nouns.one} ${onTheMap} to move it. The change is kept when you let go.`
                : `Drag its points ${onTheMap}; click or drag a midpoint to add one; alt-click a point to delete it${partsOf(pickedOne.geometry).length > 1 ? ", or inside a part to remove that part" : ""}. Each change is kept when you let go.`
              : `Hold shift and drag the ${nouns.one} ${onTheMap} to move it. A drag without shift pans the map.`}
          </span>
        </div>
        <div className={styles.section}>
          <div className={styles.sectionHead}>
            <b>Properties</b>
            {dirty.length > 0 ? <span className={styles.changed}>{dirty.length} changed</span> : null}
          </div>
          <div className={styles.grid}>
            {defs.map((def) => {
              const before = pickedOne.properties[def.name];
              const isDirty = dirty.includes(def);
              const id = `edit-${nodeId}-${def.name}`;
              const choices = def.type === "choice" ? def.choices ?? [] : def.type === "boolean" ? ["true", "false"] : null;
              const text = editTexts[def.name] ?? "";
              return (
                <React.Fragment key={def.name}>
                  <label htmlFor={id} title={def.name}>
                    {def.name}
                  </label>
                  <span style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    {choices ? (
                      <select id={id} className={`nodrag nopan ${isDirty ? styles.dirty : ""}`} data-testid={`interaction-field-${def.name}`} value={text} onChange={(e) => setEditTexts({ ...editTexts, [def.name]: e.target.value })}>
                        <option value="">(empty)</option>
                        {[...choices, ...(text && !choices.includes(text) ? [text] : [])].map((c) => (
                          <option key={c} value={c}>
                            {c}
                          </option>
                        ))}
                      </select>
                    ) : (
                      <input id={id} className={`nodrag nopan ${styles.input} ${isDirty ? styles.dirty : ""}`} data-testid={`interaction-field-${def.name}`} value={text} onChange={(e) => setEditTexts({ ...editTexts, [def.name]: e.target.value })} />
                    )}
                    {isDirty ? <span className={styles.was}>was {before === null || before === undefined || before === "" ? "empty" : String(before)}</span> : null}
                  </span>
                </React.Fragment>
              );
            })}
          </div>
        </div>
        {problems.length > 0 ? <span className={styles.problem}>{problems.join(" · ")}</span> : null}
        <span className={styles.formButtons}>
          <button type="button" className={`nodrag nopan ${styles.big} ${styles.primary}`} data-testid="interaction-form-submit" disabled={dirty.length === 0 || problems.length > 0} onClick={applyValues}>
            Apply changes
          </button>
        </span>
      </div>
    ) : (
      <div className={styles.form}>
        {back}
        <span className={styles.title}>Edit {nouns.many}</span>
        {pickBy(editBy, (by) => {
          setEditBy(by);
          setPicked([]);
          setShapeMode(null);
          setPartFor(null);
        }, "interaction-edit-by-rule")}
        <span className={styles.lead}>Click a {nouns.one} {onTheMap} to select it; shift-click adds one.</span>
        <span className={styles.hint}>One picked: drag its points to reshape it, or change its values here. Several: change one value of them all.</span>
      </div>
    );
  } else if (action === "remove") {
    const n = removeBy === "rule" ? matches?.length ?? 0 : picked.length;
    body = (
      <div className={styles.form}>
        {back}
        <span className={styles.title}>Remove {nouns.many}</span>
        {pickBy(removeBy, setRemoveBy, "interaction-remove-by-rule")}
        {removeBy === "click" ? (
          <span className={styles.lead}>
            {picked.length === 0
              ? `Click ${nouns.many} ${onTheMap} to pick them; shift-click adds one.`
              : `${plural(picked.length, nouns.one, nouns.many)} picked.`}
          </span>
        ) : (
          ruleBuilder(`Remove ${nouns.many} where`)
        )}
        <span className={styles.formButtons}>
          <button
            type="button"
            data-testid="interaction-remove-picked"
            className={`nodrag nopan ${styles.big} ${styles.danger}`}
            disabled={n === 0}
            onClick={() => {
              if (removeBy === "rule" && rule) onEdit({ op: "remove", where: rule }, active);
              else onEdit({ op: "remove", ids: picked }, active);
              setPicked([]);
            }}
          >
            Remove {n > 0 ? plural(n, nouns.one, nouns.many) : nouns.many}
          </button>
        </span>
        <span className={styles.hint}>
          {removeBy === "rule"
            ? `Kept as a rule: ${nouns.many} that match it later are removed too. The match is outlined in red ${onTheMap}.`
            : "Each removal is an entry in the edit log: switch it off or delete it to bring the features back."}
        </span>
      </div>
    );
  } else if (action === "property") {
    const taken = defs.some((d) => d.name === newProp.name.trim());
    body = (
      <div className={styles.form} data-testid="interaction-add-property">
        {back}
        <span className={styles.title}>A new property on every {nouns.one}</span>
        <label className={styles.formField}>
          <b>Name</b>
          <input className={`nodrag nopan ${styles.input}`} aria-label="Property name" data-testid="interaction-property-name" value={newProp.name} onChange={(e) => setNewProp({ ...newProp, name: e.target.value })} />
        </label>
        <div className={styles.formField}>
          <b>Type</b>
          <span className={styles.segmented} role="group" aria-label="Property type">
            {PROPERTY_TYPES.filter((t) => t !== "choice").map((t) => (
              <button key={t} type="button" aria-pressed={newProp.type === t} className={`nodrag nopan ${newProp.type === t ? styles.on : ""}`} onClick={() => setNewProp({ ...newProp, type: t, value: "" })}>
                {t === "boolean" ? "yes / no" : t}
              </button>
            ))}
          </span>
        </div>
        <PropertyField def={{ name: "default value", type: newProp.type }} value={newProp.value} hint={`for every ${nouns.one}`} testId="interaction-property-value" onChange={(value) => setNewProp({ ...newProp, value })} />
        {taken ? <span className={styles.problem}>The layer has that property already.</span> : null}
        <span className={styles.formButtons}>
          <button
            type="button"
            data-testid="interaction-property-add"
            className={`nodrag nopan ${styles.big} ${styles.primary}`}
            disabled={newProp.name.trim() === "" || taken}
            onClick={() => {
              const def: PropertyDef = { name: newProp.name.trim(), type: newProp.type };
              const values = formValues([{ ...def, name: "v" }], { v: newProp.value });
              if (active.newLayer) onAddLayerProperty(active.name, { ...def, ...(values.v !== undefined ? { default: values.v } : {}) });
              onEdit({ op: "add_column", column: def.name, value: values.v ?? null }, active);
              setNewProp({ name: "", type: "text", value: "" });
              setAction(null);
            }}
          >
            Add property
          </button>
        </span>
      </div>
    );
  }

  return (
    <div className={styles.workbench} data-testid="interaction-workbench">
      <div data-testid="interaction-active-layer" data-layer={active.name} data-kind={kind} className={styles.form}>
        {body}
      </div>
    </div>
  );
}

export { KIND_GEOMETRY };
