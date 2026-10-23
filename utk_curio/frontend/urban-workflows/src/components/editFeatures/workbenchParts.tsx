/**
 * The pieces every form of the Map Edits node's workbench shares (#662): what
 * a feature and a property's type are called, the icon of a kind of
 * geometry, the way back with Show only this layer beside it, and a choice of
 * one (picking by a click or by a rule, how a shape is changed), as the
 * canvas bar's view switch is one (`CanvasViewSwitch`).
 */
import React from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faDrawPolygon, faLocationDot, faRoute, type IconDefinition } from "@fortawesome/free-solid-svg-icons";
import type { PropertyType } from "../../utils/editFeatures/editFeatures";
import type { GeometryKind } from "../../utils/editFeatures/layerModel";
import { CheckboxInput } from "./fields";
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

/** What a property's type is called, in one spelling everywhere. */
export const TYPE_LABEL: Record<PropertyType, string> = { text: "Text", number: "Number", boolean: "Yes / no", choice: "Choice", date: "Date" };

const KIND_ICON: Record<GeometryKind, IconDefinition> = { points: faLocationDot, lines: faRoute, areas: faDrawPolygon };

export function KindIcon({ kind }: { kind: GeometryKind }) {
  return <FontAwesomeIcon icon={KIND_ICON[kind]} className={styles.icon} aria-hidden />;
}

/** One option of a choice of one. */
export interface ModeOption<T extends string> {
  value: T;
  label: string;
  icon?: IconDefinition;
  testId?: string;
  /** Off: shown, and not picked by a click. */
  disabled?: boolean;
}

/** A choice of one: a bordered group of options, the one picked filled. */
export function ModeSwitch<T extends string>({
  label,
  value,
  options,
  onChange,
}: {
  /** The group's accessible name. */
  label: string;
  value: T;
  options: ModeOption<T>[];
  onChange: (value: T) => void;
}) {
  return (
    <div className={styles.modes} role="radiogroup" aria-label={label}>
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          role="radio"
          aria-checked={value === option.value}
          data-testid={option.testId}
          disabled={option.disabled}
          className={`nodrag nopan ${styles.mode} ${value === option.value ? styles.modeChecked : ""}`}
          onClick={() => onChange(option.value)}
        >
          {option.icon ? <FontAwesomeIcon icon={option.icon} aria-hidden /> : null}
          {option.label}
        </button>
      ))}
    </div>
  );
}

/** Show only this layer: the map hides its other layers while one is worked on. */
export function SoloSwitch({ solo, setSolo }: { solo: boolean; setSolo: (solo: boolean) => void }) {
  return (
    <CheckboxInput
      checked={solo}
      onChange={setSolo}
      text="Show only this layer"
      title="Hide the map's other layers while you work on this one"
      testId="interaction-solo"
      role="switch"
    />
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
    <ModeSwitch
      label="Pick by"
      value={current}
      onChange={choose}
      options={[
        { value: "click", label: "Click" },
        { value: "rule", label: "By a rule", testId },
      ]}
    />
  );
}
