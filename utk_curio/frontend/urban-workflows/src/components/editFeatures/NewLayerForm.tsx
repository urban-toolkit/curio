/**
 * + New data layer in the Map Editor node's workbench (#662): the builder of a
 * new layer, its name, its geometry and the properties its features carry.
 */
import React, { useId, useState } from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faXmark } from "@fortawesome/free-solid-svg-icons";
import {
  NEW_LAYER_GEOMETRIES,
  PROPERTY_TYPES,
  type NewLayerDef,
  type NewLayerGeometry,
  type PropertyDef,
  type PropertyType,
} from "../../utils/editFeatures/editFeatures";
import { GEOMETRY_KIND, KIND_LABEL } from "../../utils/editFeatures/layerModel";
import { CheckboxInput, RadioChoices, SelectInput, TextInput } from "./fields";
import { KindIcon, TYPE_LABEL } from "./workbenchParts";
import styles from "./EditFeatures.module.css";

/** The builder of a new layer: its name, its geometry and its properties. */
export default function NewLayerForm({ taken, onCreate, onCancel }: { taken: string[]; onCreate: (def: NewLayerDef) => void; onCancel: () => void }) {
  const nameId = useId();
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
      <div className={styles.field}>
        <label htmlFor={nameId} className={styles.fieldName}>
          Name
        </label>
        <TextInput id={nameId} label="Layer name" testId="interaction-new-layer-name" value={name} placeholder="Cooling centers" onChange={setName} />
      </div>
      <div className={styles.field}>
        <span className={styles.fieldName}>Geometry</span>
        <RadioChoices
          label="Geometry"
          value={geometry}
          onChange={(next) => setGeometry(next as NewLayerGeometry)}
          options={NEW_LAYER_GEOMETRIES.map((g) => ({
            value: g,
            testId: `interaction-new-layer-${g}`,
            label: (
              <span className={styles.titleRow}>
                <KindIcon kind={GEOMETRY_KIND[g]} />
                {KIND_LABEL[GEOMETRY_KIND[g]]}
              </span>
            ),
          }))}
        />
      </div>
      <div className={styles.field}>
        <span className={styles.fieldName}>Properties</span>
        <div className={styles.propGrid}>
          <span className={styles.hint}>Name</span>
          <span className={styles.hint}>Type</span>
          <span className={styles.hint}>Choices or default</span>
          <span className={styles.hint}>Required</span>
          <span />
          {props.map((p, i) => (
            <React.Fragment key={i}>
              <TextInput label={`Property ${i + 1} name`} value={p.name} onChange={(text) => update(i, { name: text })} />
              <SelectInput label={`Property ${i + 1} type`} value={p.type} onChange={(type) => update(i, { type: type as PropertyType })}>
                {PROPERTY_TYPES.map((t) => (
                  <option key={t} value={t}>
                    {TYPE_LABEL[t]}
                  </option>
                ))}
              </SelectInput>
              {p.type === "choice" ? (
                <TextInput label={`Property ${i + 1} choices`} placeholder="library, school, …" value={p.choices} onChange={(text) => update(i, { choices: text })} />
              ) : (
                <TextInput label={`Property ${i + 1} default`} placeholder="default" value={p.def} onChange={(text) => update(i, { def: text })} />
              )}
              <CheckboxInput label={`Property ${i + 1} required`} checked={p.required} onChange={(checked) => update(i, { required: checked })} />
              <button type="button" className={`nodrag nopan ${styles.iconButton}`} aria-label={`Remove property ${i + 1}`} data-tooltip="Remove this property" onClick={() => setProps(props.filter((_, j) => j !== i))}>
                <FontAwesomeIcon icon={faXmark} aria-hidden />
              </button>
            </React.Fragment>
          ))}
        </div>
        <span className={styles.toolRow}>
          <button type="button" className={`nodrag nopan ${styles.button}`} data-testid="interaction-new-layer-add-property" onClick={() => setProps([...props, { name: "", type: "text", required: false, choices: "", def: "" }])}>
            + Add property
          </button>
          <span className={styles.hint}>Types: {PROPERTY_TYPES.map((t) => TYPE_LABEL[t]).join(", ")}.</span>
        </span>
      </div>
      {problem && name !== "" ? <span className={styles.problem}>{problem}</span> : null}
      <span className={styles.formButtons}>
        <button type="button" className={`nodrag nopan ${styles.button}`} onClick={onCancel}>
          Cancel
        </button>
        <button type="button" className={`nodrag nopan ${styles.primary}`} data-testid="interaction-new-layer-create" disabled={problem !== null} onClick={create}>
          Create layer and start drawing
        </button>
      </span>
    </div>
  );
}
