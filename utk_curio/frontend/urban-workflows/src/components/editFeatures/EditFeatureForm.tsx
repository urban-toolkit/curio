/**
 * Edit one feature in the Map Editor node's workbench (#662): picked on the
 * map, it is reshaped or moved there (`GeometryTools`) and its values are
 * changed here. Nothing picked yet, the form says how to pick.
 *
 * A feature of several parts, an OpenStreetMap building's, is edited on all
 * its parts at once, or on the one chosen in its parts menu (#1110).
 */
import React from "react";
import type { PropertyDef } from "../../utils/editFeatures/editFeatures";
import type { PartsForm } from "../../utils/editFeatures/featureParts";
import { formProblems, type EditedFeature } from "../../utils/editFeatures/layerModel";
import { SelectInput, TextInput } from "./fields";
import { onTheMap, type Nouns } from "./workbenchParts";
import styles from "./EditFeatures.module.css";

/** The value of a menu's blank choice: no value chosen, in a field its parts differ in. */
const NO_CHOICE = "\u0000";

/** The parts menu of a feature of several parts. */
export interface PartsChoice {
  count: number;
  /** Each part, in the layer's order, by the value it is chosen by and its name; null when nothing tells them apart. */
  options: { value: string; label: string }[] | null;
  /** The part chosen, or "" for all of them. */
  choice: string;
  onChoose: (value: string) => void;
}

export default function EditFeatureForm({
  back,
  nouns,
  pickBy,
  feature,
  geometry,
  parts = null,
  defs,
  shown,
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
  /** Its parts menu, when it has several parts. */
  parts?: PartsChoice | null;
  defs: PropertyDef[];
  /** What the form shows of its properties: their values, and those its parts differ in or that cannot be changed. */
  shown: Pick<PartsForm, "values" | "mixed" | "fixed">;
  /** The values its fields show, as text; none for a field its parts differ in that nothing was typed or chosen in. */
  texts: Record<string, string>;
  setTexts: (texts: Record<string, string>) => void;
  /** The properties whose field differs from what the form shows of them. */
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
  // A property that cannot be changed asks for nothing, nor does one the
  // parts differ in until a value is typed or chosen in it.
  const asked = defs.filter((def) => !(def.name in shown.fixed) && !(def.name in shown.mixed && texts[def.name] === undefined));
  const problems = formProblems(asked, texts);
  const capital = nouns.one[0].toUpperCase() + nouns.one.slice(1);
  const partsId = `edit-${nodeId}-parts`;
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
      <div className={styles.section} data-testid="interaction-properties">
        <div className={styles.sectionHead}>
          Properties
          {dirty.length > 0 ? (
            <span className={styles.changed} data-tone="stale">
              {dirty.length} changed
            </span>
          ) : null}
        </div>
        <div className={styles.grid}>
          {parts?.options ? (
            <>
              <label htmlFor={partsId} className={styles.gridLabel}>
                Parts
              </label>
              <span className={styles.gridValue}>
                <SelectInput id={partsId} label="Parts" testId="interaction-parts-menu" value={parts.choice} onChange={parts.onChoose}>
                  <option value="">{`All ${parts.count} parts`}</option>
                  {parts.options.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </SelectInput>
              </span>
            </>
          ) : parts ? (
            // Nothing tells its parts apart: the form is on all of them.
            <>
              <span className={styles.gridLabel}>Parts</span>
              <span className={styles.gridValue} data-testid="interaction-parts-all">{`All ${parts.count} parts`}</span>
            </>
          ) : null}
          {defs.map((def) => {
            if (def.name in shown.fixed) {
              return (
                <React.Fragment key={def.name}>
                  <span data-tooltip={def.name} className={styles.gridLabel}>
                    {def.name}
                  </span>
                  <span className={`${styles.gridValue} ${styles.hint}`} data-testid={`interaction-fixed-${def.name}`}>
                    {shown.fixed[def.name]}
                  </span>
                </React.Fragment>
              );
            }
            const before = shown.values[def.name];
            const mixed = shown.mixed[def.name];
            const isDirty = dirty.includes(def);
            const id = `edit-${nodeId}-${def.name}`;
            const choices = def.type === "choice" ? def.choices ?? [] : def.type === "boolean" ? ["true", "false"] : null;
            const text = texts[def.name] ?? "";
            // A field the parts differ in changes none of them while it is
            // left blank, or its menu on no choice; "(empty)" is a choice.
            const change = (next: string) => {
              const rest = { ...texts };
              if (mixed !== undefined && (choices ? next === NO_CHOICE : next.trim() === "")) delete rest[def.name];
              else rest[def.name] = next;
              setTexts(rest);
            };
            const unchosen = mixed !== undefined && texts[def.name] === undefined;
            const note = mixed ?? (isDirty ? `was ${before === null || before === undefined || before === "" ? "empty" : String(before)}` : null);
            return (
              <React.Fragment key={def.name}>
                <label htmlFor={id} data-tooltip={def.name} className={styles.gridLabel}>
                  {def.name}
                </label>
                <span className={styles.gridValue} data-field={def.name}>
                  {choices ? (
                    <SelectInput id={id} label={def.name} className={isDirty ? styles.dirty : undefined} testId={`interaction-field-${def.name}`} value={unchosen ? NO_CHOICE : text} onChange={change}>
                      {mixed !== undefined ? <option value={NO_CHOICE}></option> : null}
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
                </span>
                {note !== null ? (
                  // Under the field, which keeps its whole width.
                  <span className={styles.fieldNote} data-testid={mixed !== undefined ? `interaction-mixed-${def.name}` : undefined}>
                    {note}
                  </span>
                ) : null}
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
