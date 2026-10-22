import React, { memo, useCallback } from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { useReactFlow } from "reactflow";
import { NODE_CATEGORY_SHORT_LABEL } from "../../../../constants/nodeCategoryShortLabels";
import { NodeDescriptor } from "../../../../registry/types";
import { getFlowNodeCanonicalType } from "../../../../utils/flowNodeCanonicalType";
import packageStyles from "./ToolsMenuPackagePalette.module.css";

export const PackageTemplateRow = memo(function PackageTemplateRow({
    desc,
}: {
    desc: NodeDescriptor;
}) {
    const { setNodes } = useReactFlow();

    const selectOnCanvas = useCallback(
        (e: React.MouseEvent) => {
            e.stopPropagation();
            e.preventDefault();
            setNodes((nds) =>
                nds.map((n) => ({
                    ...n,
                    selected: getFlowNodeCanonicalType(n) === desc.id,
                })),
            );
        },
        [desc.id, setNodes],
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
