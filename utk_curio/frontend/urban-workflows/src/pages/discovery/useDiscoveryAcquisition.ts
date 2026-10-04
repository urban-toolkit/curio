import {
  useDatasetDetails,
  viewDatasetDetailsToast,
} from "../../components/datasets/catalog/datasetDetailsContext";
import { useToastContext } from "../../providers/ToastProvider";
import {
  notifyDatasetCatalogRefresh,
  useDiscoveryAcquire,
  type DiscoveryAcquireJob,
  type UseDiscoveryAcquireResult,
} from "../../services/discoveryCatalog";
import { notifyModelCatalogRefresh } from "../../services/modelCatalog";

export interface DiscoveryAcquisitionOptions {
  /** Whether the job came from a storage source, whose files are added
   *  rather than downloaded. */
  isStorage: (job: DiscoveryAcquireJob) => boolean;
  /** Where "View model" goes for a model source's add. */
  onViewModel: (modelId: string) => void;
}

/**
 * Downloads from the Discovery Catalog, each reported where it landed: a
 * dataset in the Data Catalog, a model in the Model Catalog. One hook for
 * every surface that downloads (the browse page, a source's page and the
 * canvas drawer), so all of them say the same thing.
 *
 * A finished download is a new dataset or model, so every surface that lists
 * them, in this tab and in any other, is told. Skipping that is how the
 * download succeeds and the dataset appears to be missing.
 */
export function useDiscoveryAcquisition({
  isStorage,
  onViewModel,
}: DiscoveryAcquisitionOptions): UseDiscoveryAcquireResult {
  // The same details modal the Data Catalog opens, over the current page, so
  // the search that found the resource is still there when it closes.
  const { openDatasetDetails } = useDatasetDetails();
  const { showToast } = useToastContext();

  return useDiscoveryAcquire((job) => {
    if (job.model?.id) {
      notifyModelCatalogRefresh();
      const modelId = job.model.id;
      const name = job.model.name || modelId;
      const view = { action: { label: "View model", onClick: () => onViewModel(modelId) } };
      if (job.alreadyPresent) {
        showToast(`${name} is already in your Model Catalog.`, "info", view);
      } else if (job.dependencies?.dependencyError) {
        showToast(
          `Added ${name} to your Model Catalog, but its libraries did not install: ${job.dependencies.dependencyError}`,
          "warning",
          view,
        );
      } else {
        showToast(`Added ${name} to your Model Catalog.`, "success", view);
      }
      return;
    }
    notifyDatasetCatalogRefresh();
    // Reported like an import into the Data Catalog, which is what it is.
    if (job.datasetId) {
      const title = typeof job.dataset?.title === "string" ? job.dataset.title : "The dataset";
      if (job.alreadyPresent && job.unchanged) {
        showToast(
          `Nothing has changed in ${title} since it was added.`,
          "info",
          viewDatasetDetailsToast(openDatasetDetails, job.datasetId),
        );
        return;
      }
      showToast(
        `${isStorage(job) ? "Added" : "Downloaded"} ${title} to your Data Catalog${job.note ? `; ${job.note}` : ""}.`,
        job.note ? "warning" : "success",
        viewDatasetDetailsToast(openDatasetDetails, job.datasetId),
      );
    }
  });
}
