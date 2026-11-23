import React, { memo, useCallback } from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { useStoreApi } from "reactflow";
import { NODE_CATEGORY_SHORT_LABEL } from "../../../../constants/nodeCategoryShortLabels";
import { NodeDescriptor } from "../../../../registry/types";
import { getFlowNodeCanonicalType } from "../../../../utils/flowNodeCanonicalType";
import { selectOnly } from "../../../../utils/focusDatasetNodes";
import { paletteItemAttrs } from "../toolsPaletteDismiss";
import packageStyles from "./ToolsMenuPackagePalette.module.css";

export const PackageTemplateRow = memo(function PackageTemplateRow({
    desc,
}: {
    desc: NodeDescriptor;
}) {
    const flowStore = useStoreApi();

    // The canvas's nodes of this kind become its selection, by their ids.
    const selectOnCanvas = useCallback(
        (e: React.MouseEvent) => {
            e.stopPropagation();
            e.preventDefault();
            const ofThisKind = flowStore.getState().getNodes()
                .filter((n) => getFlowNodeCanonicalType(n) === desc.id)
                .map((n) => n.id);
            selectOnly(flowStore, ofThisKind);
        },
        [desc.id, flowStore],
    );

    return (
        // Its tooltip opens to the right, as every tool rail palette row's does.
        <div
            className={packageStyles.packageKindRow}
            data-tooltip={desc.description ? `${desc.label}: ${desc.description}` : desc.label}
            data-tooltip-side="right"
        >
            <div
                className={packageStyles.packageKindRowDrag}
                data-pkg-template-id={String(desc.id)}
                {...paletteItemAttrs("packages", String(desc.id))}
                draggable
                onDragStart={(event) => {
                    event.dataTransfer.setData("application/reactflow", String(desc.id));
                    event.dataTransfer.effectAllowed = "move";
                }}
            >
                <FontAwesomeIcon icon={desc.icon} className={packageStyles.packageKindDragIcon} />
                {desc.badge ? (
                    <span className={packageStyles.packageKindDragBadge}>{desc.badge}</span>
                ) : null}
            </div>
            <button
                type="button"
                className={packageStyles.packageKindRowMeta}
                onClick={selectOnCanvas}
            >
                <span className={packageStyles.packageKindRowLabel}>{desc.label}</span>
                <span className={packageStyles.packageKindCategoryChip}>{NODE_CATEGORY_SHORT_LABEL[desc.category]}</span>
            </button>
        </div>
    );
});
