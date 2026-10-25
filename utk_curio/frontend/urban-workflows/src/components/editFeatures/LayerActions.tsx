/**
 * A layer picked in the Map Editor node's workbench (#662): what to do with
 * it, four cards. Add (draw on the map, then fill in the layer's own
 * properties), Edit (pick a feature on the map, reshape or move it, change
 * its values), Remove (pick features on the map, or by a rule) and Add a
 * property (a new column with a value for every feature).
 */
import React from "react";
import { KIND_LABEL, KIND_NOUN, type GeometryKind } from "../../utils/editFeatures/layerModel";
import type { Action, WorkbenchLayer } from "./LayerWorkbench";
import { KindIcon, type Nouns } from "./workbenchParts";
import styles from "./EditFeatures.module.css";

export default function LayerActions({
  active,
  kind,
  nouns,
  count,
  canEdit,
  writable,
  solo,
  onAllLayers,
  onAction,
  onNewLayer,
}: {
  active: WorkbenchLayer;
  kind: GeometryKind;
  nouns: Nouns;
  /** How many features the layer holds, as the log leaves it. */
  count: number;
  /** Whether the layer has a column that identifies its features. */
  canEdit: boolean;
  writable: boolean;
  /** Show only this layer. */
  solo: React.ReactNode;
  onAllLayers: () => void;
  onAction: (action: Action) => void;
  onNewLayer: () => void;
}) {
  const cards: { action: Action; title: string; text: string }[] = [
    { action: "add", title: `+ Add ${nouns.many}`, text: kind === "points" ? "Click the map to place them, then fill in their properties." : `Draw new ${KIND_NOUN[kind]}s, then fill in their properties.` },
    { action: "edit", title: `Edit ${nouns.many}`, text: `Change a${kind === "areas" ? "n" : ""} ${KIND_NOUN[kind]}'s shape or its values.` },
    { action: "remove", title: `Remove ${nouns.many}`, text: "Click them on the map, or pick them by a rule." },
    { action: "property", title: "Add a property", text: `A new column on every ${nouns.one}, with a default value.` },
  ];
  return (
    <>
      <div className={styles.backRow}>
        <button type="button" className={`nodrag nopan ${styles.back}`} onClick={onAllLayers}>
          ← All layers
        </button>
        {solo}
      </div>
      <div className={styles.titleRow}>
        <KindIcon kind={kind} />
        <span className={styles.title}>{active.label}</span>
        <span className={styles.meta}>
          {KIND_LABEL[kind].toLowerCase()} · {count.toLocaleString()}
        </span>
      </div>
      {!canEdit ? (
        <span className={styles.problem}>This layer has no column that identifies its features, so they cannot be edited or removed: add an id column upstream. You can still draw into a new layer.</span>
      ) : null}
      <span className={styles.lead}>What do you want to do?</span>
      <div className={styles.actionGrid}>
        {cards.map((card) => (
          <button key={card.action} type="button" data-testid={`interaction-action-${card.action}`} className={`nodrag nopan ${styles.actionCard}`} disabled={!writable || !canEdit} onClick={() => onAction(card.action)}>
            <span className={styles.actionTitle}>{card.title}</span>
            <span className={styles.actionText}>{card.text}</span>
          </button>
        ))}
      </div>
      {writable ? (
        <div className={styles.footer}>
          <button type="button" className={`nodrag nopan ${styles.button}`} onClick={onNewLayer}>
            + New data layer instead
          </button>
        </div>
      ) : null}
    </>
  );
}
