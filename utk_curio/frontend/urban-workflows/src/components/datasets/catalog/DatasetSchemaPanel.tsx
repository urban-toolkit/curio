import React, { useMemo, useState } from "react";
import {
  fieldIconGlyph,
  fieldIconKind,
  isPrimaryKeyField,
  normalizeFieldType,
  schemaStats,
} from "./schemaFieldMeta";
import type { ResolvedDatasetSchema } from "./useDatasetResolvedSchema";
import styles from "./DatasetSchemaPanel.module.css";

const ICON_CLASS: Record<ReturnType<typeof fieldIconKind>, string> = {
  geometry: styles.iconGeometry,
  integer: styles.iconInteger,
  string: styles.iconString,
  float: styles.iconFloat,
  boolean: styles.iconBoolean,
};

export interface DatasetSchemaPanelProps {
  schema: ResolvedDatasetSchema;
}

export const DatasetSchemaPanel: React.FC<DatasetSchemaPanelProps> = ({ schema }) => {
  const { fields, geometryType, fetching, unsupportedMessage } = schema;
  const [filter, setFilter] = useState("");

  const filteredFields = useMemo(() => {
    const needle = filter.trim().toLowerCase();
    if (!needle) return fields;
    return fields.filter((field) => field.name.toLowerCase().includes(needle));
  }, [fields, filter]);

  const stats = schemaStats(fields, geometryType);

  return (
    <section className={styles.panel}>
      <div className={styles.header}>
        <h2>Schema</h2>
        <span className={styles.countBadge}>{fields.length}</span>
        <input
          className={styles.filterInput}
          type="search"
          placeholder="Filter fields..."
          value={filter}
          onChange={(event) => setFilter(event.target.value)}
          aria-label="Filter schema fields"
        />
      </div>

      {fetching && fields.length === 0 ? (
        <div className={styles.state}>Loading schema...</div>
      ) : null}
      {!fetching && unsupportedMessage && fields.length === 0 ? (
        <div className={styles.state}>{unsupportedMessage}</div>
      ) : null}

      <div className={`${styles.tableWrap} ${fetching ? styles.panelRefreshing : ""}`}>
        <div className={styles.headRow}>
          <span>Field</span>
          <span>Type</span>
          <span>Null</span>
        </div>
        {filteredFields.map((field, index) => {
          const kind = fieldIconKind(field.type);
          const sourceIndex = fields.findIndex((item) => item.name === field.name);
          return (
            <div className={styles.fieldRow} key={field.name}>
              <div className={styles.fieldCell}>
                <span className={`${styles.typeIcon} ${ICON_CLASS[kind]}`}>
                  {fieldIconGlyph(kind)}
                </span>
                <span className={styles.fieldName}>{field.name}</span>
                {isPrimaryKeyField(field, sourceIndex >= 0 ? sourceIndex : index, fields) ? (
                  <span className={styles.pkBadge}>PK</span>
                ) : null}
              </div>
              <span className={styles.typeCell}>{normalizeFieldType(field.type)}</span>
              <span className={styles.nullCell}>{field.nullable ? "null" : ""}</span>
            </div>
          );
        })}
        {fields.length > 0 && filteredFields.length === 0 ? (
          <div className={styles.state}>No fields match the current filter.</div>
        ) : null}
      </div>

      <div className={styles.footer}>
        {stats.fieldCount} fields · {stats.nullableCount} nullable · {stats.geometryCount} geometry
      </div>
    </section>
  );
};
