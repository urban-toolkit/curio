import { useCallback, useEffect, useMemo, useState, type DragEvent } from "react";

import { useToastContext } from "../../../providers/ToastProvider";
import {
  beginModelDrag,
  endModelDrag,
  sortModels,
  useModelCatalog,
  writeModelDragData,
  type ModelRow,
  type ModelSortMode,
} from "../../../services/modelCatalog";
import { useModelDelete } from "./useModelDelete";

/**
 * The canvas Model Catalog drawer's state, kept out of the component the way
 * `useDatasetCatalogDrawer` keeps the Data drawer's.
 *
 * Smaller than its peer on purpose: a model is not installed into a dataflow,
 * so there is no "In project" tab and nothing to add or remove. What is left is
 * the search, the drag and the delete of a downloaded model.
 */
export function useModelCatalogDrawer(presented: boolean) {
  const { showToast } = useToastContext();
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [sort, setSort] = useState<ModelSortMode>("shipped");
  const [pinned, setPinned] = useState(false);
  // Its own state, not shared with anything that selects: a card's
  // "View details" opens the modal and nothing else.
  const [detailModel, setDetailModel] = useState<ModelRow | null>(null);

  useEffect(() => {
    const handle = window.setTimeout(() => setDebouncedSearch(search), 280);
    return () => window.clearTimeout(handle);
  }, [search]);

  const catalog = useModelCatalog({ q: debouncedSearch, enabled: presented });
  const items = useMemo(() => sortModels(catalog.data.items, sort), [catalog.data.items, sort]);
  const { confirmAction, requestDelete, dismissConfirm, busyId } = useModelDelete(showToast);

  const handleModelDragStart = useCallback((model: ModelRow, event: DragEvent<HTMLElement>) => {
    writeModelDragData(event.dataTransfer, beginModelDrag(model));
  }, []);

  const handleModelDragEnd = useCallback(() => {
    endModelDrag();
  }, []);

  return {
    search,
    setSearch,
    sort,
    setSort,
    pinned,
    setPinned,
    busyId,
    catalog,
    items,
    onDelete: requestDelete,
    confirmAction,
    dismissConfirm,
    handleModelDragStart,
    handleModelDragEnd,
    detailModel,
    openModelDetails: setDetailModel,
    closeModelDetails: useCallback(() => setDetailModel(null), []),
  };
}
