/**
 * A file from the computer, dropped on the canvas or on a node, or chosen in a
 * dataset widget: imported into the account's Data Catalog as Import dataset
 * imports it, then added to this dataflow as Add to project adds it
 * (`addDatasetToDataflow`). What comes back is the dataset's drag payload, so
 * the drop then goes the way a Data Catalog card's drop goes: MainCanvas makes
 * a Data Loading node of it, and a node (NodeContainer) sets its dataset
 * widget or writes its loader into the code.
 */
import { useCallback } from "react";
import { useFlowContext } from "../../providers/FlowProvider";
import { useToastContext } from "../../providers/ToastProvider";
import { hostedGuestSignInNote, useHostedGuest } from "../apiSettings/useHostedGuest";
import {
  IMPORTABLE_DATASET_EXTENSIONS,
  createDatasetDragPayload,
  datasetCatalogApi,
  isLayerGroupId,
  type DatasetCatalogItem,
  type DatasetDragPayload,
} from "../../services/datasetCatalog";
import { addDatasetToDataflow } from "./catalog/dataflowDatasetRef";

/** Whether a drag carries files from the computer. */
export function hasFileDrag(dataTransfer: DataTransfer | null | undefined): boolean {
  return Array.from(dataTransfer?.types || []).includes("Files");
}

/** Whether Import dataset takes a file named *name*. A lone `.shp` goes too:
 * the import says how to zip it with its sidecar files. */
export function importableFileName(name: string): boolean {
  const lower = name.toLowerCase();
  return lower.endsWith(".shp") || IMPORTABLE_DATASET_EXTENSIONS.some((ext) => lower.endsWith(ext));
}

/** What a file Import dataset does not take is told. */
export function notImportableMessage(name: string): string {
  return (
    `Curio cannot load ${name}. Drop a CSV, GeoJSON, JSON, Parquet, GeoTIFF, NetCDF, ONNX, ` +
    "OSM (.pbf) or GeoPackage file, or a .zip holding one shapefile."
  );
}

/** Imports the one file of *files* and adds it to this dataflow; null, with a
 * toast saying why, when it cannot. */
export function useDataFileImport(): (files: readonly File[]) => Promise<DatasetDragPayload | null> {
  const { ensureProjectId, setDataflowDatasets } = useFlowContext();
  const hostedGuest = useHostedGuest();
  const { showToast } = useToastContext();
  return useCallback(
    async (files: readonly File[]) => {
      if (files.length === 0) return null;
      if (files.length > 1) {
        showToast("Drop one file at a time.", "warning");
        return null;
      }
      const file = files[0];
      if (!importableFileName(file.name)) {
        showToast(notImportableMessage(file.name), "error");
        return null;
      }
      // The dataflow it goes into, saved first if it never was. A hosted guest
      // cannot save one, so it is told to sign in, as Add to project tells it.
      const dataflowId = await ensureProjectId();
      if (!dataflowId) {
        if (hostedGuest) showToast(hostedGuestSignInNote("add datasets"), "warning");
        return null;
      }
      showToast(`Importing ${file.name} into the Data Catalog...`, "info");
      try {
        const imported = await datasetCatalogApi.importDataset(file, { dataflowId });
        // A file of several layers (an OSM extract, a GeoPackage) becomes one
        // dataset per layer, in the group each of them names.
        const groupId = typeof imported.groupId === "string" && isLayerGroupId(imported.groupId)
          ? imported.groupId
          : null;
        const dataset: DatasetCatalogItem = groupId
          ? await datasetCatalogApi.getDataset(groupId, { dataflowId })
          : imported;
        await addDatasetToDataflow(dataflowId, dataset, setDataflowDatasets);
        return createDatasetDragPayload(dataset);
      } catch (err) {
        showToast((err as Error)?.message || `Could not import ${file.name}.`, "error");
        return null;
      }
    },
    [ensureProjectId, setDataflowDatasets, hostedGuest, showToast],
  );
}
