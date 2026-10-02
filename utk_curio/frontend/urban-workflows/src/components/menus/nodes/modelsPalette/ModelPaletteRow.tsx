import React, { memo, useCallback } from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faBrain } from "@fortawesome/free-solid-svg-icons";
import { useReactFlow } from "reactflow";

import {
  MODEL_RUNTIME_LABEL,
  beginModelDrag,
  endModelDrag,
  nodeLinkedModelIds,
  writeModelDragData,
  type ModelRow,
} from "../../../../services/modelCatalog";
import { modelLabelCount } from "../../../models/catalog/modelFacts";
import { focusLinkedNodes } from "../../../../utils/focusDatasetNodes";
import { useToastContext } from "../../../../providers/ToastProvider";
import { DetailsButton } from "../../../DetailsButton";
import packageStyles from "../toolsMenuPackagePalette/ToolsMenuPackagePalette.module.css";
import rowStyles from "./ModelPaletteRow.module.css";

/**
 * One model in the MODELS palette. Mirrors the Datasets and Agents rows
 * (reusing the shared `packageKind*` classes): a draggable avatar writing the
 * model drag so a node can take it, a meta button showing the name, the id
 * and two chips, and the way into the details. The meta button selects the
 * canvas nodes that run this model, as a dataset row selects the nodes that
 * load its dataset.
 */
export const ModelPaletteRow = memo(function ModelPaletteRow({
  model,
  onOpenDetails,
}: {
  model: ModelRow;
  onOpenDetails: (model: ModelRow) => void;
}) {
  const reactFlow = useReactFlow();
  const { showToast } = useToastContext();

  const selectOnCanvas = useCallback(
    (e: React.MouseEvent) => {
      e.stopPropagation();
      e.preventDefault();
      const isLinked = (n: { id: string; data: any }) =>
        nodeLinkedModelIds(n.data).includes(model.id);
      if (focusLinkedNodes(reactFlow, isLinked) === 0) {
        showToast("No nodes on the canvas use this model", "info");
      }
    },
    [model.id, reactFlow, showToast],
  );

  return (
    // The cross-surface identity attribute, matching data-dataset-id on a
    // dataset row and data-agent-coord on an agent one.
    <div className={packageStyles.packageKindRow} data-model-id={model.id}>
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
            {MODEL_RUNTIME_LABEL[model.runtime] ?? model.runtime}
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
