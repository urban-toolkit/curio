import React, { memo, useCallback } from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faBrain } from "@fortawesome/free-solid-svg-icons";
import { useReactFlow } from "reactflow";

import {
  beginModelDrag,
  endModelDrag,
  isModelPackage,
  nodeLinkedModelIds,
  writeModelDragData,
  type PackagePayload,
} from "../../../../services/packages";
import { modelLabelCount, modelRuntimeLabel } from "../../../models/catalog/modelFacts";
import { focusLinkedNodes } from "../../../../utils/focusDatasetNodes";
import { useNotebookViewContext } from "../../../../providers/flow/notebookViewContext";
import { useToastContext } from "../../../../providers/ToastProvider";
import { DetailsButton } from "../../../DetailsButton";
import packageStyles from "../toolsMenuPackagePalette/ToolsMenuPackagePalette.module.css";
import rowStyles from "./ModelPaletteRow.module.css";

/**
 * One model package in the MODELS palette. Mirrors the Datasets and Agents
 * rows (reusing the shared `packageKind*` classes): a draggable avatar writing
 * the model drag so a node can take it, a meta button showing the name, the
 * package folder and two chips, and the way into the details. The meta button
 * selects the canvas nodes that run this model, as a dataset row selects the
 * nodes that load its dataset.
 */
export const ModelPaletteRow = memo(function ModelPaletteRow({
  model,
  onOpenDetails,
}: {
  model: PackagePayload;
  onOpenDetails: (model: PackagePayload) => void;
}) {
  const reactFlow = useReactFlow();
  const { reveal } = useNotebookViewContext();
  const { showToast } = useToastContext();
  const modelId = model.packageId;

  const selectOnCanvas = useCallback(
    (e: React.MouseEvent) => {
      e.stopPropagation();
      e.preventDefault();
      const isLinked = (n: { id: string; data: any }) =>
        nodeLinkedModelIds(n.data).includes(modelId);
      if (focusLinkedNodes(reactFlow, isLinked, reveal) === 0) {
        showToast("No nodes on the canvas use this model", "info");
      }
    },
    [modelId, reactFlow, showToast, reveal],
  );
  if (!isModelPackage(model)) return null;

  return (
    // The cross-surface identity attribute, matching data-dataset-id on a
    // dataset row and data-agent-coord on an agent one.
    <div className={packageStyles.packageKindRow} data-model-id={modelId}>
      <div
        className={`${packageStyles.packageKindRowDrag} ${rowStyles.avatar_model}`}
        draggable
        onDragStart={(event) => {
          writeModelDragData(event.dataTransfer, beginModelDrag(model));
        }}
        onDragEnd={() => endModelDrag()}
        title="Drag onto a node that runs a model"
      >
        <FontAwesomeIcon icon={faBrain} className={rowStyles.avatarIcon} />
      </div>
      <button
        type="button"
        className={packageStyles.packageKindRowMeta}
        onClick={selectOnCanvas}
        title={model.description || model.name}
      >
        <span className={packageStyles.packageKindRowLabel}>{model.name}</span>
        <span className={rowStyles.modelId}>{model.dirName}</span>
        <span className={rowStyles.pills}>
          <span className={`${packageStyles.packageKindCategoryChip} ${rowStyles.chip_model}`}>
            {modelRuntimeLabel(model)}
          </span>
          <span className={packageStyles.packageKindCategoryChip}>{modelLabelCount(model)}</span>
        </span>
      </button>
      {/* The way into the model's details, as every catalog card offers. */}
      <DetailsButton
        label={`View ${model.name} details`}
        className={rowStyles.detailsButton}
        onClick={() => onOpenDetails(model)}
      />
    </div>
  );
});
