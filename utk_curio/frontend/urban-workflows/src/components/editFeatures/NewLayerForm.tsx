/**
 * + New data layer in the Map Edits node's workbench (#662): the builder of a
 * new layer, its name, its geometry and the properties its features carry.
 */
import React, { useState } from "react";
import {
  NEW_LAYER_GEOMETRIES,
  PROPERTY_TYPES,
  type NewLayerDef,
  type NewLayerGeometry,
  type PropertyDef,
  type PropertyType,
} from "../../utils/editFeatures/editFeatures";
import { GEOMETRY_KIND, KIND_LABEL } from "../../utils/editFeatures/layerModel";
import { KindIcon } from "./workbenchParts";
import styles from "./EditFeatures.module.css";

/** The builder of a new layer: its name, its geometry and its properties. */
export default function NewLayerForm({ taken, onCreate, onCancel }: { taken: string[]; onCreate: (def: NewLayerDef) => void; onCancel: () => void }) {
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
