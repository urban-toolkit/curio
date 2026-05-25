import React, { memo, useCallback } from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { Tooltip, OverlayTrigger } from "react-bootstrap";
import { useReactFlow } from "reactflow";
import { NODE_CATEGORY_SHORT_LABEL } from "../../../../constants/nodeCategoryShortLabels";
import { NodeDescriptor } from "../../../../registry/types";
import { getFlowNodeCanonicalType } from "../../../../utils/flowNodeCanonicalType";
import packageStyles from "./ToolsMenuPackagePalette.module.css";
import { OVERLAY_TRIGGER_DELAY_PROPS, type ToolsMenuTooltipSide } from "./uiConstants";

export const PackageTemplateRow = memo(function PackageTemplateRow({
    desc,
    tooltipPlacement = "right",
}: {
    desc: NodeDescriptor;
    tooltipPlacement?: ToolsMenuTooltipSide;
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
        <OverlayTrigger
            placement={tooltipPlacement}
            delay={OVERLAY_TRIGGER_DELAY_PROPS}
            overlay={
                <Tooltip>
                    {desc.label}
                    {desc.description ? ` — ${desc.description}` : ""}
                </Tooltip>
            }
        >
            <div className={packageStyles.packageKindRow}>
                <div
                    className={packageStyles.packageKindRowDrag}
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
        </OverlayTrigger>
    );
});
