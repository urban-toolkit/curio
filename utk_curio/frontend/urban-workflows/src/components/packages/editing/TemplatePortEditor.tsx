import React from "react";
import type { PortDraft } from "../../../pages/nodes/factoryDraftModel";
import { factoryUiMakeId } from "../../../pages/nodes/factoryDraftModel";
import { SupportedType } from "../../../constants";
import styles from "./NodeTemplateConfigModal.module.css";

const SUPPORTED_TYPE_OPTIONS = Object.values(SupportedType);
const CARDINALITY_OPTIONS = ["1", "n", "[0,1]", "[1,n]", "[1,2]", "2"];

export function TemplatePortEditor({
  title,
  ports,
  onChange,
}: {
  title: string;
  ports: PortDraft[];
  onChange: (ports: PortDraft[]) => void;
}) {
  const add = () =>
    onChange([
      ...ports,
      { id: factoryUiMakeId(), types: SUPPORTED_TYPE_OPTIONS[0], cardinality: "1" },
    ]);
  const remove = (i: number) => onChange(ports.filter((_, idx) => idx !== i));
  const patch = (i: number, p: Partial<PortDraft>) =>
    onChange(ports.map((port, idx) => (idx === i ? { ...port, ...p } : port)));

  return (
    <div className={styles.field}>
      <label className={styles.fieldLabel}>{title}</label>
      {ports.map((p, i) => (
        <div key={p.id} className={styles.portRow}>
          <input
            className={styles.input}
            value={p.types}
            placeholder="DATAFRAME, GEODATAFRAME"
            onChange={(e) => patch(i, { types: e.target.value })}
          />
          <select
            className={styles.select}
            value={p.cardinality}
            onChange={(e) => patch(i, { cardinality: e.target.value })}
          >
            {CARDINALITY_OPTIONS.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
          <button type="button" className={styles.smallBtn} onClick={() => remove(i)}>
            ✕
          </button>
        </div>
      ))}
      <button type="button" className={styles.smallBtn} onClick={add}>
        + Add port
      </button>
    </div>
  );
}

