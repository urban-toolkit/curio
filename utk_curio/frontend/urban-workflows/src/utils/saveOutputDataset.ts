import { defaultSaveOutputDatasetFromEnv } from "./curioEnvFlag";

/** Workflow-wide default when a node has no explicit ``saveOutputDataset`` (env + UI). */
export const DEFAULT_SAVE_OUTPUT_DATASET = defaultSaveOutputDatasetFromEnv();

/** Whether a node run should write catalog parquet + auto-install. */
export function resolveSaveOutputDataset(
  data: { saveOutputDataset?: boolean } | null | undefined,
  defaultSave: boolean = DEFAULT_SAVE_OUTPUT_DATASET,
): boolean {
  if (data && typeof data.saveOutputDataset === "boolean") {
    return data.saveOutputDataset;
  }
  return defaultSave;
}
