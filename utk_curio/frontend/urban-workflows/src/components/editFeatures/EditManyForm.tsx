/**
 * Edit several features picked on the map, in the Map Editor node's workbench
 * (#662): one value of them all.
 */
import React from "react";
import type { SelectionId } from "../../utils/references/selectionTags";
import type { FeatureEdit, PropertyDef } from "../../utils/editFeatures/editFeatures";
import { valueChange, type ValueChangeState } from "./ValueChange";
import { plural, type Nouns } from "./workbenchParts";
import styles from "./EditFeatures.module.css";

export default function EditManyForm({
  back,
  nouns,
  picked,
  defs,
  change: changeState,
  onApply,
  onClearPick,
}: {
  back: React.ReactNode;
  nouns: Nouns;
  /** The features picked. */
  picked: SelectionId[];
  defs: PropertyDef[];
  change: ValueChangeState;
  /** Writes the edit on the picked features. */
  onApply: (edit: FeatureEdit) => void;
  onClearPick: () => void;
}) {
  const change = valueChange(defs, changeState);
  const ready = change.make({ ids: picked });
  return (
    <div className={styles.form} data-testid="interaction-edit-many">
      {back}
      <span className={styles.title}>Edit {nouns.many}</span>
      <span className={styles.lead}>{plural(picked.length, nouns.one, nouns.many)} picked.</span>
      {change.section}
      <span className={styles.formButtons}>
        <button type="button" className={`nodrag nopan ${styles.button}`} onClick={onClearPick}>
          Clear the pick
        </button>
        <button
          type="button"
          data-testid="interaction-many-apply"
          className={`nodrag nopan ${styles.primary}`}
          disabled={!ready}
          onClick={() => {
            if (!ready) return;
            onApply(ready);
          }}
        >
          Apply to {plural(picked.length, nouns.one, nouns.many)}
        </button>
      </span>
      <span className={styles.hint}>Shift-click adds or drops one.</span>
    </div>
  );
}
