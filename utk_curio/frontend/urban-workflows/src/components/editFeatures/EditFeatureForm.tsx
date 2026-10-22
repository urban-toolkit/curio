/**
 * Edit one feature in the Map Edits node's workbench (#662): picked on the
 * map, it is reshaped or moved there (`GeometryTools`) and its values are
 * changed here. Nothing picked yet, the form says how to pick.
 */
import React from "react";
import type { PropertyDef } from "../../utils/editFeatures/editFeatures";
import { formProblems, type EditedFeature } from "../../utils/editFeatures/layerModel";
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
        <span className={styles.lead}>Click a {nouns.one} {onTheMap} to select it; shift-click adds one.</span>
        <span className={styles.hint}>One picked: drag its points to reshape it, or change its values here. Several: change one value of them all.</span>
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
        <span className={styles.kind}>1 selected</span>
      </div>
      <div className={styles.section} data-testid="interaction-selection">
        <div className={styles.sectionHead}>
          <b>Selection</b>
        </div>
        <span className={styles.hint}>Shift-click {nouns.many} {onTheMap} to pick more.</span>
      </div>
      {geometry}
      <div className={styles.section}>
        <div className={styles.sectionHead}>
          <b>Properties</b>
          {dirty.length > 0 ? <span className={styles.changed}>{dirty.length} changed</span> : null}
        </div>
        <div className={styles.grid}>
          {defs.map((def) => {
            const before = feature.properties[def.name];
            const isDirty = dirty.includes(def);
            const id = `edit-${nodeId}-${def.name}`;
            const choices = def.type === "choice" ? def.choices ?? [] : def.type === "boolean" ? ["true", "false"] : null;
            const text = texts[def.name] ?? "";
            return (
              <React.Fragment key={def.name}>
                <label htmlFor={id} title={def.name}>
                  {def.name}
                </label>
                <span style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  {choices ? (
                    <select id={id} className={`nodrag nopan ${isDirty ? styles.dirty : ""}`} data-testid={`interaction-field-${def.name}`} value={text} onChange={(e) => setTexts({ ...texts, [def.name]: e.target.value })}>
                      <option value="">(empty)</option>
                      {[...choices, ...(text && !choices.includes(text) ? [text] : [])].map((c) => (
                        <option key={c} value={c}>
                          {c}
                        </option>
                      ))}
                    </select>
                  ) : (
                    <input id={id} className={`nodrag nopan ${styles.input} ${isDirty ? styles.dirty : ""}`} data-testid={`interaction-field-${def.name}`} value={text} onChange={(e) => setTexts({ ...texts, [def.name]: e.target.value })} />
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
        <button type="button" className={`nodrag nopan ${styles.big} ${styles.primary}`} data-testid="interaction-form-submit" disabled={dirty.length === 0 || problems.length > 0} onClick={onApply}>
          Apply changes
        </button>
      </span>
    </div>
  );
}
