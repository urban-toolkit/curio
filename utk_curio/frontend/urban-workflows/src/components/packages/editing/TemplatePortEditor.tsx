import React from "react";
import type { PortDraft } from "../../../pages/nodes/factoryDraftModel";
import { factoryUiMakeId } from "../../../pages/nodes/factoryDraftModel";
import {
  SUPPORTED_PORT_TYPES,
  isSupportedPortType,
  normalizePortTypes,
} from "../../../constants/supportedPortTypes";
import styles from "./NodeTemplateConfigModal.module.css";

const CARDINALITY_OPTIONS = ["1", "n", "[0,1]", "[1,n]", "[1,2]", "2"];

/**
 * One row per PORT, and inside it one row per TYPE.
 *
 * Every control's accessible name carries *title* ("Input ports" /
 * "Output ports"), because the two editors render side by side and a bare
 * "Port 1 type 1" would name a control in each of them.
 *
 * The types field used to be a single free-text input whose placeholder
 * ("DATAFRAME, GEODATAFRAME") was the only statement of both the vocabulary and
 * the separator (#219). Nothing validated it: an unrecognised value passed the
 * editor and was dropped by ``asSupportedTypes`` on the way into the registry,
 * so a port silently lost a type. The cardinality control beside it was already
 * a ``<select>``, so the free text was an inconsistency within one row rather
 * than a considered design.
 */
export function TemplatePortEditor({
  title,
  ports,
  onChange,
}: {
  title: string;
  ports: PortDraft[];
  onChange: (ports: PortDraft[]) => void;
}) {
  const addPort = () =>
    onChange([
      ...ports,
      { id: factoryUiMakeId(), types: [SUPPORTED_PORT_TYPES[0]], cardinality: "1" },
    ]);
  const removePort = (i: number) => onChange(ports.filter((_, idx) => idx !== i));
  const patchPort = (i: number, p: Partial<PortDraft>) =>
    onChange(ports.map((port, idx) => (idx === i ? { ...port, ...p } : port)));

  const setTypes = (i: number, types: string[]) => patchPort(i, { types });

  return (
    <div className={styles.field}>
      <label className={styles.fieldLabel}>{title}</label>
      {ports.map((port, i) => {
        // Tolerates a draft persisted before this was an array: a canvas node's
        // stored config still carries the old comma string.
        const types = normalizePortTypes(port.types);
        return (
          <div key={port.id} className={styles.portGroup}>
            <div className={styles.portGroupHeader}>
              <span className={styles.portGroupTitle}>Port {i + 1}</span>
              <select
                className={styles.select}
                aria-label={`${title} port ${i + 1} cardinality`}
                value={port.cardinality}
                onChange={(e) => patchPort(i, { cardinality: e.target.value })}
              >
                {/* Same escape hatch as the type rows: a stored cardinality
                    outside the list would otherwise render blank and be
                    rewritten to the first option on the next edit. */}
                {(CARDINALITY_OPTIONS.includes(port.cardinality)
                  ? CARDINALITY_OPTIONS
                  : [port.cardinality, ...CARDINALITY_OPTIONS]
                ).map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
              </select>
              <button
                type="button"
                className={styles.smallBtn}
                aria-label={`Remove ${title} port ${i + 1}`}
                onClick={() => removePort(i)}
              >
                ✕
              </button>
            </div>

            <div className={styles.typeGrid}>
              {types.map((type, ti) => (
                <div key={`${port.id}-${ti}`} className={styles.typeRow}>
                  <select
                    className={styles.select}
                    aria-label={`${title} port ${i + 1} type ${ti + 1}`}
                    value={type}
                    onChange={(e) =>
                      setTypes(
                        i,
                        types.map((t, idx) => (idx === ti ? e.target.value : t)),
                      )
                    }
                  >
                    {/* An unknown stored value is offered as its own option
                        rather than silently rendering an empty select that
                        would overwrite it on the next change. */}
                    {!isSupportedPortType(type) ? (
                      <option value={type}>{type} (unrecognised)</option>
                    ) : null}
                    {SUPPORTED_PORT_TYPES.map((t) => (
                      <option key={t} value={t}>
                        {t}
                      </option>
                    ))}
                  </select>
                  <button
                    type="button"
                    className={styles.smallBtn}
                    aria-label={`Remove ${title} port ${i + 1} type ${ti + 1}`}
                    // A port with no types accepts nothing, so the last one
                    // stays put. Removing the PORT is the way to say "none".
                    disabled={types.length <= 1}
                    onClick={() => setTypes(i, types.filter((_, idx) => idx !== ti))}
                  >
                    ✕
                  </button>
                </div>
              ))}
            </div>

            <button
              type="button"
              className={styles.smallBtn}
              aria-label={`Add ${title} port ${i + 1} type`}
              onClick={() =>
                setTypes(i, [
                  ...types,
                  // Offer a type the port does not already have, so adding
                  // twice in a row cannot produce a duplicate.
                  SUPPORTED_PORT_TYPES.find((t) => !types.includes(t)) ??
                    SUPPORTED_PORT_TYPES[0],
                ])
              }
              disabled={types.length >= SUPPORTED_PORT_TYPES.length}
            >
              + Add type
            </button>
          </div>
        );
      })}
      <button
        type="button"
        className={styles.smallBtn}
        aria-label={`Add ${title} port`}
        onClick={addPort}
      >
        + Add port
      </button>
    </div>
  );
}
