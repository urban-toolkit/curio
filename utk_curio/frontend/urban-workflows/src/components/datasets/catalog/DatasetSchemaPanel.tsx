import React, { useEffect, useMemo, useState } from "react";
import {
  DatasetCatalogItem,
  DatasetSchemaField,
  datasetCatalogApi,
} from "../../../services/datasetCatalog";
import { defaultSchemaFields } from "./datasetDetailHelpers";
import {
  fieldIconGlyph,
  fieldIconKind,
  isPrimaryKeyField,
  normalizeFieldType,
  schemaStats,
} from "./schemaFieldMeta";
import styles from "./DatasetSchemaPanel.module.css";

const ICON_CLASS: Record<ReturnType<typeof fieldIconKind>, string> = {
  geometry: styles.iconGeometry,
  integer: styles.iconInteger,
  string: styles.iconString,
  float: styles.iconFloat,
  boolean: styles.iconBoolean,
};

export interface DatasetSchemaPanelProps {
  dataset: DatasetCatalogItem;
  dataflowId?: string | null;
  liveOutputs?: Array<{ node_id: string; filename: string; data_type?: string }>;
}

export const DatasetSchemaPanel: React.FC<DatasetSchemaPanelProps> = ({
  dataset,
  dataflowId = null,
  liveOutputs,
}) => {
  const [filter, setFilter] = useState("");
  const [fields, setFields] = useState<DatasetSchemaField[]>(
    dataset.schema?.fields?.length ? dataset.schema.fields : defaultSchemaFields(dataset),
  );
  const [geometryType, setGeometryType] = useState<string | null | undefined>(dataset.schema?.geometryType);
  const [fetching, setFetching] = useState(!dataset.schema?.fields?.length);
  const [unsupportedMessage, setUnsupportedMessage] = useState<string | null>(null);

  useEffect(() => {
    setFilter("");
    if (dataset.schema?.fields?.length) {
      setFields(dataset.schema.fields);
      setGeometryType(dataset.schema.geometryType);
      setUnsupportedMessage(null);
      setFetching(false);
      return;
    }

    let cancelled = false;
    setFetching(true);
    void datasetCatalogApi
      .preview(dataset.id, { dataflowId, liveOutputs, offset: 0, rowLimit: 1 })
      .then((response) => {
        if (cancelled) return;
        if (response.unsupported) {
          setFields(defaultSchemaFields(dataset));
          setUnsupportedMessage(response.message || null);
          return;
        }
        const bundleParts = response.schema?.bundleParts as
          | Array<{ label?: string; format?: string; kind?: string }>
          | undefined;
        const previewFields = bundleParts?.length
          ? bundleParts.map((part, index) => ({
              name: part.label || `Part ${index + 1}`,
              type: (part.format || "json").toUpperCase(),
              nullable: true,
            }))
          : response.schema?.fields?.length
            ? response.schema.fields
            : defaultSchemaFields(dataset);
        setFields(previewFields);
        setGeometryType(response.schema?.geometryType ?? dataset.schema?.geometryType);
        setUnsupportedMessage(null);
      })
      .catch(() => {
        if (!cancelled) {
          setFields(defaultSchemaFields(dataset));
          setUnsupportedMessage(null);
        }
      })
      .finally(() => {
        if (!cancelled) setFetching(false);
      });

    return () => {
      cancelled = true;
    };
  }, [dataflowId, dataset.id, dataset.schema?.fields, liveOutputs]);

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
        {filteredFields.length === 0 ? (
          <div className={styles.state}>No fields match the current filter.</div>
        ) : null}
      </div>

      <div className={styles.footer}>
        {stats.fieldCount} fields · {stats.nullableCount} nullable · {stats.geometryCount} geometry
        {unsupportedMessage ? ` · ${unsupportedMessage}` : ""}
      </div>
    </section>
  );
};
