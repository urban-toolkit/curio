/**
 * Add a property in the Map Edits node's workbench (#662): a new column on
 * every feature of the layer, with a default value. On a new layer, its next
 * features are asked for it too.
 */
import React from "react";
import { PROPERTY_TYPES, type FeatureEdit, type PropertyDef, type PropertyType } from "../../utils/editFeatures/editFeatures";
import { formValues } from "../../utils/editFeatures/layerModel";
import type { WorkbenchLayer } from "./LayerWorkbench";
import { PropertyField } from "./PropertyField";
import type { Nouns } from "./workbenchParts";
import styles from "./EditFeatures.module.css";

/** The property being written: its name, its type and the value every feature gets. */
export interface NewProperty {
  name: string;
  type: PropertyType;
  value: string;
}

export default function AddPropertyForm({
  back,
  nouns,
  active,
  defs,
  newProp,
  setNewProp,
  onAdd,
}: {
  back: React.ReactNode;
  nouns: Nouns;
  active: WorkbenchLayer;
  /** The layer's properties now. */
  defs: PropertyDef[];
  newProp: NewProperty;
  setNewProp: (prop: NewProperty) => void;
  /** Writes the new column; *property* is what a new layer's next features are asked for. */
  onAdd: (edit: FeatureEdit, property?: PropertyDef) => void;
}) {
  const taken = defs.some((d) => d.name === newProp.name.trim());
  return (
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
            // A new layer's next features are asked for it too, in the same change.
            const property = active.newLayer ? { ...def, ...(values.v !== undefined ? { default: values.v } : {}) } : undefined;
            onAdd({ op: "add_column", column: def.name, value: values.v ?? null }, property);
          }}
        >
          Add property
        </button>
      </span>
    </div>
  );
}
