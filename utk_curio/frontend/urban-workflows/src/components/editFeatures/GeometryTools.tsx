/**
 * The geometry tools of a feature picked in the Map Edits node's Edit (#662):
 * one way at a time of what a drag on the map does, panning it, moving the
 * feature's points or moving it whole, and a part added to it. A feature of
 * several parts that no osm_id tells apart keeps its shape: the tools are
 * off, and a tip says why (#1092).
 */
import React from "react";
import { faBezierCurve, faHand, faUpDownLeftRight } from "@fortawesome/free-solid-svg-icons";
import { KIND_NOUN, type EditedFeature, type GeometryKind } from "../../utils/editFeatures/layerModel";
import { partsOf } from "../../utils/editFeatures/geometryParts";
import { ModeSwitch, onTheMap, type ModeOption, type Nouns } from "./workbenchParts";
import styles from "./EditFeatures.module.css";

/** How the picked feature's shape is changed, or null: neither, and a drag pans the map. */
export type ShapeMode = "reshape" | "move" | null;

export default function GeometryTools({
  kind,
  nouns,
  feature,
  refusal = null,
  shapeMode,
  onShapeMode,
  partFor,
  onAddPart,
  onCancelPart,
}: {
  kind: GeometryKind;
  nouns: Nouns;
  /** The feature picked. */
  feature: EditedFeature;
  /** Why its shape cannot be changed on the map, which turns the tools off; null when it can. */
  refusal?: string | null;
  shapeMode: ShapeMode;
  onShapeMode: (mode: ShapeMode) => void;
  /** Whether a part is being drawn for the picked feature. */
  partFor: "draft" | "picked" | null;
  onAddPart: () => void;
  onCancelPart: () => void;
}) {
  const parts = partsOf(feature.geometry).length;
  const off = refusal !== null;
  const modes: ModeOption<"pan" | "reshape" | "move">[] = [
    { value: "pan", label: "Pan", icon: faHand, testId: "interaction-pan" },
    { value: "reshape", label: kind === "points" ? "Move point" : "Move points", icon: faBezierCurve, testId: "interaction-reshape", disabled: off },
    // A point is one corner: moving it whole is moving its point.
    ...(kind === "points" ? [] : [{ value: "move" as const, label: `Move whole ${nouns.one}`, icon: faUpDownLeftRight, testId: "interaction-move", disabled: off }]),
  ];
  return (
    <div className={styles.section}>
      <div className={styles.sectionHead}>
        Geometry
        {feature.status === "redrawn" ? (
          <span className={styles.changed} data-tone="stale">
            changed
          </span>
        ) : null}
      </div>
      <ModeSwitch label="Shape" value={off ? "pan" : shapeMode ?? "pan"} options={modes} onChange={(mode) => onShapeMode(mode === "pan" ? null : mode)} />
      <span className={styles.toolRow}>
        {partFor === "picked" && !off ? (
          <button type="button" className={`nodrag nopan ${styles.button}`} data-testid="interaction-cancel-part" onClick={onCancelPart}>
            Cancel the new part
          </button>
        ) : (
          <button type="button" className={`nodrag nopan ${styles.button}`} data-testid="interaction-add-part" disabled={off} onClick={onAddPart}>
            + Add a part
          </button>
        )}
        {parts > 1 ? (
          <span className={styles.hint} data-testid="interaction-part-count">
            {parts} parts
          </span>
        ) : null}
      </span>
      <span className={styles.hint} data-testid={off ? "interaction-parts-untold" : undefined}>
        {off
          ? refusal
          : partFor === "picked"
          ? kind === "points"
            ? `Click ${onTheMap} to place the new ${KIND_NOUN[kind]}. It joins this ${nouns.one}.`
            : `Draw the new part ${onTheMap}: click to add points, then double-click or press Enter. It joins this ${nouns.one}.`
          : shapeMode === null
          ? `Pick ${kind === "points" ? "Move point to move it" : `Move points or Move whole ${nouns.one} to change its shape`}. Until then, a drag ${onTheMap} pans it.`
          : shapeMode === "reshape"
          ? kind === "points"
            ? `Drag the ${nouns.one} ${onTheMap} to move it. The change is kept when you let go.`
            : `Drag its points ${onTheMap}. Click or drag a midpoint to add one, and alt-click a point to delete it${parts > 1 ? ", or inside a part to remove that part" : ""}. Each change is kept when you let go.`
          : `Hold shift and drag the ${nouns.one} ${onTheMap} to move it. A drag without shift pans the map.`}
      </span>
    </div>
  );
}
