/**
 * Add a property in the Map Editor node's workbench (#662): a new column on
 * every feature of the layer, with a default value. On a new layer, its next
 * features are asked for it too.
 */
import React, { useId } from "react";
import { PROPERTY_TYPES, type FeatureEdit, type PropertyDef, type PropertyType } from "../../utils/editFeatures/editFeatures";
import { formValues } from "../../utils/editFeatures/layerModel";
import type { WorkbenchLayer } from "./LayerWorkbench";
import { RadioChoices, TextInput } from "./fields";
import { PropertyField } from "./PropertyField";
import { TYPE_LABEL, type Nouns } from "./workbenchParts";
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
  const nameId = useId();
  const taken = defs.some((d) => d.name === newProp.name.trim());
  return (
    <div className={styles.form} data-testid="interaction-add-property">
      {back}
      <span className={styles.title}>A new property on every {nouns.one}</span>
      <div className={styles.field}>
        <label htmlFor={nameId} className={styles.fieldName}>
          Name
        </label>
        <TextInput id={nameId} label="Property name" testId="interaction-property-name" value={newProp.name} onChange={(name) => setNewProp({ ...newProp, name })} />
      </div>
      <div className={styles.field}>
        <span className={styles.fieldName}>Type</span>
        <RadioChoices
          label="Property type"
          value={newProp.type}
          onChange={(type) => setNewProp({ ...newProp, type: type as PropertyType, value: "" })}
          options={PROPERTY_TYPES.filter((t) => t !== "choice").map((t) => ({ value: t, label: TYPE_LABEL[t] }))}
        />
      </div>
      <PropertyField def={{ name: "default value", type: newProp.type }} value={newProp.value} hint={`for every ${nouns.one}`} testId="interaction-property-value" onChange={(value) => setNewProp({ ...newProp, value })} />
      {taken ? <span className={styles.problem}>The layer has that property already.</span> : null}
      <span className={styles.formButtons}>
        <button
          type="button"
          data-testid="interaction-property-add"
          className={`nodrag nopan ${styles.primary}`}
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
