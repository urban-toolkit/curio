/**
 * The geometry tools of a feature picked in the Map Edits node's Edit (#662):
 * move its points, or move it whole, on the map, and add a part to it.
 */
import React from "react";
import { KIND_NOUN, type EditedFeature, type GeometryKind } from "../../utils/editFeatures/layerModel";
import { partsOf } from "../../utils/editFeatures/geometryParts";
import { ShapeSwitch, onTheMap, type Nouns } from "./workbenchParts";
import styles from "./EditFeatures.module.css";

/** How the picked feature's shape is changed, or null: neither, and a drag pans the map. */
export type ShapeMode = "reshape" | "move" | null;

export default function GeometryTools({
  kind,
  nouns,
  feature,
  shapeMode,
  onToggleShape,
  partFor,
  onAddPart,
  onCancelPart,
}: {
  kind: GeometryKind;
  nouns: Nouns;
  /** The feature picked. */
  feature: EditedFeature;
  shapeMode: ShapeMode;
  onToggleShape: (mode: "reshape" | "move") => void;
  /** Whether a part is being drawn for the picked feature. */
  partFor: "draft" | "picked" | null;
  onAddPart: () => void;
  onCancelPart: () => void;
}) {
  return (
    <div className={styles.section}>
      <div className={styles.sectionHead}>
        <b>Geometry</b>
        {feature.status === "redrawn" ? <span className={styles.changed}>changed</span> : null}
      </div>
      <span className={styles.switches} role="group" aria-label="Shape">
        <ShapeSwitch
          on={shapeMode === "reshape"}
          icon="points"
          label={kind === "points" ? "Move point" : "Move points"}
          testId="interaction-reshape"
          onToggle={() => onToggleShape("reshape")}
        />
        {/* A point is one corner: moving it whole is moving its point. */}
        {kind === "points" ? null : (
          <ShapeSwitch on={shapeMode === "move"} icon="whole" label={`Move whole ${nouns.one}`} testId="interaction-move" onToggle={() => onToggleShape("move")} />
        )}
      </span>
      <span className={styles.formButtons}>
        {partFor === "picked" ? (
          <button type="button" className={`nodrag nopan ${styles.small}`} data-testid="interaction-cancel-part" onClick={onCancelPart}>
            Cancel the new part
          </button>
        ) : (
          <button type="button" className={`nodrag nopan ${styles.small}`} data-testid="interaction-add-part" onClick={onAddPart}>
            + Add a part
          </button>
        )}
        {partsOf(feature.geometry).length > 1 ? (
          <span className={styles.kind} data-testid="interaction-part-count">
            {partsOf(feature.geometry).length} parts
          </span>
        ) : null}
      </span>
      <span className={styles.hint}>
        {partFor === "picked"
          ? kind === "points"
            ? `Click ${onTheMap} to place the new ${KIND_NOUN[kind]}; it joins this ${nouns.one}.`
            : `Draw the new part ${onTheMap}: click to add points, then double-click or press Enter. It joins this ${nouns.one}.`
          : shapeMode === null
          ? `Turn on ${kind === "points" ? "Move point to move it" : "one of these to change its shape"}. Until then, drag ${onTheMap} to pan it.`
          : shapeMode === "reshape"
          ? kind === "points"
            ? `Drag the ${nouns.one} ${onTheMap} to move it. The change is kept when you let go.`
            : `Drag its points ${onTheMap}; click or drag a midpoint to add one; alt-click a point to delete it${partsOf(feature.geometry).length > 1 ? ", or inside a part to remove that part" : ""}. Each change is kept when you let go.`
          : `Hold shift and drag the ${nouns.one} ${onTheMap} to move it. A drag without shift pans the map.`}
      </span>
    </div>
  );
}
