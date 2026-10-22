/**
 * The pieces every form of the Map Edits node's workbench shares (#662): what
 * a feature is called, the icon of a kind of geometry, the way back with Show
 * only this layer beside it, and the choice of picking by a click or by a
 * rule.
 */
import React from "react";
import type { GeometryKind } from "../../utils/editFeatures/layerModel";
import styles from "./EditFeatures.module.css";

/** What one feature of the layer worked on is called, and several. */
export interface Nouns {
  one: string;
  many: string;
}

/** How a feature is picked: by a click on the map, or by a rule. */
export type PickMode = "click" | "rule";

export const plural = (n: number, one: string, many: string) => `${n.toLocaleString()} ${n === 1 ? one : many}`;

/** Where the drawing happens. */
export const onTheMap = "on the map";

/** An on/off switch: a way of changing the picked feature's shape. */
export function ShapeSwitch({ on, icon, label, testId, onToggle }: { on: boolean; icon: "points" | "whole"; label: string; testId: string; onToggle: () => void }) {
  return (
    <button type="button" role="switch" aria-checked={on} data-testid={testId} className={`nodrag nopan ${styles.switch} ${on ? styles.switchOn : ""}`} onClick={onToggle}>
      <svg className={styles.switchIcon} width={18} height={18} viewBox="0 0 18 18" aria-hidden="true">
        {icon === "points" ? (
          <>
            <polyline points="3,14 8,4 15,9" fill="none" stroke="currentColor" strokeWidth={1.6} strokeLinejoin="round" />
            <rect x={1.5} y={12.5} width={3} height={3} fill="#FFFFFF" stroke="currentColor" strokeWidth={1.4} />
            <rect x={6.5} y={2.5} width={3} height={3} fill="#FFFFFF" stroke="currentColor" strokeWidth={1.4} />
            <rect x={13.5} y={7.5} width={3} height={3} fill="#FFFFFF" stroke="currentColor" strokeWidth={1.4} />
          </>
        ) : (
          <path d="M9 1.5v15M1.5 9h15M9 1.5l-2.2 2.2M9 1.5l2.2 2.2M9 16.5l-2.2-2.2M9 16.5l2.2-2.2M1.5 9l2.2-2.2M1.5 9l2.2 2.2M16.5 9l-2.2-2.2M16.5 9l-2.2 2.2" fill="none" stroke="currentColor" strokeWidth={1.6} strokeLinecap="round" />
        )}
      </svg>
      <span className={styles.switchLabel}>{label}</span>
      <span className={styles.switchTrack} aria-hidden="true">
        <span className={styles.switchKnob} />
      </span>
      <span className={styles.switchState} aria-hidden="true">{on ? "On" : "Off"}</span>
    </button>
  );
}

export function KindIcon({ kind, size = 16 }: { kind: GeometryKind; size?: number }) {
  if (kind === "points") {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
        <circle cx="12" cy="12" r="5" />
      </svg>
    );
  }
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d={kind === "lines" ? "M4 18L10 8l4 6 6-9" : "M5 7l8-3 6 7-4 9-10-3z"} />
    </svg>
  );
}

/** Show only this layer: the map hides its other layers while one is worked on. */
export function SoloSwitch({ solo, setSolo }: { solo: boolean; setSolo: (solo: boolean) => void }) {
  return (
    <label className={`nodrag nopan ${styles.soloSwitch}`} title="Hide the map's other layers while you work on this one">
      <input type="checkbox" role="switch" data-testid="interaction-solo" checked={solo} onChange={(e) => setSolo(e.target.checked)} />
      <span className={styles.track} aria-hidden="true" />
      Show only this layer
    </label>
  );
}

/** The way back from an action to the layer's actions, with Show only this layer beside it. */
export function BackRow({ label, onBack, solo }: { label: string; onBack: () => void; solo: React.ReactNode }) {
  return (
    <div className={styles.backRow}>
      <button type="button" data-testid="interaction-back" className={`nodrag nopan ${styles.back}`} onClick={onBack}>
        ← {label}
      </button>
      {solo}
    </div>
  );
}

/** Picking by a click on the map, or by a rule. */
export function PickBy({ current, choose, testId }: { current: PickMode; choose: (by: PickMode) => void; testId: string }) {
  return (
    <span className={styles.segmented} role="group" aria-label="Pick by">
      <button type="button" aria-pressed={current === "click"} className={`nodrag nopan ${current === "click" ? styles.on : ""}`} onClick={() => choose("click")}>
        Click
      </button>
      <button type="button" aria-pressed={current === "rule"} data-testid={testId} className={`nodrag nopan ${current === "rule" ? styles.on : ""}`} onClick={() => choose("rule")}>
        By a rule
      </button>
    </span>
  );
}
