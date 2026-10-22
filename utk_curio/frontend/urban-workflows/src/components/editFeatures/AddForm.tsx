/**
 * Add in the Map Edits node's workbench (#662): a feature drawn on the map,
 * part by part, then the layer's own properties filled in, the values it
 * holds offered as choices.
 */
import React from "react";
import type { Geometry, PropertyDef } from "../../utils/editFeatures/editFeatures";
import { KIND_NOUN, formProblems, type GeometryKind } from "../../utils/editFeatures/layerModel";
import { partsOf } from "../../utils/editFeatures/geometryParts";
import type { WorkbenchLayer } from "./LayerWorkbench";
import { PropertyField, fieldHint } from "./PropertyField";
import { onTheMap, type Nouns } from "./workbenchParts";
import styles from "./EditFeatures.module.css";

export default function AddForm({
  back,
  active,
  kind,
  nouns,
  defs,
  drawn,
  partFor,
  texts,
  setTexts,
  onAdd,
  onAddPart,
  onCancelPart,
  onDiscard,
}: {
  back: React.ReactNode;
  active: WorkbenchLayer;
  kind: GeometryKind;
  nouns: Nouns;
  /** The properties a new feature of the layer is asked for. */
  defs: PropertyDef[];
  /** The shape drawn, not yet added. */
  drawn: Geometry | null;
  /** Whether one more part of the shape drawn is being drawn. */
  partFor: "draft" | "picked" | null;
  texts: Record<string, string>;
  setTexts: (texts: Record<string, string>) => void;
  onAdd: () => void;
  onAddPart: () => void;
  onCancelPart: () => void;
  onDiscard: () => void;
}) {
  const problems = formProblems(defs, texts);
  const draftParts = partsOf(drawn).length;
  return drawn && partFor !== "draft" ? (
    <div className={styles.form} data-testid="interaction-property-form">
      {back}
      <span className={styles.title}>New {nouns.one}: its properties</span>
      {draftParts > 1 ? <span className={styles.hint} data-testid="interaction-part-count">{draftParts} parts</span> : null}
      <span className={styles.hint}>
        {active.newLayer ? "The fields are the properties the layer was made with." : "The fields are the layer's columns, and the choices are the values already in it."}
      </span>
      {defs.length === 0 ? <span className={styles.hint}>This layer has no properties to fill in.</span> : null}
      {defs.map((def) => (
        <PropertyField key={def.name} def={def} value={texts[def.name] ?? ""} hint={fieldHint(def, active.fc)} testId={`interaction-field-${def.name}`} onChange={(text) => setTexts({ ...texts, [def.name]: text })} />
      ))}
      {problems.length > 0 ? <span className={styles.problem}>{problems.join(" · ")}</span> : null}
      <span className={styles.formButtons}>
        <button type="button" className={`nodrag nopan ${styles.button}`} onClick={onDiscard}>
          Discard {KIND_NOUN[kind]}
        </button>
        <button type="button" className={`nodrag nopan ${styles.button}`} data-testid="interaction-add-part" onClick={onAddPart}>
          Add another part
        </button>
        <button type="button" className={`nodrag nopan ${styles.primary}`} data-testid="interaction-form-submit" disabled={problems.length > 0} onClick={onAdd}>
          Add {nouns.one}
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
        <button type="button" className={`nodrag nopan ${styles.button}`} data-testid="interaction-cancel-part" onClick={onCancelPart}>
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
      <span className={styles.hint}>Its properties are asked for next. Drag to move the map, or press Esc to give up.</span>
    </div>
  );
}
