import { useEffect, useState } from "react";
import {
  DatasetCatalogItem,
  DatasetSchemaField,
  datasetCatalogApi,
} from "../../../services/datasetCatalog";

export interface ResolvedDatasetSchema {
  fields: DatasetSchemaField[];
  geometryType?: string | null;
  fetching: boolean;
  unsupportedMessage: string | null;
}

const EMPTY: ResolvedDatasetSchema = {
  fields: [],
  geometryType: null,
  fetching: false,
  unsupportedMessage: null,
};

/**
 * Single source of truth for a dataset's schema fields in the detail panel.
 * Uses the catalog item's schema when present, otherwise resolves it from the
 * preview API — so the header/info column counts and the schema sidebar all
 * agree. No placeholder fields are fabricated.
 */
export function useDatasetResolvedSchema(
  dataset: DatasetCatalogItem | null,
  dataflowId: string | null = null,
  liveOutputs?: Array<{ node_id: string; filename: string; data_type?: string }>,
): ResolvedDatasetSchema {
  const inlineFields = dataset?.schema?.fields?.length ? dataset.schema.fields : null;
  const [resolved, setResolved] = useState<ResolvedDatasetSchema>(() =>
    inlineFields
      ? {
          fields: inlineFields,
          geometryType: dataset?.schema?.geometryType,
          fetching: false,
          unsupportedMessage: null,
        }
      : { ...EMPTY, fetching: dataset != null },
  );

  useEffect(() => {
    if (!dataset) {
      setResolved(EMPTY);
      return;
    }
    if (dataset.schema?.fields?.length) {
      setResolved({
        fields: dataset.schema.fields,
        geometryType: dataset.schema.geometryType,
        fetching: false,
        unsupportedMessage: null,
      });
      return;
    }

    let cancelled = false;
    setResolved({ ...EMPTY, fetching: true });
    void datasetCatalogApi
      .preview(dataset.id, { dataflowId, liveOutputs, offset: 0, rowLimit: 1 })
      .then((response) => {
        if (cancelled) return;
        if (response.unsupported) {
          setResolved({
            ...EMPTY,
            unsupportedMessage: response.message || "Schema is not available for this dataset yet.",
          });
          return;
        }
        const bundleParts = response.schema?.bundleParts as
          | Array<{ label?: string; format?: string; kind?: string }>
          | undefined;
        const fields = bundleParts?.length
          ? bundleParts.map((part, index) => ({
              name: part.label || `Part ${index + 1}`,
              type: (part.format || "json").toUpperCase(),
              nullable: true,
            }))
          : response.schema?.fields || [];
        setResolved({
          fields,
          geometryType: response.schema?.geometryType ?? dataset.schema?.geometryType,
          fetching: false,
          unsupportedMessage: null,
        });
      })
      .catch(() => {
        if (!cancelled) {
          setResolved({
            ...EMPTY,
            unsupportedMessage: "Schema could not be loaded.",
          });
        }
      });

    return () => {
      cancelled = true;
    };
  }, [dataflowId, dataset?.id, dataset?.schema?.fields, liveOutputs]);

  return resolved;
}
