/**
 * Edit one feature in the Map Edits node's workbench (#662): picked on the
 * map, it is reshaped or moved there (`GeometryTools`) and its values are
 * changed here. Nothing picked yet, the form says how to pick.
 */
import React from "react";
import type { PropertyDef } from "../../utils/editFeatures/editFeatures";
import { formProblems, type EditedFeature } from "../../utils/editFeatures/layerModel";
import { SelectInput, TextInput } from "./fields";
import { onTheMap, type Nouns } from "./workbenchParts";
import styles from "./EditFeatures.module.css";

export default function EditFeatureForm({
  back,
  nouns,
  pickBy,
  feature,
  geometry,
  defs,
  texts,
  setTexts,
  dirty,
  nodeId,
  onApply,
}: {
  back: React.ReactNode;
  nouns: Nouns;
  /** Picking by a click or by a rule. */
  pickBy: React.ReactNode;
  /** The one feature picked, or undefined while none is. */
  feature: EditedFeature | undefined;
  /** Its geometry tools. */
  geometry: React.ReactNode;
  defs: PropertyDef[];
  /** The values its fields show, as text. */
  texts: Record<string, string>;
  setTexts: (texts: Record<string, string>) => void;
  /** The properties whose field differs from the feature's value. */
  dirty: PropertyDef[];
  nodeId: string;
  onApply: () => void;
}) {
  if (!feature) {
    return (
      <div className={styles.form}>
        {back}
        <span className={styles.title}>Edit {nouns.many}</span>
        {pickBy}
        <span className={styles.lead}>Click a {nouns.one} {onTheMap} to select it. Shift-click adds one.</span>
        <span className={styles.hint}>With one picked, drag its points to reshape it, or change its values here. With several, change one value of them all.</span>
      </div>
    );
  }
  const problems = formProblems(defs, texts);
  const capital = nouns.one[0].toUpperCase() + nouns.one.slice(1);
  return (
    <div className={styles.form}>
      {back}
      <div className={`${styles.titleRow} ${styles.spread}`}>
        <span className={styles.title}>
          {capital} · {String(feature.properties.name ?? feature.id)}
        </span>
        <span className={styles.hint}>1 selected</span>
      </div>
      <div className={styles.section} data-testid="interaction-selection">
        <div className={styles.sectionHead}>Selection</div>
        <span className={styles.hint}>Shift-click {nouns.many} {onTheMap} to pick more.</span>
      </div>
      {geometry}
      <div className={styles.section}>
        <div className={styles.sectionHead}>
          Properties
          {dirty.length > 0 ? (
            <span className={styles.changed} data-tone="stale">
              {dirty.length} changed
            </span>
          ) : null}
        </div>
        <div className={styles.grid}>
          {defs.map((def) => {
            const before = feature.properties[def.name];
            const isDirty = dirty.includes(def);
            const id = `edit-${nodeId}-${def.name}`;
            const choices = def.type === "choice" ? def.choices ?? [] : def.type === "boolean" ? ["true", "false"] : null;
            const text = texts[def.name] ?? "";
            const change = (next: string) => setTexts({ ...texts, [def.name]: next });
            return (
              <React.Fragment key={def.name}>
                <label htmlFor={id} title={def.name} className={styles.gridLabel}>
                  {def.name}
                </label>
                <span className={styles.gridValue}>
                  {choices ? (
                    <SelectInput id={id} label={def.name} className={isDirty ? styles.dirty : undefined} testId={`interaction-field-${def.name}`} value={text} onChange={change}>
                      <option value="">(empty)</option>
                      {[...choices, ...(text && !choices.includes(text) ? [text] : [])].map((c) => (
                        <option key={c} value={c}>
                          {c}
                        </option>
                      ))}
                    </SelectInput>
                  ) : (
                    <TextInput id={id} label={def.name} className={isDirty ? styles.dirty : undefined} testId={`interaction-field-${def.name}`} value={text} onChange={change} />
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
        <button type="button" className={`nodrag nopan ${styles.primary}`} data-testid="interaction-form-submit" disabled={dirty.length === 0 || problems.length > 0} onClick={onApply}>
          Apply changes
        </button>
      </span>
    </div>
  );
}
